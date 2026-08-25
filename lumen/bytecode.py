"""Compiled program representation."""
from __future__ import annotations

import bisect

from .opcodes import OPERANDS, WIDTH, Op


class Function:
    __slots__ = ("name", "arity", "nlocals", "code", "consts", "lines", "signature")

    def __init__(self, name: str, arity: int = 0, nlocals: int = 0, signature: str = ""):
        self.name = name
        self.arity = arity
        self.nlocals = nlocals
        self.signature = signature
        self.code = bytearray()
        self.consts: list = []
        self.lines: list[tuple[int, int]] = []   # (code offset, source line), ascending

    def line_for(self, offset: int) -> int:
        """Source line covering a code offset (binary search of the line table)."""
        if not self.lines:
            return 0
        offsets = [o for o, _ in self.lines]
        i = bisect.bisect_right(offsets, offset) - 1
        return self.lines[max(i, 0)][1]

    def __repr__(self) -> str:
        return f"<Function {self.name}/{self.arity} {len(self.code)} bytes>"


class StructDef:
    __slots__ = ("name", "field_names")

    def __init__(self, name: str, field_names: list[str]):
        self.name = name
        self.field_names = field_names


class Program:
    def __init__(self, source_name: str = "<input>"):
        self.source_name = source_name
        self.functions: list[Function] = []
        self.structs: list[StructDef] = []
        self.nglobals = 0
        self.global_inits: list[tuple[int, int]] = []   # (global slot, function index)
        self.global_names: dict[int, str] = {}          # debug info
        self.entry_index = 0

    @property
    def entry(self) -> Function:
        return self.functions[self.entry_index]

    def add_function(self, fn: Function) -> int:
        self.functions.append(fn)
        return len(self.functions) - 1


def decode(code: bytes, offset: int):
    """Decode one instruction: returns (op, operands, next offset)."""
    op = code[offset]
    pos = offset + 1
    operands = []
    for kind in OPERANDS.get(op, ()):
        width = WIDTH[kind]
        operands.append(int.from_bytes(code[pos:pos + width], "little", signed=(kind == "s16")))
        pos += width
    return Op(op), operands, pos
