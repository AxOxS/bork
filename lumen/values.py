"""Runtime value representation and Lumen's integer semantics.

Lumen's `int` is a 64-bit two's-complement integer, like C's int64_t. Python's
ints are arbitrary precision and its `//` floors, so neither wrapping nor
division comes for free: both are spelled out here and used by every phase that
has to know what an operation means.
"""
from __future__ import annotations

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


def format_float(value: float) -> str:
    if value != value:
        return "nan"
    if value == float("inf"):
        return "inf"
    if value == float("-inf"):
        return "-inf"
    if value == int(value) and abs(value) < 1e16:
        return f"{int(value)}.0"
    return repr(value)


def to_display(value) -> str:
    """User-facing form of a runtime value."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float):
        return format_float(value)
    return str(value)
