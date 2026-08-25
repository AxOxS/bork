import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumen import compile_source, run_source        # noqa: E402
from lumen.bytecode import decode                   # noqa: E402
from lumen.errors import LumenRuntimeError          # noqa: E402
from lumen.opcodes import Op                        # noqa: E402


def opcodes_of(source):
    fn = compile_source(source)
    ops, offset = [], 0
    while offset < len(fn.code):
        op, _, offset = decode(fn.code, offset)
        ops.append(op)
    return ops


class TestExecution(unittest.TestCase):
    def test_literal(self):
        self.assertEqual(run_source("42"), 42)

    def test_the_four_operators(self):
        self.assertEqual(run_source("1 + 2"), 3)
        self.assertEqual(run_source("7 - 3"), 4)
        self.assertEqual(run_source("6 * 7"), 42)
        self.assertEqual(run_source("9 / 3"), 3)

    def test_precedence_is_honoured_at_runtime(self):
        self.assertEqual(run_source("1 + 2 * 3"), 7)
        self.assertEqual(run_source("(1 + 2) * 3"), 9)

    def test_left_associativity(self):
        self.assertEqual(run_source("10 - 2 - 3"), 5)
        self.assertEqual(run_source("100 / 5 / 2"), 10)

    def test_negation(self):
        self.assertEqual(run_source("-5"), -5)
        self.assertEqual(run_source("-(2 + 3)"), -5)

    def test_deeply_nested_expression(self):
        self.assertEqual(run_source("((((1 + 1) * 2) + 1) * 3)"), 15)

    def test_division_by_zero_traps(self):
        with self.assertRaises(LumenRuntimeError) as ctx:
            run_source("1 / 0")
        self.assertIn("division by zero", ctx.exception.message)

    def test_remainder_by_zero_traps(self):
        with self.assertRaises(LumenRuntimeError):
            run_source("1 % 0")


class TestCodegen(unittest.TestCase):
    def test_operators_lower_to_their_opcodes(self):
        self.assertEqual(opcodes_of("1 + 2"), [Op.CONST, Op.CONST, Op.ADD, Op.HALT])

    def test_constants_are_deduplicated(self):
        self.assertEqual(compile_source("7 + 7 + 7").consts, [7])

    def test_every_program_ends_in_halt(self):
        self.assertEqual(opcodes_of("1")[-1], Op.HALT)

    def test_stack_is_balanced(self):
        # Every expression must leave exactly one value behind.
        vm_result = run_source("1 + 2 * 3 - 4")
        self.assertEqual(vm_result, 3)


if __name__ == "__main__":
    unittest.main()
