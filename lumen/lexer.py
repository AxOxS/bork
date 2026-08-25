"""Lexer: source text -> a flat stream of tokens.

Every token carries a Span so later phases can point at the exact text that
caused a problem. Positions are much easier to thread through from the start
than to retrofit once the parser and type checker already exist.

Scope is deliberately only what the arithmetic slice needs. Identifiers,
strings, floats and keywords arrive with the features that use them.
"""
from __future__ import annotations

from dataclasses import dataclass

from .errors import Diagnostic, LumenError, Span
from .values import MAX_I64

# Matched in order, so longest first: once '==' and '->' exist, they must win
# over '=' and '-'.
OPERATORS = ["+", "-", "*", "/", "%", "(", ")"]


@dataclass
class Token:
    kind: str        # 'int', the operator's own text, or 'eof'
    value: object
    span: Span

    def __repr__(self) -> str:
        return f"Token({self.kind!r}, {self.value!r}, {self.span.line}:{self.span.col})"


class Lexer:
    def __init__(self, source: str, filename: str = "<input>"):
        self.src = source
        self.filename = filename
        self.pos = 0
        self.line = 1
        self.col = 1
        self.diags: list[Diagnostic] = []

    # -- character helpers -------------------------------------------------
    def _peek(self, offset: int = 0) -> str:
        i = self.pos + offset
        return self.src[i] if i < len(self.src) else ""

    def _advance(self) -> str:
        ch = self.src[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _span_from(self, line: int, col: int, start: int) -> Span:
        return Span(line, col, max(1, self.pos - start))

    def _error(self, msg: str, span: Span, note: str | None = None) -> None:
        self.diags.append(Diagnostic(msg, span, note=note))

    # -- main loop ---------------------------------------------------------
    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while True:
            self._skip_trivia()
            if self.pos >= len(self.src):
                tokens.append(Token("eof", None, Span(self.line, self.col, 0)))
                break
            tokens.append(self._next_token())
        if self.diags:
            raise LumenError(self.diags, self.src, self.filename)
        return tokens

    def _skip_trivia(self) -> None:
        while self.pos < len(self.src):
            ch = self._peek()
            if ch in " \t\r\n":
                self._advance()
            elif ch == "/" and self._peek(1) == "/":
                while self.pos < len(self.src) and self._peek() != "\n":
                    self._advance()
            else:
                return

    def _next_token(self) -> Token:
        line, col, start = self.line, self.col, self.pos
        ch = self._peek()

        if ch.isdigit():
            return self._number(line, col, start)

        for op in OPERATORS:
            if self.src.startswith(op, self.pos):
                for _ in op:
                    self._advance()
                return Token(op, op, Span(line, col, len(op)))

        self._advance()
        span = Span(line, col, 1)
        self._error(f"unexpected character {ch!r}", span)
        return Token("error", ch, span)

    def _number(self, line: int, col: int, start: int) -> Token:
        while self._peek().isdigit():
            self._advance()
        text = self.src[start:self.pos]
        span = Span(line, col, len(text))
        value = int(text)
        if value > MAX_I64:
            self._error("integer literal does not fit in a 64-bit int", span)
            value = 0
        return Token("int", value, span)


def tokenize(source: str, filename: str = "<input>") -> list[Token]:
    return Lexer(source, filename).tokenize()
