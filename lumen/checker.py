"""Semantic analysis: name resolution, type checking and storage allocation.

The checker annotates the AST in place: expressions get `.ty`, identifiers get
`.ref`, and every binding gets a storage slot. The code generator then never has
to ask a question about names or types, and neither does the VM.

Errors are collected rather than raised at the first one, so a single run can
report everything it found.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import ast_nodes as A
from . import builtins as B
from . import types as T
from .errors import Diagnostic, LumenError, Span


@dataclass
class VarInfo:
    name: str
    ty: T.Type
    mutable: bool
    kind: str          # 'global' | 'local'
    slot: int
    span: Span


class FnCtx:
    """Per-function storage allocation."""

    def __init__(self, name: str):
        self.name = name
        self.nlocals = 0

    def alloc(self) -> int:
        slot = self.nlocals
        self.nlocals += 1
        return slot


ARITH = {"+", "-", "*", "/", "%"}
ORDERING = {"<", "<=", ">", ">="}
EQUALITY = {"==", "!="}


class Checker:
    def __init__(self, source: str = "", filename: str = "<input>"):
        self.source = source
        self.filename = filename
        self.errors: list[Diagnostic] = []

        self.globals: dict[str, VarInfo] = {}
        self.nglobals = 0
        self.scopes: list[dict[str, VarInfo]] = []
        self.loop_depth = 0
        self.entry_ctx = FnCtx("<main>")

    # -- diagnostics -------------------------------------------------------
    def error(self, msg: str, span: Span, note: str | None = None) -> None:
        self.errors.append(Diagnostic(msg, span, note=note))

    # -- scopes ------------------------------------------------------------
    def push_scope(self) -> None:
        self.scopes.append({})

    def pop_scope(self) -> None:
        self.scopes.pop()

    def declare(self, name: str, ty: T.Type, mutable: bool, span: Span) -> VarInfo:
        if self.scopes:
            scope = self.scopes[-1]
            if name in scope:
                self.error(f"'{name}' is already declared in this scope", span,
                           note=f"previous declaration at line {scope[name].span.line}")
            info = VarInfo(name, ty, mutable, "local", self.entry_ctx.alloc(), span)
            scope[name] = info
            return info
        if name in self.globals:
            self.error(f"'{name}' is already declared", span,
                       note=f"previous declaration at line {self.globals[name].span.line}")
        info = VarInfo(name, ty, mutable, "global", self.alloc_global(), span)
        self.globals[name] = info
        return info

    def alloc_global(self) -> int:
        slot = self.nglobals
        self.nglobals += 1
        return slot

    def lookup(self, name: str) -> VarInfo | None:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return self.globals.get(name)

    # -- type expressions --------------------------------------------------
    def resolve_type(self, node: A.Node | None) -> T.Type:
        if node is None:
            return T.UNIT
        if isinstance(node, A.TypeName):
            if node.name in T.PRIMITIVES:
                return T.PRIMITIVES[node.name]
            self.error(f"unknown type '{node.name}'", node.span)
            return T.ERROR
        raise AssertionError(f"unhandled type node {node!r}")

    # -- driver ------------------------------------------------------------
    def check_module(self, module: A.Module) -> A.Module:
        for stmt in module.stmts:
            self.check_stmt(stmt)
        if self.errors:
            raise LumenError(self.errors, self.source, self.filename)
        module.entry_nlocals = self.entry_ctx.nlocals
        return module

    # -- statements --------------------------------------------------------
    def check_block(self, block: A.Block) -> None:
        self.push_scope()
        for stmt in block.stmts:
            self.check_stmt(stmt)
        self.pop_scope()

    def check_stmt(self, stmt: A.Stmt) -> None:
        method = getattr(self, "_stmt_" + type(stmt).__name__, None)
        if method is None:
            raise AssertionError(f"unhandled statement {type(stmt).__name__}")
        method(stmt)

    def _stmt_LetStmt(self, stmt: A.LetStmt) -> None:
        declared = self.resolve_type(stmt.type_expr) if stmt.type_expr else None
        actual = self.check_expr(stmt.init, expected=declared)
        if actual is T.UNIT:
            self.error(f"cannot bind '{stmt.name}' to a value of type `unit`", stmt.init.span)
            actual = T.ERROR
        if declared is not None and not T.compatible(declared, actual):
            self.error(f"expected `{declared}` in the initialiser of '{stmt.name}', found `{actual}`",
                       stmt.init.span)
        ty = declared if declared is not None else actual
        stmt.info = self.declare(stmt.name, ty, stmt.mutable, stmt.span)

    def _stmt_ExprStmt(self, stmt: A.ExprStmt) -> None:
        self.check_expr(stmt.expr)

    def _stmt_Block(self, stmt: A.Block) -> None:
        self.check_block(stmt)

    def _stmt_IfStmt(self, stmt: A.IfStmt) -> None:
        cond = self.check_expr(stmt.cond)
        if cond is not T.BOOL and cond is not T.ERROR:
            self.error(f"`if` condition must be `bool`, found `{cond}`", stmt.cond.span)
        self.check_block(stmt.then)
        if isinstance(stmt.otherwise, A.Block):
            self.check_block(stmt.otherwise)
        elif stmt.otherwise is not None:
            self.check_stmt(stmt.otherwise)

    def _stmt_WhileStmt(self, stmt: A.WhileStmt) -> None:
        cond = self.check_expr(stmt.cond)
        if cond is not T.BOOL and cond is not T.ERROR:
            self.error(f"`while` condition must be `bool`, found `{cond}`", stmt.cond.span)
        self.loop_depth += 1
        self.check_block(stmt.body)
        self.loop_depth -= 1

    def _stmt_BreakStmt(self, stmt: A.BreakStmt) -> None:
        if self.loop_depth == 0:
            self.error("`break` outside of a loop", stmt.span)

    def _stmt_ContinueStmt(self, stmt: A.ContinueStmt) -> None:
        if self.loop_depth == 0:
            self.error("`continue` outside of a loop", stmt.span)

    def _stmt_AssignStmt(self, stmt: A.AssignStmt) -> None:
        target = stmt.target
        target_ty = self.check_expr(target)
        info = target.ref
        if isinstance(info, VarInfo) and not info.mutable:
            self.error(f"cannot assign to '{target.name}' because it is not mutable", target.span,
                       note=f"declare it with `var {target.name} = ...` to make it mutable")
        value_ty = self.check_expr(stmt.value, expected=target_ty)
        if not T.compatible(target_ty, value_ty):
            self.error(f"cannot assign `{value_ty}` to a target of type `{target_ty}`", stmt.value.span)

    # -- expressions -------------------------------------------------------
    def check_expr(self, expr: A.Expr, expected: T.Type | None = None) -> T.Type:
        method = getattr(self, "_expr_" + type(expr).__name__, None)
        if method is None:
            raise AssertionError(f"unhandled expression {type(expr).__name__}")
        ty = method(expr, expected)
        expr.ty = ty
        return ty

    def _expr_IntLit(self, e, expected):
        return T.INT

    def _expr_FloatLit(self, e, expected):
        return T.FLOAT

    def _expr_BoolLit(self, e, expected):
        return T.BOOL

    def _expr_Ident(self, e: A.Ident, expected):
        info = self.lookup(e.name)
        if info is not None:
            e.ref = info
            return info.ty
        if B.lookup(e.name):
            self.error(f"built-in '{e.name}' can only be called, not used as a value", e.span,
                       note=f"write `{e.name}(...)` to call it")
            return T.ERROR
        self.error(f"unknown name '{e.name}'", e.span)
        return T.ERROR

    def _expr_Unary(self, e: A.Unary, expected):
        ty = self.check_expr(e.operand, expected=expected if e.op == "-" else T.BOOL)
        if e.op == "-":
            if ty is T.INT:
                e.kind = "int"
            elif ty is T.FLOAT:
                e.kind = "float"
            elif ty is not T.ERROR:
                self.error(f"cannot negate a value of type `{ty}`", e.span)
                return T.ERROR
            return ty
        if ty is not T.BOOL and ty is not T.ERROR:
            self.error(f"`!` expects `bool`, found `{ty}`", e.span)
            return T.BOOL
        e.kind = "bool"
        return T.BOOL

    def binary_result(self, op: str, left: T.Type, right: T.Type, span: Span):
        """Type and codegen kind for `left op right`. Reports its own errors."""
        if left is T.ERROR or right is T.ERROR:
            return T.ERROR, "int"
        if op in ARITH:
            if left is T.INT and right is T.INT:
                return T.INT, "int"
            if left is T.FLOAT and right is T.FLOAT:
                return T.FLOAT, "float"
            note = None
            if {left, right} == {T.INT, T.FLOAT}:
                note = "Lumen does not convert between numeric types implicitly"
            self.error(f"cannot apply `{op}` to `{left}` and `{right}`", span, note=note)
            return T.ERROR, "int"
        if op in ORDERING:
            if left is right and left in (T.INT, T.FLOAT):
                return T.BOOL, left.name
            self.error(f"cannot compare `{left}` with `{right}` using `{op}`", span,
                       note="ordering comparisons work on `int` and `float`")
            return T.BOOL, "int"
        if op in EQUALITY:
            if left != right:
                self.error(f"cannot compare `{left}` with `{right}`", span)
                return T.BOOL, "int"
            return T.BOOL, "value"
        raise AssertionError(f"unknown operator {op}")

    def _expr_Binary(self, e: A.Binary, expected):
        hint = expected if e.op in ARITH and isinstance(expected, T.Primitive) else None
        left = self.check_expr(e.left, expected=hint)
        right = self.check_expr(e.right, expected=left if left is not T.ERROR else hint)
        result, kind = self.binary_result(e.op, left, right, e.span)
        e.kind = kind
        return result

    def _expr_Call(self, e: A.Call, expected):
        callee = e.callee
        # Built-in calls are resolved statically unless a variable shadows the name.
        if isinstance(callee, A.Ident) and self.lookup(callee.name) is None:
            sig = B.lookup(callee.name)
            if sig is not None:
                return self.check_builtin_call(e, sig)
        fn_ty = self.check_expr(callee)
        for arg in e.args:
            self.check_expr(arg)
        if fn_ty is not T.ERROR:
            self.error(f"cannot call a value of type `{fn_ty}`", callee.span)
        return T.ERROR

    def check_builtin_call(self, e: A.Call, sig) -> T.Type:
        e.builtin = sig.name
        argtys = [self.check_expr(a) for a in e.args]
        if not B.arity_ok(sig, len(argtys)):
            want = sig.arity if isinstance(sig.arity, int) else f"{sig.arity[0]}..{sig.arity[1]}"
            self.error(f"'{sig.name}' expects {want} argument(s), found {len(argtys)}", e.span,
                       note=sig.doc)
            return T.ERROR
        return sig.check(argtys, lambda msg: self.error(msg, e.span, note=sig.doc))


def check(module: A.Module, source: str = "", filename: str = "<input>") -> Checker:
    checker = Checker(source, filename)
    checker.check_module(module)
    return checker
