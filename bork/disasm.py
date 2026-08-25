"""Bytecode disassembler -- `borkc dis`.

The VM decodes operands inline for speed; this walks the same stream through
bytecode.decode(), which is the readable version. Keeping the two in step is
what the operand table in opcodes.py is for.
"""
from __future__ import annotations

from .bytecode import Function, Program, decode
from .opcodes import JUMPS, Op
from .values import to_repr


def disassemble_function(fn: Function, program: Program | None = None) -> str:
    out = [f"{fn.signature or fn.name}",
           f"  ; {len(fn.code)} bytes, {fn.arity} param(s), {fn.nlocals} local slot(s), "
           f"{len(fn.consts)} constant(s)"]
    offset = 0
    last_line = None
    while offset < len(fn.code):
        op, operands, next_offset = decode(fn.code, offset)
        line = fn.line_for(offset)
        line_col = f"{line:>4}" if line != last_line else "    "
        last_line = line
        text = f"  {line_col} {offset:>5}  {op.name:<22}"
        if op in JUMPS:
            target = next_offset + operands[0]
            text += f"{operands[0]:<6} -> {target}"
        elif op == Op.CONST:
            text += f"{operands[0]:<6} ; {to_repr(fn.consts[operands[0]])}"
        elif op == Op.CALL_NATIVE:
            from .builtins import BUILTINS
            text += f"{operands[0]}, {operands[1]:<3} ; {BUILTINS[operands[0]].name}"
        elif op == Op.MAKE_STRUCT and program:
            text += f"{operands[0]:<6} ; {program.structs[operands[0]].name}"
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
           f"; {len(program.functions)} function(s), {program.nglobals} global slot(s), "
           f"{len(program.structs)} struct(s)"]
    for st in program.structs:
        out.append(f"; struct {st.name} {{ {', '.join(st.field_names)} }}")
    out.append("")
    for i, fn in enumerate(program.functions):
        marker = "  [entry]" if i == program.entry_index else ""
        out.append(f"=== [{i}] {fn.name}{marker}")
        out.append(disassemble_function(fn, program))
        out.append("")
    return "\n".join(out)
