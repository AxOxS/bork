"""AST-level optimisation pass, run after type checking.

Everything here is type-directed: because the checker has already annotated the
tree, folding knows whether `+` means int addition, float addition or string
concatenation, and can apply the exact runtime semantics -- 64-bit wrapping,
truncating division -- by calling the same helpers the VM calls. Reimplementing
them here in terms of Python's operators would make the compiler and the
interpreter disagree about arithmetic, which is the one thing a constant folder
must never do.

Operations that can trap at runtime (division by zero) are deliberately left
alone so the error still surfaces where the programmer wrote it.
"""
from __future__ import annotations

import math

from . import ast_nodes as A
from . import types as T
from .values import idiv, imod, wrap64

LITERALS = (A.IntLit, A.FloatLit, A.BoolLit, A.StrLit)


def literal_value(node):
    return node.value if isinstance(node, LITERALS) else None


def make_literal(value, span, ty):
    if isinstance(value, bool):
        node = A.BoolLit(span, value)
    elif isinstance(value, int):
        node = A.IntLit(span, wrap64(value))
    elif isinstance(value, float):
        node = A.FloatLit(span, value)
    elif isinstance(value, str):
        node = A.StrLit(span, value)
    else:
        raise TypeError(f"not a literal value: {value!r}")
    node.ty = ty
    return node


class Optimizer:
    def __init__(self):
        self.folds = 0

    @property
    def total(self) -> int:
        return self.folds

    # -- driver ------------------------------------------------------------
    def run(self, module: A.Module) -> A.Module:
        module.stmts = self.stmt_list(module.stmts)
        return module

    def stmt_list(self, stmts: list) -> list:
        return [self.stmt(s) for s in stmts]

    # -- statements --------------------------------------------------------
    def stmt(self, stmt):
        if isinstance(stmt, A.Block):
            stmt.stmts = self.stmt_list(stmt.stmts)
            return stmt
        if isinstance(stmt, A.FnDecl):
            stmt.body = self.stmt(stmt.body)
            return stmt
        if isinstance(stmt, A.LetStmt):
            stmt.init = self.expr(stmt.init)
            return stmt
        if isinstance(stmt, A.AssignStmt):
            stmt.target = self.expr(stmt.target)
            stmt.value = self.expr(stmt.value)
            return stmt
        if isinstance(stmt, A.ExprStmt):
            stmt.expr = self.expr(stmt.expr)
            return stmt
        if isinstance(stmt, A.IfStmt):
            stmt.cond = self.expr(stmt.cond)
            stmt.then = self.stmt(stmt.then)
            if stmt.otherwise is not None:
                stmt.otherwise = self.stmt(stmt.otherwise)
            return stmt
        if isinstance(stmt, A.WhileStmt):
            stmt.cond = self.expr(stmt.cond)
            stmt.body = self.stmt(stmt.body)
            return stmt
        if isinstance(stmt, A.ForRange):
            stmt.start = self.expr(stmt.start)
            stmt.end = self.expr(stmt.end)
            stmt.body = self.stmt(stmt.body)
            return stmt
        if isinstance(stmt, A.ForIn):
            stmt.iterable = self.expr(stmt.iterable)
            stmt.body = self.stmt(stmt.body)
            return stmt
        if isinstance(stmt, A.ReturnStmt):
            if stmt.value is not None:
                stmt.value = self.expr(stmt.value)
            return stmt
        return stmt

    # -- expressions -------------------------------------------------------
    def expr(self, e):
        if isinstance(e, A.Unary):
            e.operand = self.expr(e.operand)
            value = literal_value(e.operand)
            if value is not None:
                if e.op == "-" and isinstance(value, (int, float)) and not isinstance(value, bool):
                    self.folds += 1
                    return make_literal(-value, e.span, e.ty)
                if e.op == "!" and isinstance(value, bool):
                    self.folds += 1
                    return make_literal(not value, e.span, e.ty)
            return e

        if isinstance(e, A.Binary):
            e.left = self.expr(e.left)
            e.right = self.expr(e.right)
            folded = self.fold_binary(e)
            if folded is not None:
                self.folds += 1
                return folded
            return self.simplify_binary(e)

        if isinstance(e, A.Logical):
            e.left = self.expr(e.left)
            e.right = self.expr(e.right)
            if isinstance(e.left, A.BoolLit):
                self.folds += 1
                # Short-circuiting means the right operand simply disappears.
                if e.op == "&&":
                    return e.right if e.left.value else make_literal(False, e.span, T.BOOL)
                return make_literal(True, e.span, T.BOOL) if e.left.value else e.right
            return e

        if isinstance(e, A.Call):
            e.callee = self.expr(e.callee)
            e.args = [self.expr(a) for a in e.args]
            return e
        if isinstance(e, A.Index):
            e.obj = self.expr(e.obj)
            e.index = self.expr(e.index)
            return e
        if isinstance(e, A.FieldAccess):
            e.obj = self.expr(e.obj)
            return e
        if isinstance(e, A.ArrayLit):
            e.elements = [self.expr(x) for x in e.elements]
            return e
        if isinstance(e, A.StructLit):
            e.fields = [(n, self.expr(v), s) for n, v, s in e.fields]
            return e
        return e

    def fold_binary(self, e: A.Binary):
        left, right = literal_value(e.left), literal_value(e.right)
        if left is None or right is None:
            return None
        op = e.op
        try:
            if e.kind == "int":
                if op in ("/", "%") and right == 0:
                    return None                     # let it trap at runtime
                # idiv/imod/wrap64 are the VM's, so folding cannot drift from it.
                table = {"+": lambda: left + right, "-": lambda: left - right,
                         "*": lambda: left * right, "/": lambda: idiv(left, right),
                         "%": lambda: imod(left, right)}
                if op in table:
                    return make_literal(wrap64(table[op]()), e.span, T.INT)
            elif e.kind == "float":
                if op in ("/", "%") and right == 0.0:
                    return None
                table = {"+": lambda: left + right, "-": lambda: left - right,
                         "*": lambda: left * right, "/": lambda: left / right,
                         "%": lambda: math.fmod(left, right)}
                if op in table:
                    return make_literal(table[op](), e.span, T.FLOAT)
            elif e.kind == "str" and op == "+":
                return make_literal(left + right, e.span, T.STR)

            if op in ("==", "!=", "<", "<=", ">", ">="):
                cmp = {"==": left == right, "!=": left != right, "<": left < right,
                       "<=": left <= right, ">": left > right, ">=": left >= right}[op]
                return make_literal(bool(cmp), e.span, T.BOOL)
        except (ArithmeticError, TypeError, ValueError):
            return None
        return None

    def simplify_binary(self, e: A.Binary):
        """Identities that hold exactly. Only applied to int and str, because
        float identities are unsound around NaN and signed zero."""
        left, right = literal_value(e.left), literal_value(e.right)
        if e.kind == "int":
            if e.op == "+" and right == 0:
                self.folds += 1; return e.left
            if e.op == "+" and left == 0:
                self.folds += 1; return e.right
            if e.op == "-" and right == 0:
                self.folds += 1; return e.left
            if e.op == "*" and right == 1:
                self.folds += 1; return e.left
            if e.op == "*" and left == 1:
                self.folds += 1; return e.right
            if e.op == "/" and right == 1:
                self.folds += 1; return e.left
        if e.kind == "str" and e.op == "+":
            if right == "":
                self.folds += 1; return e.left
            if left == "":
                self.folds += 1; return e.right
        return e


def optimize(module: A.Module) -> Optimizer:
    opt = Optimizer()
    opt.run(module)
    return opt
