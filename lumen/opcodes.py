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
    CONCAT = 42

    EQ = 50
    NE = 51
    LT = 52
    LE = 53
    GT = 54
    GE = 55
    NOT = 56

    JUMP = 60                   # s16 relative to the next instruction
    JUMP_IF_FALSE = 61          # s16, pops the condition
    JUMP_IF_TRUE_OR_POP = 62    # s16, short-circuit for ||
    JUMP_IF_FALSE_OR_POP = 63   # s16, short-circuit for &&

    CALL = 70           # u8 argc
    CALL_NATIVE = 71    # u8 builtin index, u8 argc
    RET = 72            # pops the return value, tears down the frame

    MAKE_ARRAY = 80     # u16 element count
    INDEX_GET = 82      # arr idx -> value
    MAKE_STRUCT = 81    # u16 struct index
    INDEX_SET = 83      # arr idx value ->
    FIELD_GET = 84      # u8 field index
    FIELD_SET = 85      # u8 field index; obj value ->
    LEN = 86


U8, U16, S16 = "u8", "u16", "s16"

OPERANDS: dict[int, tuple[str, ...]] = {
    Op.CONST: (U16,),
    Op.LOAD_LOCAL: (U8,),
    Op.STORE_LOCAL: (U8,),
    Op.LOAD_GLOBAL: (U16,),
    Op.STORE_GLOBAL: (U16,),
    Op.JUMP: (S16,),
    Op.JUMP_IF_FALSE: (S16,),
    Op.JUMP_IF_TRUE_OR_POP: (S16,),
    Op.JUMP_IF_FALSE_OR_POP: (S16,),
    Op.CALL: (U8,),
    Op.CALL_NATIVE: (U8, U8),
    Op.MAKE_ARRAY: (U16,),
    Op.MAKE_STRUCT: (U16,),
    Op.FIELD_GET: (U8,),
    Op.FIELD_SET: (U8,),
}

WIDTH = {U8: 1, U16: 2, S16: 2}

JUMPS = {Op.JUMP, Op.JUMP_IF_FALSE, Op.JUMP_IF_TRUE_OR_POP, Op.JUMP_IF_FALSE_OR_POP}

# (operand kind, operator) -> opcode, used by the code generator.
ARITH_OPS = {
    ("int", "+"): Op.ADD_INT, ("int", "-"): Op.SUB_INT, ("int", "*"): Op.MUL_INT,
    ("int", "/"): Op.DIV_INT, ("int", "%"): Op.MOD_INT,
    ("float", "+"): Op.ADD_FLOAT, ("float", "-"): Op.SUB_FLOAT, ("float", "*"): Op.MUL_FLOAT,
    ("float", "/"): Op.DIV_FLOAT, ("float", "%"): Op.MOD_FLOAT,
    ("str", "+"): Op.CONCAT,
}

NEG_OPS = {"int": Op.NEG_INT, "float": Op.NEG_FLOAT}

COMPARE_OPS = {"==": Op.EQ, "!=": Op.NE, "<": Op.LT, "<=": Op.LE, ">": Op.GT, ">=": Op.GE}


def instruction_size(op: int) -> int:
    return 1 + sum(WIDTH[kind] for kind in OPERANDS.get(op, ()))
