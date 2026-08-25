"""Lumen -- a small statically typed language and its compiler.

Pipeline:  source -> tokens -> AST -> typed AST -> optimised AST -> bytecode -> VM

    from lumen import run_source
    run_source("print(1 + 2);")
"""
from __future__ import annotations

from .bytecode import Program, deserialize, serialize
from .checker import Checker, check
from .compiler import compile_module
from .disasm import disassemble
from .errors import LumenError, LumenRuntimeError
from .lexer import tokenize
from .optimizer import optimize
from .parser import parse
from .vm import VM

__version__ = "0.0.1"
__all__ = ["compile_source", "run_source", "tokenize", "parse", "check", "optimize",
           "compile_module",
           "disassemble", "serialize", "deserialize", "Checker", "CompileResult", "Program", "VM",
           "LumenError", "LumenRuntimeError"]


class CompileResult:
    def __init__(self, program: Program, checker: Checker, module, optimizer=None):
        self.program = program
        self.checker = checker
        self.module = module
        self.optimizer = optimizer

    @property
    def warnings(self):
        return self.checker.warnings


def compile_source(source: str, filename: str = "<input>", optimise: bool = True) -> CompileResult:
    """Run the whole front end and back end. Raises LumenError on bad input."""
    module = parse(source, filename)
    checker = check(module, source, filename)
    opt = optimize(module) if optimise else None
    try:
        program = compile_module(module, checker, filename)
    except LumenError as exc:
        # Back-end limit errors are raised without source context; add it here
        # so they render with a snippet like every other diagnostic.
        if not exc.source:
            exc.source, exc.filename = source, filename
        raise
    return CompileResult(program, checker, module, opt)


def run_source(source: str, filename: str = "<input>", out=None, optimise: bool = True) -> VM:
    """Compile and immediately execute. Raises LumenRuntimeError on a trap."""
    vm = VM(compile_source(source, filename, optimise).program, out=out)
    vm.run()
    return vm
