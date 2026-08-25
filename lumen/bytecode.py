"""Compiled program representation and the `.lmc` object file format."""
from __future__ import annotations

import bisect
import struct

from .opcodes import OPERANDS, WIDTH, Op

MAGIC = b"LUMC"
VERSION = 1


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


# -- binary serialisation --------------------------------------------------
class _Writer:
    def __init__(self):
        self.buf = bytearray()

    def u8(self, v):   self.buf += struct.pack("<B", v)
    def u16(self, v):  self.buf += struct.pack("<H", v)
    def u32(self, v):  self.buf += struct.pack("<I", v)
    def i64(self, v):  self.buf += struct.pack("<q", v)
    def f64(self, v):  self.buf += struct.pack("<d", v)

    def string(self, s: str):
        data = s.encode("utf-8")
        self.u32(len(data))
        self.buf += data

    def blob(self, data: bytes):
        self.u32(len(data))
        self.buf += data


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def _take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise ValueError("truncated Lumen object file")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def u8(self):  return struct.unpack("<B", self._take(1))[0]
    def u16(self): return struct.unpack("<H", self._take(2))[0]
    def u32(self): return struct.unpack("<I", self._take(4))[0]
    def i64(self): return struct.unpack("<q", self._take(8))[0]
    def f64(self): return struct.unpack("<d", self._take(8))[0]

    def string(self) -> str:
        return self._take(self.u32()).decode("utf-8")

    def blob(self) -> bytes:
        return self._take(self.u32())


TAG_INT, TAG_FLOAT, TAG_STR, TAG_BOOL = 0, 1, 2, 3


def serialize(program: Program) -> bytes:
    w = _Writer()
    w.buf += MAGIC
    w.u8(VERSION)
    w.string(program.source_name)
    w.u32(program.nglobals)
    w.u32(program.entry_index)

    w.u32(len(program.structs))
    for st in program.structs:
        w.string(st.name)
        w.u16(len(st.field_names))
        for name in st.field_names:
            w.string(name)

    w.u32(len(program.global_inits))
    for slot, fn_index in program.global_inits:
        w.u32(slot)
        w.u32(fn_index)

    w.u32(len(program.global_names))
    for slot, name in sorted(program.global_names.items()):
        w.u32(slot)
        w.string(name)

    w.u32(len(program.functions))
    for fn in program.functions:
        w.string(fn.name)
        w.string(fn.signature)
        w.u8(fn.arity)
        w.u16(fn.nlocals)
        w.blob(bytes(fn.code))
        w.u32(len(fn.consts))
        for c in fn.consts:
            if isinstance(c, bool):
                w.u8(TAG_BOOL); w.u8(1 if c else 0)
            elif isinstance(c, int):
                w.u8(TAG_INT); w.i64(c)
            elif isinstance(c, float):
                w.u8(TAG_FLOAT); w.f64(c)
            elif isinstance(c, str):
                w.u8(TAG_STR); w.string(c)
            else:
                raise TypeError(f"cannot serialise constant {c!r}")
        w.u32(len(fn.lines))
        for offset, line in fn.lines:
            w.u32(offset)
            w.u32(line)
    return bytes(w.buf)


def deserialize(data: bytes) -> Program:
    r = _Reader(data)
    if r._take(4) != MAGIC:
        raise ValueError("not a Lumen object file (bad magic)")
    version = r.u8()
    if version != VERSION:
        raise ValueError(f"unsupported object file version {version} (this build reads {VERSION})")
    program = Program(r.string())
    program.nglobals = r.u32()
    program.entry_index = r.u32()

    for _ in range(r.u32()):
        name = r.string()
        fields = [r.string() for _ in range(r.u16())]
        program.structs.append(StructDef(name, fields))

    for _ in range(r.u32()):
        program.global_inits.append((r.u32(), r.u32()))

    for _ in range(r.u32()):
        slot = r.u32()
        program.global_names[slot] = r.string()

    for _ in range(r.u32()):
        fn = Function(r.string(), signature=r.string())
        fn.arity = r.u8()
        fn.nlocals = r.u16()
        fn.code = bytearray(r.blob())
        for _ in range(r.u32()):
            tag = r.u8()
            if tag == TAG_BOOL:
                fn.consts.append(r.u8() == 1)
            elif tag == TAG_INT:
                fn.consts.append(r.i64())
            elif tag == TAG_FLOAT:
                fn.consts.append(r.f64())
            elif tag == TAG_STR:
                fn.consts.append(r.string())
            else:
                raise ValueError(f"unknown constant tag {tag}")
        fn.lines = [(r.u32(), r.u32()) for _ in range(r.u32())]
        program.functions.append(fn)
    return program


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
