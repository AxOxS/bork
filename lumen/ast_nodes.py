"""Abstract syntax tree for Lumen.

Nodes are plain dataclasses. Fields declared kw_only with a default are
annotation slots that the type checker fills in and the code generator reads.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from .errors import Span


@dataclass
class Node:
    span: Span


# --------------------------------------------------------------------------
# Type expressions (syntax, not semantics -- resolved by the checker)
# --------------------------------------------------------------------------
@dataclass
class TypeName(Node):
    name: str


# --------------------------------------------------------------------------
# Expressions
# --------------------------------------------------------------------------
@dataclass
class Expr(Node):
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
class Ident(Expr):
    name: str
    ref: object = field(default=None, kw_only=True)           # VarInfo


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
class Logical(Expr):
    op: str                                                   # '&&' | '||'
    left: Expr
    right: Expr


@dataclass
class Call(Expr):
    callee: Expr
    args: list
    builtin: str | None = field(default=None, kw_only=True)


# --------------------------------------------------------------------------
# Statements
# --------------------------------------------------------------------------
@dataclass
class Stmt(Node):
    pass


@dataclass
class LetStmt(Stmt):
    name: str
    type_expr: Node | None
    init: Expr
    mutable: bool
    info: object = field(default=None, kw_only=True)          # VarInfo


@dataclass
class AssignStmt(Stmt):
    target: Expr                                              # Ident
    op: str                                                   # '='
    value: Expr
    kind: str = field(default="", kw_only=True)


@dataclass
class ExprStmt(Stmt):
    expr: Expr


@dataclass
class Block(Stmt):
    stmts: list


@dataclass
class IfStmt(Stmt):
    cond: Expr
    then: Block
    otherwise: Node | None                                    # Block | IfStmt | None


@dataclass
class WhileStmt(Stmt):
    cond: Expr
    body: Block


@dataclass
class BreakStmt(Stmt):
    pass


@dataclass
class ContinueStmt(Stmt):
    pass


@dataclass
class Module(Node):
    stmts: list


def dump(node, indent: int = 0) -> str:
    """Render an AST as an indented tree (used by `lumc ast`)."""
    pad = "  " * indent
    if isinstance(node, list):
        if not node:
            return pad + "[]"
        return "\n".join(dump(n, indent) for n in node)
    if not dataclasses.is_dataclass(node):
        return pad + repr(node)
    head = f"{pad}{type(node).__name__}"
    scalars, children = [], []
    for f in dataclasses.fields(node):
        if f.name in ("span", "ty", "info", "ref"):
            continue
        value = getattr(node, f.name)
        if isinstance(value, list) or dataclasses.is_dataclass(value):
            children.append((f.name, value))
        elif value is not None:
            scalars.append(f"{f.name}={value!r}")
    ty = getattr(node, "ty", None)
    if ty is not None:
        scalars.append(f": {ty}")
    if scalars:
        head += " (" + ", ".join(scalars) + ")"
    out = [head]
    for name, value in children:
        if isinstance(value, list) and not value:
            continue
        out.append(f"{pad}  .{name}")
        out.append(dump(value, indent + 2))
    return "\n".join(out)
