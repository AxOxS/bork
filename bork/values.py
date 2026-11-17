"""Runtime values, and the 64-bit integer semantics Python doesn't give us for free."""
from __future__ import annotations

import math

MIN_I64 = -(1 << 63)
MAX_I64 = (1 << 63) - 1
_MASK = (1 << 64) - 1


def wrap64(value: int) -> int:
    value &= _MASK
    return value - (1 << 64) if value > MAX_I64 else value


# Truncates toward zero, unlike Python's //.
def idiv(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


# Sign follows the dividend.
def imod(a: int, b: int) -> int:
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


# A global whose initialiser hasn't run yet.
class Uninitialised:

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


# Inside containers, strings are quoted.
def to_repr(value) -> str:
    if isinstance(value, str):
        escaped = (value.replace("\\", "\\\\").replace('"', '\\"')
                   .replace("\n", "\\n").replace("\t", "\\t"))
        return f'"{escaped}"'
    return to_display(value)


# What str() and print() produce.
def to_display(value) -> str:
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
