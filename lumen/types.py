"""The Lumen type lattice.

Primitives are singletons so identity comparison works.
"""
from __future__ import annotations


class Type:
    def __str__(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def __repr__(self) -> str:
        return str(self)


class Primitive(Type):
    def __init__(self, name: str):
        self.name = name

    def __str__(self) -> str:
        return self.name

    def __hash__(self) -> int:
        return hash(("prim", self.name))

    def __eq__(self, other) -> bool:
        return isinstance(other, Primitive) and other.name == self.name


INT = Primitive("int")
FLOAT = Primitive("float")
BOOL = Primitive("bool")
STR = Primitive("str")
UNIT = Primitive("unit")
# Assigned to expressions whose type could not be determined; suppresses
# cascading errors because it is compatible with everything.
ERROR = Primitive("<error>")

PRIMITIVES = {"int": INT, "float": FLOAT, "bool": BOOL, "str": STR, "unit": UNIT}
NUMERIC = (INT, FLOAT)


class ArrayType(Type):
    def __init__(self, elem: Type):
        self.elem = elem

    def __str__(self) -> str:
        return f"[{self.elem}]"

    def __hash__(self) -> int:
        return hash(("array", self.elem))

    def __eq__(self, other) -> bool:
        return isinstance(other, ArrayType) and other.elem == self.elem


class FnType(Type):
    def __init__(self, params: list[Type], ret: Type):
        self.params = params
        self.ret = ret

    def __str__(self) -> str:
        args = ", ".join(str(p) for p in self.params)
        return f"fn({args}) -> {self.ret}"

    def __hash__(self) -> int:
        return hash(("fn", tuple(self.params), self.ret))

    def __eq__(self, other) -> bool:
        return isinstance(other, FnType) and other.params == self.params and other.ret == self.ret


def compatible(expected: Type, actual: Type) -> bool:
    """Assignability. ERROR unifies with anything to avoid error cascades."""
    if expected is ERROR or actual is ERROR:
        return True
    return expected == actual
