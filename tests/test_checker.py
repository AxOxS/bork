import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumen import compile_source                    # noqa: E402
from lumen import types as T                        # noqa: E402
from lumen.checker import check                     # noqa: E402
from lumen.errors import LumenError                 # noqa: E402
from lumen.parser import parse                      # noqa: E402


def errors_of(source):
    try:
        compile_source(source, "<test>")
    except LumenError as exc:
        return [d.message for d in exc.diagnostics]
    raise AssertionError("expected a compile error, but compilation succeeded")


def type_of(source):
    module = parse(source)
    check(module, source)
    return module.expr.ty


class TestTypeChecker(unittest.TestCase):
    def assertErrorMatches(self, source, fragment):
        errors = errors_of(source)
        self.assertTrue(any(fragment in e for e in errors),
                        f"expected an error containing {fragment!r}, got {errors}")

    # -- inference ---------------------------------------------------------
    def test_literals_have_their_own_types(self):
        self.assertIs(type_of("1"), T.INT)
        self.assertIs(type_of("1.5"), T.FLOAT)
        self.assertIs(type_of("true"), T.BOOL)

    def test_arithmetic_preserves_the_operand_type(self):
        self.assertIs(type_of("1 + 2 * 3"), T.INT)
        self.assertIs(type_of("1.5 * 2.0"), T.FLOAT)

    def test_comparisons_produce_bool(self):
        self.assertIs(type_of("1 < 2"), T.BOOL)
        self.assertIs(type_of("1.0 == 1.0"), T.BOOL)

    # -- no implicit conversions ------------------------------------------
    def test_int_and_float_do_not_mix(self):
        self.assertErrorMatches("1 + 2.0", "cannot apply `+` to `int` and `float`")
        self.assertErrorMatches("1.0 * 2", "cannot apply `*`")

    def test_the_error_explains_why(self):
        try:
            compile_source("1 + 2.0", "<test>")
        except LumenError as exc:
            self.assertIn("implicitly", exc.diagnostics[0].note or "")
        else:
            self.fail("expected a compile error")

    def test_arithmetic_on_bool_is_rejected(self):
        self.assertErrorMatches("true + 1", "cannot apply `+`")
        self.assertErrorMatches("-true", "cannot negate")

    def test_not_expects_bool(self):
        self.assertErrorMatches("!1", "`!` expects `bool`")

    def test_ordering_needs_comparable_operands(self):
        self.assertErrorMatches("true < false", "cannot compare")
        self.assertErrorMatches("1 < 2.0", "cannot compare `int` with `float`")

    def test_equality_needs_matching_types(self):
        self.assertErrorMatches("1 == true", "cannot compare `int` with `bool`")

    # -- error handling ----------------------------------------------------
    def test_several_errors_are_reported_at_once(self):
        self.assertGreaterEqual(len(errors_of("(1 + true) * (2.0 % false)")), 2)

    def test_a_poisoned_subexpression_does_not_cascade(self):
        # One error for `1 + true`, not a second for using its result.
        self.assertEqual(len(errors_of("(1 + true) + 1")), 1)

    def test_operand_kind_is_recorded_for_codegen(self):
        module = parse("1.5 + 2.5")
        check(module, "1.5 + 2.5")
        self.assertEqual(module.expr.kind, "float")


if __name__ == "__main__":
    unittest.main()
