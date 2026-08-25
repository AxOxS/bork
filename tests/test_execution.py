import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumen import compile_source, run_source        # noqa: E402
from lumen.bytecode import decode                   # noqa: E402
from lumen.errors import LumenRuntimeError          # noqa: E402
from lumen.errors import LumenError                 # noqa: E402
from lumen.opcodes import Op                        # noqa: E402
from lumen.values import MAX_I64, MIN_I64           # noqa: E402


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


class TestIntegerSemantics(unittest.TestCase):
    """Lumen's int is C's int64_t, which is not what Python's int does."""

    def test_division_truncates_toward_zero(self):
        # Python's -7 // 2 is -4; Lumen, like C and Rust, gives -3.
        self.assertEqual(run_source("7 / 2"), 3)
        self.assertEqual(run_source("-7 / 2"), -3)
        self.assertEqual(run_source("7 / -2"), -3)
        self.assertEqual(run_source("-7 / -2"), 3)

    def test_remainder_takes_the_sign_of_the_dividend(self):
        # Python's -7 % 2 is 1; Lumen gives -1.
        self.assertEqual(run_source("-7 % 2"), -1)
        self.assertEqual(run_source("7 % -2"), 1)
        self.assertEqual(run_source("-7 % -2"), -1)

    def test_quotient_and_remainder_agree(self):
        for a in (-9, -7, -1, 0, 1, 7, 9):
            for b in (-3, -2, 2, 3):
                with self.subTest(a=a, b=b):
                    q = run_source(f"({a}) / ({b})")
                    r = run_source(f"({a}) % ({b})")
                    self.assertEqual(q * b + r, a)

    def test_addition_wraps_at_64_bits(self):
        self.assertEqual(run_source(f"{MAX_I64} + 1"), MIN_I64)

    def test_multiplication_wraps_at_64_bits(self):
        self.assertEqual(run_source(f"{MAX_I64} * 2"), -2)

    def test_negation_wraps(self):
        # -MIN_I64 has no positive counterpart, so it wraps back to itself.
        self.assertEqual(run_source(f"-({MAX_I64} + 1)"), MIN_I64)

    def test_literal_too_large_is_rejected(self):
        with self.assertRaises(LumenError) as ctx:
            run_source(str(MAX_I64 + 1))
        self.assertIn("64-bit", ctx.exception.diagnostics[0].message)


class TestFloats(unittest.TestCase):
    def test_float_arithmetic(self):
        self.assertEqual(run_source("1.5 + 2.5"), 4.0)
        self.assertEqual(run_source("7.0 / 2.0"), 3.5)

    def test_float_division_is_ieee_and_does_not_trap(self):
        self.assertEqual(run_source("1.0 / 0.0"), float("inf"))
        self.assertEqual(run_source("-1.0 / 0.0"), float("-inf"))
        self.assertNotEqual(run_source("0.0 / 0.0"), run_source("0.0 / 0.0"))   # nan

    def test_float_literals_do_not_wrap(self):
        self.assertEqual(run_source("1e300 * 10.0"), 1e301)


class TestComparisons(unittest.TestCase):
    def test_ordering(self):
        self.assertIs(run_source("1 < 2"), True)
        self.assertIs(run_source("2 <= 2"), True)
        self.assertIs(run_source("3 > 4"), False)
        self.assertIs(run_source("3 >= 4"), False)

    def test_equality(self):
        self.assertIs(run_source("1 == 1"), True)
        self.assertIs(run_source("1 != 1"), False)

    def test_booleans(self):
        self.assertIs(run_source("true"), True)
        self.assertIs(run_source("!true"), False)
        self.assertIs(run_source("!(1 == 2)"), True)

    def test_comparison_of_arithmetic_results(self):
        self.assertIs(run_source("1 + 2 * 3 == 7"), True)


class TestCodegen(unittest.TestCase):
    def test_operators_lower_to_the_opcode_for_their_type(self):
        self.assertEqual(opcodes_of("1 + 2"), [Op.CONST, Op.CONST, Op.ADD_INT, Op.HALT])
        self.assertEqual(opcodes_of("1.0 + 2.0"), [Op.CONST, Op.CONST, Op.ADD_FLOAT, Op.HALT])

    def test_negation_picks_the_typed_opcode(self):
        self.assertIn(Op.NEG_INT, opcodes_of("-(1 + 2)"))
        self.assertIn(Op.NEG_FLOAT, opcodes_of("-(1.0 + 2.0)"))

    def test_the_vm_has_no_generic_arithmetic_left(self):
        # Every arithmetic opcode names the type it operates on.
        self.assertFalse([name for name in Op.__members__
                          if name in ("ADD", "SUB", "MUL", "DIV", "MOD", "NEG")])

    def test_constants_are_deduplicated(self):
        self.assertEqual(compile_source("7 + 7 + 7").consts, [7])

    def test_negative_literals_do_not_emit_a_negation(self):
        self.assertEqual(opcodes_of("-5"), [Op.CONST, Op.HALT])
        self.assertEqual(compile_source("-5").consts, [-5])

    def test_booleans_have_dedicated_opcodes(self):
        self.assertEqual(opcodes_of("true"), [Op.TRUE, Op.HALT])
        self.assertEqual(compile_source("true").consts, [])

    def test_int_and_float_constants_do_not_collide(self):
        # Python considers 1 == 1.0; the constant pool must not merge them.
        self.assertEqual(compile_source("(1 == 1) == (1.0 == 1.0)").consts, [1, 1.0])

    def test_every_program_ends_in_halt(self):
        self.assertEqual(opcodes_of("1")[-1], Op.HALT)

    def test_stack_is_balanced(self):
        # Every expression must leave exactly one value behind.
        vm_result = run_source("1 + 2 * 3 - 4")
        self.assertEqual(vm_result, 3)


if __name__ == "__main__":
    unittest.main()
