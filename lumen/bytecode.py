"""Compiled program representation."""
from __future__ import annotations

from .opcodes import OPERANDS, WIDTH, Op


class Function:
    __slots__ = ("name", "nlocals", "code", "consts")

    def __init__(self, name: str, nlocals: int = 0):
        self.name = name
        self.nlocals = nlocals
        self.code = bytearray()
        self.consts: list = []

    def __repr__(self) -> str:
        return f"<Function {self.name} {len(self.code)} bytes>"


class Program:
    def __init__(self, source_name: str = "<input>"):
        self.source_name = source_name
        self.functions: list[Function] = []
        self.nglobals = 0
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
