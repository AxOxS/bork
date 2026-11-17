"""Shared harness: compile a snippet, run it, capture its output."""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bork import compile_source, deserialize, serialize          # noqa: E402
from bork.errors import BorkError, BorkRuntimeError            # noqa: E402
from bork.vm import VM                                           # noqa: E402


# BORK_BACKEND=c runs every program through the C back end instead of the VM,
# so the whole execution suite doubles as a conformance test for it.
BACKEND = os.environ.get("BORK_BACKEND", "vm")


# Builds with the C back end and runs the binary.
def run_native(source: str, optimise: bool = True, filename: str = "<test>"):
    from bork.cbackend import compile_c, generate
    result = compile_source(source, filename, optimise=optimise)
    c_source = generate(result.module, result.checker, filename)
    with tempfile.TemporaryDirectory() as tmp:
        exe = os.path.join(tmp, "prog")
        compile_c(c_source, exe, keep_c=False)
        return subprocess.run([exe], capture_output=True, text=True, timeout=120)


# The error the VM would have raised, rebuilt from a binary's stderr.
def native_runtime_error(stderr: str) -> BorkRuntimeError:
    lines = stderr.rstrip("\n").split("\n")
    assert lines[0].startswith("runtime error: "), stderr
    return BorkRuntimeError(lines[0][len("runtime error: "):], [l.strip() for l in lines[1:]])


def run(source: str, optimise: bool = True, via_object_file: bool = False) -> str:
    if BACKEND == "c":
        proc = run_native(source, optimise)
        if proc.returncode == 70:
            raise native_runtime_error(proc.stderr)
        if proc.returncode != 0:
            raise AssertionError(f"native program exited with {proc.returncode}: {proc.stderr}")
        return proc.stdout
    result = compile_source(source, "<test>", optimise=optimise)
    program = deserialize(serialize(result.program)) if via_object_file else result.program
    buffer = io.StringIO()
    VM(program, out=buffer).run()
    return buffer.getvalue()


def run_main(body: str, **kwargs) -> str:
    return run("fn main() {\n" + body + "\n}", **kwargs)


# Prints one expression; returns the text without the newline.
def expr_output(expression: str, **kwargs) -> str:
    return run_main(f"    print({expression});", **kwargs).rstrip("\n")


# Expects compilation to fail.
def compile_errors(source: str) -> list[str]:
    try:
        compile_source(source, "<test>")
    except BorkError as exc:
        return [d.message for d in exc.diagnostics]
    raise AssertionError("expected a compile error, but compilation succeeded")


def warnings_of(source: str) -> list[str]:
    return [d.message for d in compile_source(source, "<test>").warnings]


def runtime_error(source: str) -> str:
    try:
        run(source)
    except BorkRuntimeError as exc:
        return exc.message
    raise AssertionError("expected a runtime error, but the program completed")


def opcodes_of(source: str, fn_name: str = "<main>", optimise: bool = True) -> list:
    from bork.bytecode import decode
    program = compile_source(source, "<test>", optimise=optimise).program
    fn = next(f for f in program.functions if f.name == fn_name)
    ops, offset = [], 0
    while offset < len(fn.code):
        op, _, offset = decode(fn.code, offset)
        ops.append(op)
    return ops


def program_of(source: str, optimise: bool = True):
    return compile_source(source, "<test>", optimise=optimise).program


def entry_of(source: str, optimise: bool = True):
    return compile_source(source, "<test>", optimise=optimise).program.entry


def constants_of(source: str, fn_name: str = "<main>", optimise: bool = True) -> list:
    program = compile_source(source, "<test>", optimise=optimise).program
    return next(f for f in program.functions if f.name == fn_name).consts
