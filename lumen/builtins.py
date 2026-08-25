"""Built-in functions.

Builtins are not first-class values: calls to them are resolved at compile time
and lowered to a CALL_NATIVE instruction. Each builtin has a hand-written
checking rule, because several are polymorphic in ways the surface type system
cannot express.
"""
from __future__ import annotations

from . import types as T
from .errors import LumenRuntimeError
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


def _c_len(a, report):
    t = a[0]
    if not isinstance(t, T.ArrayType) and t is not T.STR and t is not T.ERROR:
        report(f"`len` expects an array or `str`, found `{t}`")
    return T.INT


def _c_push(a, report):
    arr, val = a
    if not isinstance(arr, T.ArrayType):
        if arr is not T.ERROR:
            report(f"`push` expects an array as its first argument, found `{arr}`")
        return T.UNIT
    if not T.compatible(arr.elem, val):
        report(f"cannot push `{val}` onto `{arr}`")
    return T.UNIT


def _c_pop(a, report):
    arr = a[0]
    if not isinstance(arr, T.ArrayType):
        if arr is not T.ERROR:
            report(f"`pop` expects an array, found `{arr}`")
        return T.ERROR
    return arr.elem


def _c_str(a, report):
    if a[0] is T.UNIT:
        report("cannot convert `unit` to `str`")
    return T.STR


# -- native implementations -----------------------------------------------
def _n_print(vm, args):
    vm.out.write(to_display(args[0]) + "\n")
    return UNIT


def _n_len(vm, args):
    return len(args[0])


def _n_str(vm, args):
    return to_display(args[0])


def _n_push(vm, args):
    args[0].append(args[1])
    return UNIT


def _n_pop(vm, args):
    arr = args[0]
    if not arr:
        raise LumenRuntimeError("pop from empty array")
    return arr.pop()


# Index order is part of the bytecode ABI: appending is safe, reordering is not.
BUILTINS: list[BuiltinSig] = [
    BuiltinSig("print", 1, _c_print, _n_print, "print(v) -> unit    write a value and a newline"),
    BuiltinSig("len",   1, _c_len,   _n_len,   "len(x) -> int       length of an array or string"),
    BuiltinSig("str",   1, _c_str,   _n_str,   "str(v) -> str       convert any value to text"),
    BuiltinSig("push",  2, _c_push,  _n_push,  "push(a, v) -> unit  append to an array"),
    BuiltinSig("pop",   1, _c_pop,   _n_pop,   "pop(a) -> T         remove and return the last element"),
]

BUILTIN_INDEX = {b.name: i for i, b in enumerate(BUILTINS)}


def lookup(name: str) -> BuiltinSig | None:
    i = BUILTIN_INDEX.get(name)
    return BUILTINS[i] if i is not None else None


def arity_ok(sig: BuiltinSig, n: int) -> bool:
    return _arity_ok(sig, n)
