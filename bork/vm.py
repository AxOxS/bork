"""The virtual machine: an iterative stack interpreter for compiled bytecode."""
from __future__ import annotations

import math
import sys

from .builtins import BUILTINS
from .bytecode import Program
from .errors import BorkRuntimeError
from .opcodes import Op
from .values import UNINIT, UNIT, FunctionValue, StructValue, idiv, imod, to_display, wrap64

MAX_FRAMES = 20000


class Frame:
    __slots__ = ("fn", "ip", "base")

    def __init__(self, fn, ip: int, base: int):
        self.fn = fn
        self.ip = ip
        self.base = base


# IEEE: dividing by zero gives inf or nan instead of trapping.
def fdiv(a: float, b: float) -> float:
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
    def __init__(self, program: Program, out=None, trace: bool = False):
        self.program = program
        self.out = out if out is not None else sys.stdout
        self.trace = trace
        self.globals = [UNINIT] * program.nglobals
        self.structs = program.structs
        self.stack: list = []
        self.frames: list[Frame] = []
        self.instructions = 0

    # -- errors ------------------------------------------------------------
    def traceback(self, fn, ip: int, head: int = 8, tail: int = 4) -> list[str]:
        source = self.program.source_name
        lines = [f"at {fn.name} ({source}:{fn.line_for(max(ip - 1, 0))})"]
        for frame in reversed(self.frames):
            lines.append(f"at {frame.fn.name} ({source}:{frame.fn.line_for(max(frame.ip - 1, 0))})")
        # Deep recursion would otherwise print thousands of identical lines.
        if len(lines) > head + tail + 1:
            omitted = len(lines) - head - tail
            lines = lines[:head] + [f"... {omitted:,} frames omitted ..."] + lines[-tail:]
        return lines

    def fail(self, message: str, fn, ip: int):
        return BorkRuntimeError(message, self.traceback(fn, ip))

    # Operands are decoded inline rather than through bytecode.decode: this loop
    # runs once per instruction executed.
    def run(self):
        program = self.program
        for slot, fn_index in program.global_inits:
            self.globals[slot] = FunctionValue(program.functions[fn_index])

        fn = program.entry
        code = fn.code
        consts = fn.consts
        stack = self.stack
        globals_ = self.globals
        frames = self.frames
        stack.append(UNIT)                       # placeholder for the entry "callee"
        base = 1
        stack.extend([UNIT] * fn.nlocals)
        ip = 0
        while True:
            if self.trace:
                self._trace(fn, ip, stack, base)
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
                    raise self.fail(f"'{name}' is used before it is initialised", fn, ip)
                stack.append(value)
            elif op == Op.STORE_GLOBAL:
                globals_[code[ip] | (code[ip + 1] << 8)] = stack.pop()
                ip += 2
            elif op == Op.POP:
                stack.pop()
            elif op == Op.UNIT:
                stack.append(UNIT)
            elif op == Op.DUP:
                stack.append(stack[-1])
            elif op == Op.DUP2:
                stack.extend(stack[-2:])

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
                    raise self.fail("integer division by zero", fn, ip)
                stack[-1] = wrap64(idiv(stack[-1], b))
            elif op == Op.MOD_INT:
                b = stack.pop()
                if b == 0:
                    raise self.fail("integer remainder by zero", fn, ip)
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
            elif op == Op.CONCAT:
                b = stack.pop(); stack[-1] = stack[-1] + b

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

            elif op == Op.JUMP:
                delta = int.from_bytes(code[ip:ip + 2], "little", signed=True)
                ip += 2 + delta
            elif op == Op.JUMP_IF_FALSE:
                delta = int.from_bytes(code[ip:ip + 2], "little", signed=True)
                ip += 2
                if stack.pop() is False:
                    ip += delta

            elif op == Op.JUMP_IF_FALSE_OR_POP:
                delta = int.from_bytes(code[ip:ip + 2], "little", signed=True)
                ip += 2
                if stack[-1] is False:
                    ip += delta
                else:
                    stack.pop()
            elif op == Op.JUMP_IF_TRUE_OR_POP:
                delta = int.from_bytes(code[ip:ip + 2], "little", signed=True)
                ip += 2
                if stack[-1] is True:
                    ip += delta
                else:
                    stack.pop()

            elif op == Op.CALL:
                # Stack for a call with N arguments:
                #   ... callee arg0 .. argN-1 [extra locals] <temporaries>
                #       ^ base-1               ^ base+N
                # so LOAD_LOCAL i is stack[base + i], and RET truncates to base-1.
                argc = code[ip]
                ip += 1
                callee = stack[-argc - 1]
                if not isinstance(callee, FunctionValue):
                    raise self.fail(f"cannot call {to_display(callee)}", fn, ip)
                target = callee.fn
                if len(frames) >= MAX_FRAMES:
                    raise self.fail(f"call stack overflow (limit {MAX_FRAMES} frames)", fn, ip)
                frames.append(Frame(fn, ip, base))
                base = len(stack) - argc
                if target.nlocals > argc:
                    stack.extend([UNIT] * (target.nlocals - argc))
                fn = target
                code = fn.code
                consts = fn.consts
                ip = 0
            elif op == Op.RET:
                result = stack.pop()
                del stack[base - 1:]
                stack.append(result)
                if not frames:
                    return result
                frame = frames.pop()
                fn = frame.fn
                ip = frame.ip
                base = frame.base
                code = fn.code
                consts = fn.consts

            elif op == Op.CALL_NATIVE:
                index = code[ip]
                argc = code[ip + 1]
                ip += 2
                args = stack[len(stack) - argc:] if argc else []
                if argc:
                    del stack[len(stack) - argc:]
                try:
                    stack.append(BUILTINS[index].native(self, args))
                except BorkRuntimeError as exc:
                    raise self.fail(exc.message, fn, ip) from None

            # -- aggregates -----------------------------------------------
            elif op == Op.MAKE_ARRAY:
                count = code[ip] | (code[ip + 1] << 8)
                ip += 2
                if count:
                    items = stack[len(stack) - count:]
                    del stack[len(stack) - count:]
                else:
                    items = []
                stack.append(items)
            elif op == Op.INDEX_GET:
                index = stack.pop()
                target = stack[-1]
                if index < 0 or index >= len(target):
                    kind = "string" if isinstance(target, str) else "array"
                    raise self.fail(
                        f"index {index} is out of bounds for {kind} of length {len(target)}", fn, ip)
                stack[-1] = target[index]
            elif op == Op.MAKE_STRUCT:
                definition = self.structs[code[ip] | (code[ip + 1] << 8)]
                ip += 2
                count = len(definition.field_names)
                fields = stack[len(stack) - count:]
                del stack[len(stack) - count:]
                stack.append(StructValue(definition, fields))
            elif op == Op.FIELD_GET:
                stack[-1] = stack[-1].fields[code[ip]]
                ip += 1
            elif op == Op.FIELD_SET:
                value = stack.pop()
                stack.pop().fields[code[ip]] = value
                ip += 1
            elif op == Op.LEN:
                stack[-1] = len(stack[-1])
            elif op == Op.INDEX_SET:
                value = stack.pop()
                index = stack.pop()
                target = stack.pop()
                if index < 0 or index >= len(target):
                    raise self.fail(
                        f"index {index} is out of bounds for array of length {len(target)}", fn, ip)
                target[index] = value

            elif op == Op.HALT:
                return UNIT
            elif op == Op.NOP:
                pass
            else:
                raise self.fail(f"illegal instruction {op} at offset {ip - 1}", fn, ip)


    def _trace(self, fn, ip, stack, base) -> None:
        from .bytecode import decode
        op, operands, _ = decode(fn.code, ip)
        args = " ".join(str(x) for x in operands)
        top = ", ".join(to_display(v) for v in stack[base:][-5:])
        print(f"[{fn.name:>10} {ip:>4}] {op.name:<22} {args:<8} | {top}", file=sys.stderr)


def run(program: Program, out=None, trace: bool = False) -> VM:
    vm = VM(program, out=out, trace=trace)
    vm.run()
    return vm
