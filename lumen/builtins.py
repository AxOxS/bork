"""Built-in functions.

Builtins are not first-class values: calls to them are resolved at compile time
and lowered to a CALL_NATIVE instruction. Each builtin has a hand-written
checking rule, because several are polymorphic in ways the surface type system
cannot express.
"""
from __future__ import annotations

from . import types as T
from .values import UNIT, to_display


class BuiltinSig:
    def __init__(self, name: str, arity, check, native, doc: str):
        self.name = name
        self.arity = arity            # int or (min, max)
        self.check = check            # (argtys, report) -> Type
        self.native = native          # (vm, args) -> value
        self.doc = doc


def _arity_ok(sig: BuiltinSig, n: int) -> bool:
    if isinstance(sig.arity, tuple):
        return sig.arity[0] <= n <= sig.arity[1]
    return n == sig.arity


# -- checking rules --------------------------------------------------------
def _c_print(a, report):
    if a[0] is T.UNIT:
        report("cannot print a value of type `unit`")
    return T.UNIT


# -- native implementations -----------------------------------------------
def _n_print(vm, args):
    vm.out.write(to_display(args[0]) + "\n")
    return UNIT


# Index order is part of the bytecode ABI: appending is safe, reordering is not.
BUILTINS: list[BuiltinSig] = [
    BuiltinSig("print", 1, _c_print, _n_print, "print(v) -> unit    write a value and a newline"),
]

BUILTIN_INDEX = {b.name: i for i, b in enumerate(BUILTINS)}


def lookup(name: str) -> BuiltinSig | None:
    i = BUILTIN_INDEX.get(name)
    return BUILTINS[i] if i is not None else None


def arity_ok(sig: BuiltinSig, n: int) -> bool:
    return _arity_ok(sig, n)
