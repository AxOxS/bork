"""Abstract syntax tree for Lumen.

Nodes are plain dataclasses carrying the Span of the source text they came
from. A module is currently a single expression; that changes once there are
statements to put in one.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from .errors import Span


@dataclass
class Node:
    span: Span


@dataclass
class Expr(Node):
    # Annotation slot filled in by the type checker and read by codegen.
    ty: object = field(default=None, kw_only=True)


@dataclass
class IntLit(Expr):
    value: int


@dataclass
class FloatLit(Expr):
    value: float


@dataclass
class BoolLit(Expr):
    value: bool


@dataclass
class Unary(Expr):
    op: str
    operand: Expr
    kind: str = field(default="", kw_only=True)               # 'int' | 'float' | 'bool'





@dataclass
class Binary(Expr):
    op: str
    left: Expr
    right: Expr
    kind: str = field(default="", kw_only=True)               # operand class for codegen


@dataclass
class Module(Node):
    expr: Expr


def dump(node, indent: int = 0) -> str:
    """Render an AST as an indented tree (used by `lumc ast`)."""
    pad = "  " * indent
    if not dataclasses.is_dataclass(node):
        return pad + repr(node)
    scalars, children = [], []
    for f in dataclasses.fields(node):
        if f.name in ("span", "ty"):
            continue
        value = getattr(node, f.name)
        if dataclasses.is_dataclass(value):
            children.append((f.name, value))
        elif value is not None:
            scalars.append(f"{f.name}={value!r}")
    head = pad + type(node).__name__
    ty = getattr(node, "ty", None)
    if ty is not None:
        scalars.append(f": {ty}")
    if scalars:
        head += " (" + ", ".join(scalars) + ")"
    out = [head]
    for name, value in children:
        out.append(f"{pad}  .{name}")
        out.append(dump(value, indent + 2))
    return "\n".join(out)
