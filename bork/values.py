"""Runtime value representation and Bork's integer semantics.

Bork's `int` is a 64-bit two's-complement integer, like C's int64_t. Python's
ints are arbitrary precision and its `//` floors, so neither wrapping nor
division comes for free: both are spelled out here and used by every phase that
has to know what an operation means.
"""
from __future__ import annotations

import math

MIN_I64 = -(1 << 63)
MAX_I64 = (1 << 63) - 1
_MASK = (1 << 64) - 1


def wrap64(value: int) -> int:
    """Wrap to 64-bit two's complement, like C's int64_t."""
    value &= _MASK
    return value - (1 << 64) if value > MAX_I64 else value


def idiv(a: int, b: int) -> int:
    """Integer division truncating toward zero (C/Rust semantics, not Python's)."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def imod(a: int, b: int) -> int:
    """Remainder whose sign follows the dividend."""
    return a - idiv(a, b) * b


class Unit:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "unit"


UNIT = Unit()


class Uninitialised:
    """Sentinel stored in globals that have not run their initialiser yet."""

    def __repr__(self) -> str:
        return "<uninitialised>"


UNINIT = Uninitialised()


class StructValue:
    __slots__ = ("def_", "fields")

    def __init__(self, def_, fields: list):
        self.def_ = def_
        self.fields = fields

    def __repr__(self) -> str:
        return to_repr(self)


class FunctionValue:
    """A compiled function bound as a callable value."""

    __slots__ = ("fn",)

    def __init__(self, fn):
        self.fn = fn

    def __repr__(self) -> str:
        return f"<fn {self.fn.name}>"


def format_float(value: float) -> str:
    if value != value:
        return "nan"
    if value == float("inf"):
        return "inf"
    if value == float("-inf"):
        return "-inf"
    if value == int(value) and abs(value) < 1e16:
        # int(-0.0) is 0, which would silently drop the sign of negative zero.
        sign = "-" if value == 0.0 and math.copysign(1.0, value) < 0 else ""
        return f"{sign}{int(value)}.0"
    return repr(value)


def to_repr(value) -> str:
    """Developer-facing form: strings are quoted (used inside containers)."""
    if isinstance(value, str):
        escaped = (value.replace("\\", "\\\\").replace('"', '\\"')
                   .replace("\n", "\\n").replace("\t", "\\t"))
        return f'"{escaped}"'
    return to_display(value)


def to_display(value) -> str:
    """User-facing form, as produced by `str(...)` and `print(...)`."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is UNIT:
        return "unit"
    if isinstance(value, float):
        return format_float(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "[" + ", ".join(to_repr(v) for v in value) + "]"
    if isinstance(value, StructValue):
        parts = ", ".join(f"{n}: {to_repr(v)}"
                          for n, v in zip(value.def_.field_names, value.fields))
        return f"{value.def_.name}{{{parts}}}"
    if isinstance(value, FunctionValue):
        return f"<fn {value.fn.name}>"
    return str(value)
