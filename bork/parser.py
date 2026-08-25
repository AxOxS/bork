"""Recursive-descent parser with Pratt-style expression precedence.

One `binary_expr` loop handles every binary operator: each is looked up in
PRECEDENCE and parsed with a minimum binding power, which is how precedence and
left-associativity fall out without a rule per level.

A module is a sequence of statements. Statements are dispatched on their first
token; everything that is not a keyword is an expression statement or an
assignment, which is decided after parsing the expression.

Errors use panic-mode recovery: on a syntax error we resynchronise at the next
statement boundary so a single run reports many problems instead of just one.
"""
from __future__ import annotations

from . import ast_nodes as A
from .errors import Diagnostic, BorkError, Span
from .lexer import Token, tokenize

# Binary operator precedence (higher binds tighter).
PRECEDENCE = {
    "||": 1,
    "&&": 2,
    "==": 3, "!=": 3,
    "<": 4, "<=": 4, ">": 4, ">=": 4,
    "+": 5, "-": 5,
    "*": 6, "/": 6, "%": 6,
}
ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%="}
STMT_STARTERS = {"let", "var", "if", "while", "for", "return", "break", "continue",
                 "fn", "struct", "}"}


class _ParseError(Exception):
    """Internal signal to unwind to the nearest recovery point."""


class Parser:
    def __init__(self, tokens: list[Token], source: str = "", filename: str = "<input>"):
        self.tokens = tokens
        self.pos = 0
        self.source = source
        self.filename = filename
        self.diags: list[Diagnostic] = []
        # Rust-style ambiguity guard: inside an `if`/`while` header a `{` opens
        # the body, so `Name { ... }` must not parse as a struct literal.
        self.no_struct_literal = 0

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

    def _expect(self, kind: str, what: str | None = None) -> Token:
        if self.current.kind == kind:
            return self._advance()
        label = what or f"'{kind}'"
        self._error(f"expected {label}, found {self._describe(self.current)}", self.current.span)
        raise _ParseError()

    @staticmethod
    def _describe(tok: Token) -> str:
        if tok.kind == "eof":
            return "end of file"
        if tok.kind == "ident":
            return f"identifier '{tok.value}'"
        if tok.kind in ("int", "float", "str"):
            return f"{tok.kind} literal"
        return f"'{tok.kind}'"

    def _error(self, msg: str, span: Span, note: str | None = None) -> None:
        # Suppress a cascade of errors pointing at the same token.
        if self.diags and self.diags[-1].span == span:
            return
        self.diags.append(Diagnostic(msg, span, note=note))

    def _synchronise(self) -> None:
        """Skip tokens until something that can begin a statement."""
        while self.current.kind != "eof":
            if self.tokens[self.pos - 1].kind == ";":
                return
            if self.current.kind in STMT_STARTERS:
                return
            self._advance()

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
            try:
                stmts.append(self.declaration())
            except _ParseError:
                self._synchronise()
                if self._check("}"):     # stray closer; drop it and continue
                    self._advance()
        if self.diags:
            raise BorkError(self.diags, self.source, self.filename)
        return A.Module(start, stmts)

    # -- declarations ------------------------------------------------------
    def declaration(self) -> A.Stmt:
        if self._check("fn"):
            return self.fn_decl()
        if self._check("struct"):
            return self.struct_decl()
        return self.statement()

    def struct_decl(self) -> A.StructDecl:
        kw = self._expect("struct")
        name_tok = self._expect("ident", "struct name")
        self._expect("{")
        fields = []
        while not self._check("}") and not self._check("eof"):
            f_name = self._expect("ident", "field name")
            self._expect(":", "':' followed by a field type")
            f_type = self.type_expr()
            fields.append((f_name.value, f_type, f_name.span))
            if not self._match(","):
                break
        self._expect("}")
        return A.StructDecl(kw.span.to(name_tok.span), name_tok.value, fields)

    def fn_decl(self) -> A.FnDecl:
        kw = self._expect("fn")
        name_tok = self._expect("ident", "function name")
        self._expect("(")
        params: list[A.Param] = []
        if not self._check(")"):
            while True:
                p_name = self._expect("ident", "parameter name")
                self._expect(":", "':' followed by a parameter type")
                p_type = self.type_expr()
                params.append(A.Param(p_name.span, p_name.value, p_type))
                if not self._match(","):
                    break
        self._expect(")")
        ret_type = self.type_expr() if self._match("->") else None
        body = self.block()
        return A.FnDecl(kw.span.to(name_tok.span), name_tok.value, params, ret_type, body)

    # -- types -------------------------------------------------------------
    def type_expr(self) -> A.Node:
        tok = self.current
        if self._match("["):
            elem = self.type_expr()
            self._expect("]")
            return A.TypeArray(tok.span, elem)
        if self._match("fn"):
            self._expect("(")
            params = []
            if not self._check(")"):
                while True:
                    params.append(self.type_expr())
                    if not self._match(","):
                        break
            self._expect(")")
            ret = self.type_expr() if self._match("->") else None
            return A.TypeFn(tok.span, params, ret)
        if self._check("ident"):
            self._advance()
            return A.TypeName(tok.span, tok.value)
        self._error(f"expected a type, found {self._describe(tok)}", tok.span)
        raise _ParseError()

    # -- statements --------------------------------------------------------
    def block(self) -> A.Block:
        open_tok = self._expect("{")
        stmts: list[A.Stmt] = []
        while not self._check("}") and not self._check("eof"):
            try:
                stmts.append(self.declaration())
            except _ParseError:
                self._synchronise()
                if self._check("}"):
                    break
        self._expect("}")
        return A.Block(open_tok.span, stmts)

    def statement(self) -> A.Stmt:
        tok = self.current
        if tok.kind in ("let", "var"):
            return self.let_stmt()
        if tok.kind == "if":
            return self.if_stmt()
        if tok.kind == "while":
            return self.while_stmt()
        if tok.kind == "for":
            return self.for_stmt()
        if tok.kind == "return":
            self._advance()
            value = None
            if not self._check(";"):
                value = self.expression()
            self._expect(";")
            return A.ReturnStmt(tok.span, value)
        if tok.kind == "break":
            self._advance()
            self._expect(";")
            return A.BreakStmt(tok.span)
        if tok.kind == "continue":
            self._advance()
            self._expect(";")
            return A.ContinueStmt(tok.span)
        if tok.kind == "{":
            return self.block()
        return self.expr_or_assign()

    def while_stmt(self) -> A.WhileStmt:
        kw = self._expect("while")
        cond = self.header_expression()
        return A.WhileStmt(kw.span, cond, self.block())

    def header_expression(self) -> A.Expr:
        """Parse an expression in a position where '{' starts a block."""
        self.no_struct_literal += 1
        try:
            return self.expression()
        finally:
            self.no_struct_literal -= 1

    def if_stmt(self) -> A.IfStmt:
        kw = self._expect("if")
        cond = self.header_expression()
        then = self.block()
        otherwise = None
        if self._match("else"):
            # `else if` chains as a nested statement rather than a new form.
            otherwise = self.if_stmt() if self._check("if") else self.block()
        return A.IfStmt(kw.span, cond, then, otherwise)

    def let_stmt(self) -> A.LetStmt:
        kw = self._advance()
        mutable = kw.kind == "var"
        name_tok = self._expect("ident", "variable name")
        type_expr = self.type_expr() if self._match(":") else None
        self._expect("=", "'=' and an initialiser")
        init = self.expression()
        self._expect(";")
        return A.LetStmt(kw.span.to(name_tok.span), name_tok.value, type_expr, init, mutable)

    def for_stmt(self) -> A.Stmt:
        kw = self._expect("for")
        var = self._expect("ident", "loop variable name")
        self._expect("in")
        first = self.header_expression()
        if self._match(".."):
            end = self.header_expression()
            return A.ForRange(kw.span, var.value, first, end, self.block())
        return A.ForIn(kw.span, var.value, first, self.block())

    def expr_or_assign(self) -> A.Stmt:
        expr = self.expression()
        if self.current.kind in ASSIGN_OPS:
            op = self._advance()
            value = self.expression()
            self._expect(";")
            if not isinstance(expr, (A.Ident, A.Index, A.FieldAccess)):
                self._error("invalid assignment target", expr.span,
                            note="only variables, array elements and struct fields "
                                 "can be assigned")
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
            span = left.span.to(right.span)
            if op in ("&&", "||"):
                left = A.Logical(span, op, left, right)
            else:
                left = A.Binary(span, op, left, right)

    def postfix_expr(self) -> A.Expr:
        expr = self.primary_expr()
        while True:
            if self._check("("):
                self._advance()
                args = []
                if not self._check(")"):
                    # Argument lists are delimited, so struct literals are fine here.
                    saved, self.no_struct_literal = self.no_struct_literal, 0
                    try:
                        while True:
                            args.append(self.expression())
                            if not self._match(","):
                                break
                    finally:
                        self.no_struct_literal = saved
                close = self._expect(")")
                expr = A.Call(expr.span.to(close.span), expr, args)
            elif self._check("["):
                self._advance()
                saved, self.no_struct_literal = self.no_struct_literal, 0
                try:
                    index = self.expression()
                finally:
                    self.no_struct_literal = saved
                close = self._expect("]")
                expr = A.Index(expr.span.to(close.span), expr, index)
            elif self._check("."):
                self._advance()
                name = self._expect("ident", "field name")
                expr = A.FieldAccess(expr.span.to(name.span), expr, name.value)
            else:
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
        if tok.kind == "str":
            self._advance()
            return A.StrLit(tok.span, tok.value)
        if tok.kind in ("true", "false"):
            self._advance()
            return A.BoolLit(tok.span, tok.value)
        if tok.kind == "(":
            self._advance()
            saved, self.no_struct_literal = self.no_struct_literal, 0
            try:
                inner = self.expression()
            finally:
                self.no_struct_literal = saved
            self._expect(")")
            return inner
        if tok.kind == "[":
            self._advance()
            saved, self.no_struct_literal = self.no_struct_literal, 0
            elements = []
            try:
                if not self._check("]"):
                    while True:
                        elements.append(self.expression())
                        if not self._match(","):
                            break
            finally:
                self.no_struct_literal = saved
            close = self._expect("]")
            return A.ArrayLit(tok.span.to(close.span), elements)
        if tok.kind == "ident":
            self._advance()
            if self._check("{") and not self.no_struct_literal:
                return self.struct_literal(tok)
            return A.Ident(tok.span, tok.value)
        self._error(f"expected an expression, found {self._describe(tok)}", tok.span)
        raise _ParseError()


    def struct_literal(self, name_tok: Token) -> A.StructLit:
        self._expect("{")
        saved, self.no_struct_literal = self.no_struct_literal, 0
        fields = []
        try:
            while not self._check("}") and not self._check("eof"):
                f_name = self._expect("ident", "field name")
                self._expect(":")
                fields.append((f_name.value, self.expression(), f_name.span))
                if not self._match(","):
                    break
        finally:
            self.no_struct_literal = saved
        close = self._expect("}")
        return A.StructLit(name_tok.span.to(close.span), name_tok.value, fields)


def parse(source: str, filename: str = "<input>") -> A.Module:
    return Parser(tokenize(source, filename), source, filename).parse_module()
