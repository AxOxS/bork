"""Shared harness: compile a snippet, run it, capture its output."""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumen import compile_source                                  # noqa: E402
from lumen.errors import LumenError, LumenRuntimeError            # noqa: E402
from lumen.vm import VM                                           # noqa: E402


def run(source: str) -> str:
    """Compile and run `source`, returning everything it printed."""
    result = compile_source(source, "<test>")
    buffer = io.StringIO()
    VM(result.program, out=buffer).run()
    return buffer.getvalue()


def run_main(body: str) -> str:
    """Run statements as the body of `main`."""
    return run("fn main() {\n" + body + "\n}")


def expr_output(expression: str) -> str:
    """Print a single expression and return the text, without the newline."""
    return run_main(f"    print({expression});").rstrip("\n")


def compile_errors(source: str) -> list[str]:
    """Compile expecting failure; return the error messages."""
    try:
        compile_source(source, "<test>")
    except LumenError as exc:
        return [d.message for d in exc.diagnostics]
    raise AssertionError("expected a compile error, but compilation succeeded")


def warnings_of(source: str) -> list[str]:
    return [d.message for d in compile_source(source, "<test>").warnings]


def runtime_error(source: str) -> str:
    try:
        run(source)
    except LumenRuntimeError as exc:
        return exc.message
    raise AssertionError("expected a runtime error, but the program completed")


def opcodes_of(source: str, fn_name: str = "<main>") -> list:
    from lumen.bytecode import decode
    program = compile_source(source, "<test>").program
    fn = next(f for f in program.functions if f.name == fn_name)
    ops, offset = [], 0
    while offset < len(fn.code):
        op, _, offset = decode(fn.code, offset)
        ops.append(op)
    return ops


def program_of(source: str):
    return compile_source(source, "<test>").program


def entry_of(source: str):
    return compile_source(source, "<test>").program.entry


def constants_of(source: str, fn_name: str = "<main>") -> list:
    program = compile_source(source, "<test>").program
    return next(f for f in program.functions if f.name == fn_name).consts
