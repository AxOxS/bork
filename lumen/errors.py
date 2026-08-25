"""Source positions and compiler errors.

An error is a single message pinned to a Span. That is enough while the
language is only arithmetic; once there is enough of it to produce
interesting errors, this grows into a list of diagnostics rendered with
source snippets and carets.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    """A region of source text, 1-based line and column."""

    line: int
    col: int
    length: int = 1

    def to(self, other: "Span") -> "Span":
        """Span covering self through other (exact only on a single line)."""
        if other.line != self.line:
            return self
        return Span(self.line, self.col, max(1, other.col + other.length - self.col))


class LumenError(Exception):
    def __init__(self, message: str, span: Span, filename: str = "<input>"):
        self.message = message
        self.span = span
        self.filename = filename
        super().__init__(message)

    def render(self) -> str:
        return f"{self.filename}:{self.span.line}:{self.span.col}: error: {self.message}"


class LumenRuntimeError(Exception):
    """A trap raised by the virtual machine."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)

    def render(self) -> str:
        return "runtime error: " + self.message
