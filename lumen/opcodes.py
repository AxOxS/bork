"""The Lumen VM instruction set.

A stack machine. Instructions are one opcode byte followed by zero or more
operands; operand widths are fixed per opcode, so the stream can be decoded
linearly by both the VM and the disassembler.

Arithmetic is specialised by static type (ADD_INT vs ADD_FLOAT): the checker has
already proved the operand types, so the VM never has to dispatch on them.

Opcode numbers are grouped by purpose with gaps between the groups, so related
instructions can be added later without renumbering the whole set.
"""
from __future__ import annotations

from enum import IntEnum


class Op(IntEnum):
    HALT = 0
    NOP = 1

    CONST = 10          # u16 const index -> push consts[i]
    TRUE = 11
    FALSE = 12
    UNIT = 13
    POP = 14

    LOAD_LOCAL = 20     # u8 slot
    STORE_LOCAL = 21    # u8 slot (pops)
    LOAD_GLOBAL = 22    # u16 slot
    STORE_GLOBAL = 23   # u16 slot (pops)

    ADD_INT = 30
    SUB_INT = 31
    MUL_INT = 32
    DIV_INT = 33
    MOD_INT = 34
    NEG_INT = 35
    ADD_FLOAT = 36
    SUB_FLOAT = 37
    MUL_FLOAT = 38
    DIV_FLOAT = 39
    MOD_FLOAT = 40
    NEG_FLOAT = 41

    EQ = 50
    NE = 51
    LT = 52
    LE = 53
    GT = 54
    GE = 55
    NOT = 56

    CALL_NATIVE = 71    # u8 builtin index, u8 argc


U8, U16, S16 = "u8", "u16", "s16"

OPERANDS: dict[int, tuple[str, ...]] = {
    Op.CONST: (U16,),
    Op.LOAD_LOCAL: (U8,),
    Op.STORE_LOCAL: (U8,),
    Op.LOAD_GLOBAL: (U16,),
    Op.STORE_GLOBAL: (U16,),
    Op.CALL_NATIVE: (U8, U8),
}

WIDTH = {U8: 1, U16: 2, S16: 2}

# (operand kind, operator) -> opcode, used by the code generator.
ARITH_OPS = {
    ("int", "+"): Op.ADD_INT, ("int", "-"): Op.SUB_INT, ("int", "*"): Op.MUL_INT,
    ("int", "/"): Op.DIV_INT, ("int", "%"): Op.MOD_INT,
    ("float", "+"): Op.ADD_FLOAT, ("float", "-"): Op.SUB_FLOAT, ("float", "*"): Op.MUL_FLOAT,
    ("float", "/"): Op.DIV_FLOAT, ("float", "%"): Op.MOD_FLOAT,
}

NEG_OPS = {"int": Op.NEG_INT, "float": Op.NEG_FLOAT}

COMPARE_OPS = {"==": Op.EQ, "!=": Op.NE, "<": Op.LT, "<=": Op.LE, ">": Op.GT, ">=": Op.GE}


def instruction_size(op: int) -> int:
    return 1 + sum(WIDTH[kind] for kind in OPERANDS.get(op, ()))
