"""Bork, a small statically typed language. `compile_source` and `run_source` are the entry points."""
from __future__ import annotations

from .bytecode import Program, deserialize, serialize
from .checker import Checker, check
from .compiler import compile_module
from .disasm import disassemble
from .errors import BorkError, BorkRuntimeError
from .lexer import tokenize
from .optimizer import optimize
from .parser import parse
from .vm import VM

__version__ = "1.0.0"
__all__ = ["compile_source", "run_source", "tokenize", "parse", "check", "optimize",
           "compile_module",
           "disassemble", "serialize", "deserialize", "Checker", "CompileResult", "Program", "VM",
           "BorkError", "BorkRuntimeError"]


class CompileResult:
    def __init__(self, program: Program, checker: Checker, module, optimizer=None):
        self.program = program
        self.checker = checker
        self.module = module
        self.optimizer = optimizer

    @property
    def warnings(self):
        return self.checker.warnings


# Runs every phase. Raises BorkError on bad input.
def compile_source(source: str, filename: str = "<input>", optimise: bool = True) -> CompileResult:
    module = parse(source, filename)
    checker = check(module, source, filename)
    opt = optimize(module) if optimise else None
    try:
        program = compile_module(module, checker, filename)
    except BorkError as exc:
        # Back-end limit errors are raised without source context; add it here
        # so they render with a snippet like every other diagnostic.
        if not exc.source:
            exc.source, exc.filename = source, filename
        raise
    return CompileResult(program, checker, module, opt)


def run_source(source: str, filename: str = "<input>", out=None, optimise: bool = True) -> VM:
    vm = VM(compile_source(source, filename, optimise).program, out=out)
    vm.run()
    return vm
