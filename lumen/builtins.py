"""Built-in functions.

Builtins are not first-class values: calls to them are resolved at compile time
and lowered to a CALL_NATIVE instruction (or, for `len`, to a dedicated opcode).
Each builtin has a hand-written checking rule because several are polymorphic in
ways the surface type system cannot express.
"""
from __future__ import annotations

import math
import time

from . import types as T
from .errors import LumenRuntimeError
from .values import UNIT, to_display, wrap64


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


def _c_str(a, report):
    if a[0] is T.UNIT:
        report("cannot convert `unit` to `str`")
    return T.STR


def _c_int(a, report):
    if a[0] not in (T.INT, T.FLOAT, T.BOOL, T.STR, T.ERROR):
        report(f"cannot convert `{a[0]}` to `int`")
    return T.INT


def _c_float(a, report):
    if a[0] not in (T.INT, T.FLOAT, T.STR, T.ERROR):
        report(f"cannot convert `{a[0]}` to `float`")
    return T.FLOAT


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


def _c_sqrt(a, report):
    if a[0] not in (T.INT, T.FLOAT, T.ERROR):
        report(f"`sqrt` expects a number, found `{a[0]}`")
    return T.FLOAT


def _c_abs(a, report):
    if a[0] not in (T.INT, T.FLOAT, T.ERROR):
        report(f"`abs` expects a number, found `{a[0]}`")
        return T.ERROR
    return a[0]


def _c_minmax(name):
    def rule(a, report):
        x, y = a
        if x not in (T.INT, T.FLOAT, T.ERROR) or y not in (T.INT, T.FLOAT, T.ERROR):
            report(f"`{name}` expects two numbers, found `{x}` and `{y}`")
            return T.ERROR
        if x is not T.ERROR and y is not T.ERROR and x != y:
            report(f"`{name}` expects both arguments to have the same type, found `{x}` and `{y}`")
            return T.ERROR
        return x if x is not T.ERROR else y
    return rule


def _c_chr(a, report):
    if a[0] not in (T.INT, T.ERROR):
        report(f"`chr` expects an `int`, found `{a[0]}`")
    return T.STR


def _c_ord(a, report):
    if a[0] not in (T.STR, T.ERROR):
        report(f"`ord` expects a `str`, found `{a[0]}`")
    return T.INT


def _c_substr(a, report):
    s, i, j = a
    if s not in (T.STR, T.ERROR):
        report(f"`substr` expects a `str`, found `{s}`")
    if i not in (T.INT, T.ERROR) or j not in (T.INT, T.ERROR):
        report("`substr` expects `int` bounds")
    return T.STR


def _c_clock(a, report):
    return T.FLOAT


# -- native implementations -----------------------------------------------
def _n_print(vm, args):
    vm.out.write(to_display(args[0]) + "\n")
    return UNIT


def _n_len(vm, args):
    return len(args[0])


def _n_str(vm, args):
    return to_display(args[0])


def _n_int(vm, args):
    v = args[0]
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            raise LumenRuntimeError(f"cannot convert {to_display(v)} to int")
        return wrap64(int(v))
    if isinstance(v, str):
        try:
            return wrap64(int(v.strip()))
        except ValueError:
            raise LumenRuntimeError(f"cannot parse {v!r} as int") from None
    return v


def _n_float(vm, args):
    v = args[0]
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            raise LumenRuntimeError(f"cannot parse {v!r} as float") from None
    return float(v)


def _n_push(vm, args):
    args[0].append(args[1])
    return UNIT


def _n_pop(vm, args):
    arr = args[0]
    if not arr:
        raise LumenRuntimeError("pop from empty array")
    return arr.pop()


def _n_sqrt(vm, args):
    v = float(args[0])
    if v < 0:
        raise LumenRuntimeError(f"sqrt of negative number {to_display(args[0])}")
    return math.sqrt(v)


def _n_abs(vm, args):
    v = args[0]
    return wrap64(abs(v)) if isinstance(v, int) else abs(v)


def _n_min(vm, args):
    return args[0] if args[0] <= args[1] else args[1]


def _n_max(vm, args):
    return args[0] if args[0] >= args[1] else args[1]


def _n_chr(vm, args):
    code = args[0]
    if code < 0 or code > 0x10FFFF:
        raise LumenRuntimeError(f"chr: {code} is not a valid character code")
    return chr(code)


def _n_ord(vm, args):
    s = args[0]
    if len(s) != 1:
        raise LumenRuntimeError(f"ord expects a single-character string, got length {len(s)}")
    return ord(s)


def _n_substr(vm, args):
    s, i, j = args
    n = len(s)
    if i < 0 or j > n or i > j:
        raise LumenRuntimeError(f"substr bounds [{i}, {j}) out of range for string of length {n}")
    return s[i:j]


def _n_clock(vm, args):
    return time.perf_counter()


# Index order is part of the bytecode ABI: appending is safe, reordering is not.
BUILTINS: list[BuiltinSig] = [
    BuiltinSig("print",  1, _c_print,  _n_print,  "print(v) -> unit    write a value and a newline"),
    BuiltinSig("len",    1, _c_len,    _n_len,    "len(x) -> int       length of an array or string"),
    BuiltinSig("str",    1, _c_str,    _n_str,    "str(v) -> str       convert any value to text"),
    BuiltinSig("int",    1, _c_int,    _n_int,    "int(v) -> int       truncate a float / parse a str"),
    BuiltinSig("float",  1, _c_float,  _n_float,  "float(v) -> float   widen an int / parse a str"),
    BuiltinSig("push",   2, _c_push,   _n_push,   "push(a, v) -> unit  append to an array"),
    BuiltinSig("pop",    1, _c_pop,    _n_pop,    "pop(a) -> T         remove and return the last element"),
    BuiltinSig("sqrt",   1, _c_sqrt,   _n_sqrt,   "sqrt(x) -> float    square root"),
    BuiltinSig("abs",    1, _c_abs,    _n_abs,    "abs(x) -> int|float absolute value"),
    BuiltinSig("min",    2, _c_minmax("min"), _n_min, "min(a, b)           smaller of two numbers"),
    BuiltinSig("max",    2, _c_minmax("max"), _n_max, "max(a, b)           larger of two numbers"),
    BuiltinSig("chr",    1, _c_chr,    _n_chr,    "chr(c) -> str       character for a code point"),
    BuiltinSig("ord",    1, _c_ord,    _n_ord,    "ord(s) -> int       code point of a 1-char string"),
    BuiltinSig("substr", 3, _c_substr, _n_substr, "substr(s, i, j)     slice [i, j) of a string"),
    BuiltinSig("clock",  0, _c_clock,  _n_clock,  "clock() -> float    seconds from a monotonic clock"),
]

BUILTIN_INDEX = {b.name: i for i, b in enumerate(BUILTINS)}


def lookup(name: str) -> BuiltinSig | None:
    i = BUILTIN_INDEX.get(name)
    return BUILTINS[i] if i is not None else None


def arity_ok(sig: BuiltinSig, n: int) -> bool:
    return _arity_ok(sig, n)
