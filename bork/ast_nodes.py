"""AST node dataclasses, plus the tree printer behind `borkc ast`."""
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


@dataclass
class TypeArray(Node):
    elem: Node


@dataclass
class TypeFn(Node):
    params: list
    ret: Node | None


# --------------------------------------------------------------------------
# Expressions
# --------------------------------------------------------------------------
# kw_only fields with defaults are filled in by the checker, read by codegen.
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
class StrLit(Expr):
    value: str


@dataclass
class ArrayLit(Expr):
    elements: list


@dataclass
class StructLit(Expr):
    name: str
    fields: list           # list[(name, Expr, Span)]
    def_: object = field(default=None, kw_only=True)
    order: list = field(default_factory=list, kw_only=True)   # source index per declared field


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
class Index(Expr):
    obj: Expr
    index: Expr


@dataclass
class FieldAccess(Expr):
    obj: Expr
    name: str
    index: int = field(default=-1, kw_only=True)


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
    target: Expr                                              # Ident | Index | FieldAccess
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
class ForRange(Stmt):
    var: str
    start: Expr
    end: Expr
    body: Block
    info: object = field(default=None, kw_only=True)          # loop variable VarInfo
    limit_slot: int = field(default=-1, kw_only=True)         # hidden local holding `end`


@dataclass
class ForIn(Stmt):
    var: str
    iterable: Expr
    body: Block
    info: object = field(default=None, kw_only=True)
    arr_slot: int = field(default=-1, kw_only=True)
    idx_slot: int = field(default=-1, kw_only=True)


@dataclass
class BreakStmt(Stmt):
    pass


@dataclass
class ContinueStmt(Stmt):
    pass


@dataclass
class ReturnStmt(Stmt):
    value: Expr | None


@dataclass
class Param(Node):
    name: str
    type_expr: Node
    info: object = field(default=None, kw_only=True)


@dataclass
class FnDecl(Stmt):
    name: str
    params: list
    ret_type: Node | None
    body: Block
    ty: object = field(default=None, kw_only=True)            # FnType
    global_slot: int = field(default=-1, kw_only=True)
    nlocals: int = field(default=0, kw_only=True)


@dataclass
class StructDecl(Stmt):
    name: str
    fields: list                                              # list[(name, type_expr, Span)]
    ty: object = field(default=None, kw_only=True)


@dataclass
class Module(Node):
    stmts: list


def dump(node, indent: int = 0) -> str:
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
        if f.name in ("span", "ty", "info", "ref", "def_", "order",
                      "global_slot", "nlocals", "index",
                      "limit_slot", "arr_slot", "idx_slot"):
            continue
        value = getattr(node, f.name)
        if isinstance(value, list) or dataclasses.is_dataclass(value):
            children.append((f.name, value))
        elif value is not None:
            scalars.append(f"{f.name}={value!r}")
    ty = getattr(node, "ty", None)
    if ty is not None and not isinstance(node, (FnDecl, StructDecl)):
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
