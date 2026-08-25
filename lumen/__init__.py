"""Lumen -- a small statically typed language and its compiler.

Pipeline:  source -> tokens -> AST -> typed AST -> bytecode -> VM

    from lumen import run_source
    run_source("print(1 + 2);")
"""
from __future__ import annotations

from .bytecode import Program
from .checker import Checker, check
from .compiler import compile_module
from .disasm import disassemble
from .errors import LumenError, LumenRuntimeError
from .lexer import tokenize
from .parser import parse
from .vm import VM

__version__ = "0.0.1"
__all__ = ["compile_source", "run_source", "tokenize", "parse", "check", "compile_module",
           "disassemble", "Checker", "CompileResult", "Program", "VM",
           "LumenError", "LumenRuntimeError"]


class CompileResult:
    def __init__(self, program: Program, checker: Checker, module):
        self.program = program
        self.checker = checker
        self.module = module


def compile_source(source: str, filename: str = "<input>") -> CompileResult:
    """Run the whole front end and back end. Raises LumenError on bad input."""
    module = parse(source, filename)
    checker = check(module, source, filename)
    program = compile_module(module, checker, filename)
    return CompileResult(program, checker, module)


def run_source(source: str, filename: str = "<input>", out=None) -> VM:
    """Compile and immediately execute. Raises LumenRuntimeError on a trap."""
    vm = VM(compile_source(source, filename).program, out=out)
    vm.run()
    return vm
