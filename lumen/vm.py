"""The Lumen virtual machine: a stack interpreter for compiled bytecode.

One `while` loop decodes and executes instructions. Operands are read straight
out of the code array rather than through `decode`, because this loop runs once
per executed instruction and the disassembler runs once per program.

Locals live in the stack itself, below the temporaries: LOAD_LOCAL i is simply
stack[base + i]. Globals live in a flat array, indexed by the slot the checker
handed out.
"""
from __future__ import annotations

import math
import sys

from .builtins import BUILTINS
from .bytecode import Program
from .errors import LumenRuntimeError
from .opcodes import Op
from .values import UNINIT, UNIT, idiv, imod, wrap64


def fdiv(a: float, b: float) -> float:
    """IEEE-754 division: dividing by zero yields inf/nan, it does not trap."""
    if b == 0.0:
        if a != a or a == 0.0:
            return float("nan")
        return math.copysign(float("inf"), a) * math.copysign(1.0, b)
    return a / b


def fmod(a: float, b: float) -> float:
    if b == 0.0 or a != a or b != b:
        return float("nan")
    try:
        return math.fmod(a, b)
    except ValueError:
        return float("nan")


class VM:
    def __init__(self, program: Program, out=None):
        self.program = program
        self.out = out if out is not None else sys.stdout
        self.globals = [UNINIT] * program.nglobals
        self.stack: list = []
        self.instructions = 0

    def run(self):
        program = self.program
        fn = program.entry
        code = fn.code
        consts = fn.consts
        stack = self.stack
        globals_ = self.globals
        base = 0
        stack.extend([UNIT] * fn.nlocals)
        ip = 0
        while True:
            self.instructions += 1
            op = code[ip]
            ip += 1

            if op == Op.CONST:
                stack.append(consts[code[ip] | (code[ip + 1] << 8)])
                ip += 2
            elif op == Op.LOAD_LOCAL:
                stack.append(stack[base + code[ip]])
                ip += 1
            elif op == Op.STORE_LOCAL:
                stack[base + code[ip]] = stack.pop()
                ip += 1
            elif op == Op.LOAD_GLOBAL:
                slot = code[ip] | (code[ip + 1] << 8)
                ip += 2
                value = globals_[slot]
                if value is UNINIT:
                    name = program.global_names.get(slot, f"global#{slot}")
                    raise LumenRuntimeError(f"'{name}' is used before it is initialised")
                stack.append(value)
            elif op == Op.STORE_GLOBAL:
                globals_[code[ip] | (code[ip + 1] << 8)] = stack.pop()
                ip += 2
            elif op == Op.POP:
                stack.pop()
            elif op == Op.UNIT:
                stack.append(UNIT)

            # -- integer arithmetic ---------------------------------------
            elif op == Op.ADD_INT:
                b = stack.pop(); stack[-1] = wrap64(stack[-1] + b)
            elif op == Op.SUB_INT:
                b = stack.pop(); stack[-1] = wrap64(stack[-1] - b)
            elif op == Op.MUL_INT:
                b = stack.pop(); stack[-1] = wrap64(stack[-1] * b)
            elif op == Op.DIV_INT:
                b = stack.pop()
                if b == 0:
                    raise LumenRuntimeError("integer division by zero")
                stack[-1] = wrap64(idiv(stack[-1], b))
            elif op == Op.MOD_INT:
                b = stack.pop()
                if b == 0:
                    raise LumenRuntimeError("integer remainder by zero")
                stack[-1] = wrap64(imod(stack[-1], b))
            elif op == Op.NEG_INT:
                stack[-1] = wrap64(-stack[-1])

            # -- float arithmetic -----------------------------------------
            elif op == Op.ADD_FLOAT:
                b = stack.pop(); stack[-1] = stack[-1] + b
            elif op == Op.SUB_FLOAT:
                b = stack.pop(); stack[-1] = stack[-1] - b
            elif op == Op.MUL_FLOAT:
                b = stack.pop(); stack[-1] = stack[-1] * b
            elif op == Op.DIV_FLOAT:
                b = stack.pop(); stack[-1] = fdiv(stack[-1], b)
            elif op == Op.MOD_FLOAT:
                b = stack.pop(); stack[-1] = fmod(stack[-1], b)
            elif op == Op.NEG_FLOAT:
                stack[-1] = -stack[-1]

            elif op == Op.TRUE:
                stack.append(True)
            elif op == Op.FALSE:
                stack.append(False)
            elif op == Op.LT:
                b = stack.pop(); stack[-1] = stack[-1] < b
            elif op == Op.LE:
                b = stack.pop(); stack[-1] = stack[-1] <= b
            elif op == Op.GT:
                b = stack.pop(); stack[-1] = stack[-1] > b
            elif op == Op.GE:
                b = stack.pop(); stack[-1] = stack[-1] >= b
            elif op == Op.EQ:
                b = stack.pop(); stack[-1] = stack[-1] == b
            elif op == Op.NE:
                b = stack.pop(); stack[-1] = stack[-1] != b
            elif op == Op.NOT:
                stack[-1] = not stack[-1]

            elif op == Op.CALL_NATIVE:
                index = code[ip]
                argc = code[ip + 1]
                ip += 2
                args = stack[len(stack) - argc:] if argc else []
                if argc:
                    del stack[len(stack) - argc:]
                stack.append(BUILTINS[index].native(self, args))

            elif op == Op.HALT:
                return UNIT
            elif op == Op.NOP:
                pass
            else:
                raise LumenRuntimeError(f"illegal instruction {op} at offset {ip - 1}")


def run(program: Program, out=None) -> VM:
    vm = VM(program, out=out)
    vm.run()
    return vm
