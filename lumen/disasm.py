"""Bytecode disassembler -- `lumc dis`.

The VM decodes operands inline for speed; this walks the same stream through
bytecode.decode(), which is the readable version. Keeping the two in step is
what the operand table in opcodes.py is for.
"""
from __future__ import annotations

from .bytecode import Function, Program, decode
from .opcodes import JUMPS, Op


def disassemble_function(fn: Function, program: Program | None = None) -> str:
    out = [f"{fn.signature or fn.name}",
           f"  ; {len(fn.code)} bytes, {fn.arity} param(s), {fn.nlocals} local slot(s), "
           f"{len(fn.consts)} constant(s)"]
    offset = 0
    while offset < len(fn.code):
        op, operands, next_offset = decode(fn.code, offset)
        text = f"  {offset:>5}  {op.name:<22}"
        if op in JUMPS:
            target = next_offset + operands[0]
            text += f"{operands[0]:<6} -> {target}"
        elif op == Op.CONST:
            text += f"{operands[0]:<6} ; {fn.consts[operands[0]]!r}"
        elif op == Op.CALL_NATIVE:
            from .builtins import BUILTINS
            text += f"{operands[0]}, {operands[1]:<3} ; {BUILTINS[operands[0]].name}"
        elif op in (Op.LOAD_GLOBAL, Op.STORE_GLOBAL):
            name = program.global_names.get(operands[0]) if program else None
            text += f"{operands[0]:<6}" + (f" ; {name}" if name else "")
        elif operands:
            text += ", ".join(str(x) for x in operands)
        out.append(text.rstrip())
        offset = next_offset
    return "\n".join(out)


def disassemble(program: Program) -> str:
    out = [f"; module {program.source_name}",
           f"; {len(program.functions)} function(s), {program.nglobals} global slot(s)",
           ""]
    for i, fn in enumerate(program.functions):
        marker = "  [entry]" if i == program.entry_index else ""
        out.append(f"=== [{i}] {fn.name}{marker}")
        out.append(disassemble_function(fn, program))
        out.append("")
    return "\n".join(out)
