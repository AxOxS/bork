"""Lumen -- a small statically typed language and its compiler.

Pipeline:  source -> tokens -> AST -> typed AST -> bytecode -> VM
"""
from __future__ import annotations

from .bytecode import Function
from .checker import Checker, check
from .compiler import compile_module
from .disasm import disassemble
from .errors import LumenError, LumenRuntimeError
from .lexer import tokenize
from .parser import parse
from .vm import VM

__version__ = "0.0.1"
__all__ = ["compile_source", "run_source", "tokenize", "parse", "check", "compile_module",
           "disassemble", "Checker",
           "Function", "VM", "LumenError", "LumenRuntimeError"]


def compile_source(source: str, filename: str = "<input>") -> Function:
    """Run the whole pipeline. Raises LumenError on bad input."""
    module = parse(source, filename)
    check(module, source, filename)
    return compile_module(module)


def run_source(source: str, filename: str = "<input>"):
    """Compile and immediately execute, returning the result."""
    return VM(compile_source(source, filename)).run()
