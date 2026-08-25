"""Source positions and pretty-printed compiler diagnostics."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    """A half-open region of source text, 1-based line/col."""

    line: int
    col: int
    length: int = 1

    def to(self, other: "Span") -> "Span":
        """Span covering self through other (only exact when on one line)."""
        if other.line != self.line:
            return self
        return Span(self.line, self.col, max(1, other.col + other.length - self.col))


NOWHERE = Span(0, 0, 0)


@dataclass
class Diagnostic:
    message: str
    span: Span
    severity: str = "error"
    note: str | None = None


class BorkError(Exception):
    """A bundle of diagnostics raised by any compiler phase."""

    def __init__(self, diagnostics: list[Diagnostic], source: str = "", filename: str = "<input>"):
        self.diagnostics = diagnostics
        self.source = source
        self.filename = filename
        super().__init__(diagnostics[0].message if diagnostics else "compilation failed")

    def render(self) -> str:
        return render_diagnostics(self.diagnostics, self.source, self.filename)


class BorkRuntimeError(Exception):
    """A trap raised by the virtual machine."""

    def __init__(self, message: str, traceback_lines: list[str] | None = None):
        self.message = message
        self.traceback_lines = traceback_lines or []
        super().__init__(message)

    def render(self) -> str:
        out = ["runtime error: " + self.message]
        for line in self.traceback_lines:
            out.append("    " + line)
        return "\n".join(out)


BOLD = "\033[1m"
RED = "\033[31m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
RESET = "\033[0m"


def _color(enabled: bool):
    if enabled:
        return BOLD, RED, YELLOW, BLUE, RESET
    return "", "", "", "", ""


def render_diagnostics(diags: list[Diagnostic], source: str, filename: str, color: bool = False) -> str:
    bold, red, yellow, blue, reset = _color(color)
    lines = source.splitlines()
    out: list[str] = []
    for d in diags:
        tint = red if d.severity == "error" else yellow
        out.append(f"{bold}{tint}{d.severity}{reset}{bold}: {d.message}{reset}")
        if d.span.line <= 0 or d.span.line > len(lines):
            out.append(f"  --> {filename}")
            if d.note:
                out.append(f"   = note: {d.note}")
            out.append("")
            continue
        src_line = lines[d.span.line - 1]
        gutter = len(str(d.span.line))
        pad = " " * gutter
        # A span may run past the end of its starting line; clamp the caret to it.
        caret_len = max(1, min(d.span.length, max(1, len(src_line) - d.span.col + 1)))
        out.append(f"{pad}{blue}-->{reset} {filename}:{d.span.line}:{d.span.col}")
        out.append(f"{pad} {blue}|{reset}")
        out.append(f"{blue}{d.span.line}{reset} {blue}|{reset} {src_line}")
        out.append(f"{pad} {blue}|{reset} " + " " * (d.span.col - 1) + f"{tint}{'^' * caret_len}{reset}")
        if d.note:
            out.append(f"{pad} {blue}={reset} note: {d.note}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"
