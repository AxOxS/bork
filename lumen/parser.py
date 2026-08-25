"""Recursive-descent parser with Pratt-style expression precedence.

One `binary_expr` loop handles every binary operator: each is looked up in
PRECEDENCE and parsed with a minimum binding power, which is how precedence and
left-associativity fall out without a rule per level.

A module is a sequence of statements. Statements are dispatched on their first
token; everything that is not a keyword is an expression statement or an
assignment, which is decided after parsing the expression.
"""
from __future__ import annotations

from . import ast_nodes as A
from .errors import Diagnostic, LumenError, Span
from .lexer import Token, tokenize

# Binary operator precedence (higher binds tighter).
PRECEDENCE = {
    "==": 3, "!=": 3,
    "<": 4, "<=": 4, ">": 4, ">=": 4,
    "+": 5, "-": 5,
    "*": 6, "/": 6, "%": 6,
}
ASSIGN_OPS = {"="}


class Parser:
    def __init__(self, tokens: list[Token], source: str = "", filename: str = "<input>"):
        self.tokens = tokens
        self.pos = 0
        self.source = source
        self.filename = filename

    # -- token helpers -----------------------------------------------------
    @property
    def current(self) -> Token:
        return self.tokens[self.pos]

    def _check(self, kind: str) -> bool:
        return self.current.kind == kind

    def _advance(self) -> Token:
        tok = self.current
        if tok.kind != "eof":
            self.pos += 1
        return tok

    def _expect(self, kind: str) -> Token:
        if self.current.kind == kind:
            return self._advance()
        raise self._error(f"expected '{kind}', found {self._describe(self.current)}",
                          self.current.span,
                          note="the previous token ends at "
                               f"line {self.tokens[self.pos - 1].span.line}")

    @staticmethod
    def _describe(tok: Token) -> str:
        if tok.kind == "eof":
            return "end of file"
        if tok.kind == "ident":
            return f"identifier '{tok.value}'"
        if tok.kind in ("int", "float"):
            return f"{tok.kind} literal"
        return f"'{tok.kind}'"

    def _error(self, msg: str, span: Span, note: str | None = None) -> LumenError:
        return LumenError([Diagnostic(msg, span, note=note)], self.source, self.filename)

    def _error_at(self, msg: str, span: Span, note: str | None = None) -> None:
        raise self._error(msg, span, note)

    def _match(self, *kinds: str) -> Token | None:
        if self.current.kind in kinds:
            tok = self.current
            self.pos += 1
            return tok
        return None

    # -- entry point -------------------------------------------------------
    def parse_module(self) -> A.Module:
        start = self.current.span
        stmts: list[A.Stmt] = []
        while not self._check("eof"):
            stmts.append(self.statement())
        return A.Module(start, stmts)

    # -- types -------------------------------------------------------------
    def type_expr(self) -> A.Node:
        tok = self.current
        if self._check("ident"):
            self._advance()
            return A.TypeName(tok.span, tok.value)
        raise self._error(f"expected a type, found {self._describe(tok)}", tok.span)

    # -- statements --------------------------------------------------------
    def block(self) -> A.Block:
        open_tok = self._expect("{")
        stmts: list[A.Stmt] = []
        while not self._check("}") and not self._check("eof"):
            stmts.append(self.statement())
        self._expect("}")
        return A.Block(open_tok.span, stmts)

    def statement(self) -> A.Stmt:
        tok = self.current
        if tok.kind in ("let", "var"):
            return self.let_stmt()
        if tok.kind == "if":
            return self.if_stmt()
        if tok.kind == "{":
            return self.block()
        return self.expr_or_assign()

    def if_stmt(self) -> A.IfStmt:
        kw = self._expect("if")
        cond = self.expression()
        then = self.block()
        otherwise = None
        if self._match("else"):
            # `else if` chains as a nested statement rather than a new form.
            otherwise = self.if_stmt() if self._check("if") else self.block()
        return A.IfStmt(kw.span, cond, then, otherwise)

    def let_stmt(self) -> A.LetStmt:
        kw = self._advance()
        mutable = kw.kind == "var"
        name_tok = self._expect("ident")
        type_expr = self.type_expr() if self._match(":") else None
        self._expect("=")
        init = self.expression()
        self._expect(";")
        return A.LetStmt(kw.span.to(name_tok.span), name_tok.value, type_expr, init, mutable)

    def expr_or_assign(self) -> A.Stmt:
        expr = self.expression()
        if self.current.kind in ASSIGN_OPS:
            op = self._advance()
            value = self.expression()
            self._expect(";")
            if not isinstance(expr, A.Ident):
                self._error_at("invalid assignment target", expr.span,
                               note="only variables can be assigned")
            return A.AssignStmt(expr.span, expr, op.kind, value)
        self._expect(";")
        return A.ExprStmt(expr.span, expr)

    # -- expressions (Pratt) ----------------------------------------------
    def expression(self) -> A.Expr:
        return self.binary_expr(0)

    def binary_expr(self, min_prec: int) -> A.Expr:
        left = self.unary_expr()
        while True:
            op = self.current.kind
            prec = PRECEDENCE.get(op, -1)
            if prec < 0 or prec < min_prec:
                return left
            self._advance()
            # All binary operators are left-associative, so the right-hand side
            # is parsed one level tighter.
            right = self.binary_expr(prec + 1)
            left = A.Binary(left.span.to(right.span), op, left, right)

    def postfix_expr(self) -> A.Expr:
        expr = self.primary_expr()
        while self._check("("):
            self._advance()
            args = []
            if not self._check(")"):
                while True:
                    args.append(self.expression())
                    if not self._match(","):
                        break
            close = self._expect(")")
            expr = A.Call(expr.span.to(close.span), expr, args)
        return expr

    def unary_expr(self) -> A.Expr:
        tok = self.current
        if tok.kind in ("-", "!"):
            self._advance()
            operand = self.unary_expr()
            # Fold '-' into a numeric literal rather than emitting a negation.
            if tok.kind == "-" and isinstance(operand, A.IntLit):
                return A.IntLit(tok.span.to(operand.span), -operand.value)
            if tok.kind == "-" and isinstance(operand, A.FloatLit):
                return A.FloatLit(tok.span.to(operand.span), -operand.value)
            return A.Unary(tok.span.to(operand.span), tok.kind, operand)
        return self.postfix_expr()

    def primary_expr(self) -> A.Expr:
        tok = self.current
        if tok.kind == "int":
            self._advance()
            return A.IntLit(tok.span, tok.value)
        if tok.kind == "float":
            self._advance()
            return A.FloatLit(tok.span, tok.value)
        if tok.kind in ("true", "false"):
            self._advance()
            return A.BoolLit(tok.span, tok.value)
        if tok.kind == "(":
            self._advance()
            inner = self.expression()
            self._expect(")")
            return inner
        if tok.kind == "ident":
            self._advance()
            return A.Ident(tok.span, tok.value)
        raise self._error(f"expected an expression, found {self._describe(tok)}", tok.span)


def parse(source: str, filename: str = "<input>") -> A.Module:
    return Parser(tokenize(source, filename), source, filename).parse_module()
