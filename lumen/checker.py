"""Semantic analysis: type checking.

The checker annotates the AST in place -- every expression gets a `.ty`, and
every operator gets a `.kind` naming the operand class it works on. The code
generator then never has to ask a question about types, and neither does the VM.

Errors are collected rather than raised at the first one, so a single run can
report everything it found.
"""
from __future__ import annotations

from . import ast_nodes as A
from . import types as T
from .errors import Diagnostic, LumenError, Span

ARITH = {"+", "-", "*", "/", "%"}
ORDERING = {"<", "<=", ">", ">="}
EQUALITY = {"==", "!="}


class Checker:
    def __init__(self, source: str = "", filename: str = "<input>"):
        self.source = source
        self.filename = filename
        self.errors: list[Diagnostic] = []

    # -- diagnostics -------------------------------------------------------
    def error(self, msg: str, span: Span, note: str | None = None) -> None:
        self.errors.append(Diagnostic(msg, span, note=note))

    # -- driver ------------------------------------------------------------
    def check_module(self, module: A.Module) -> A.Module:
        self.check_expr(module.expr)
        if self.errors:
            raise LumenError(self.errors, self.source, self.filename)
        return module

    # -- expressions -------------------------------------------------------
    def check_expr(self, expr: A.Expr) -> T.Type:
        method = getattr(self, "_expr_" + type(expr).__name__, None)
        if method is None:
            raise AssertionError(f"unhandled expression {type(expr).__name__}")
        ty = method(expr)
        expr.ty = ty
        return ty

    def _expr_IntLit(self, e):
        return T.INT

    def _expr_FloatLit(self, e):
        return T.FLOAT

    def _expr_BoolLit(self, e):
        return T.BOOL

    def _expr_Unary(self, e: A.Unary):
        ty = self.check_expr(e.operand)
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

    def _expr_Binary(self, e: A.Binary):
        left = self.check_expr(e.left)
        right = self.check_expr(e.right)
        result, kind = self.binary_result(e.op, left, right, e.span)
        e.kind = kind
        return result


def check(module: A.Module, source: str = "", filename: str = "<input>") -> Checker:
    checker = Checker(source, filename)
    checker.check_module(module)
    return checker
