import unittest

from helpers import compile_errors as errors_of
from lumen import compile_source
from lumen import types as T
from lumen.checker import check
from lumen.errors import LumenError
from lumen.parser import parse


def type_of(expression):
    source = expression + ";"
    module = parse(source)
    check(module, source)
    return module.stmts[0].expr.ty


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
        self.assertErrorMatches("print(1 + 2.0);", "cannot apply `+` to `int` and `float`")
        self.assertErrorMatches("print(1.0 * 2);", "cannot apply `*`")

    def test_the_error_explains_why(self):
        try:
            compile_source("print(1 + 2.0);", "<test>")
        except LumenError as exc:
            self.assertIn("implicitly", exc.diagnostics[0].note or "")
        else:
            self.fail("expected a compile error")

    def test_arithmetic_on_bool_is_rejected(self):
        self.assertErrorMatches("print(true + 1);", "cannot apply `+`")
        self.assertErrorMatches("print(-true);", "cannot negate")

    def test_not_expects_bool(self):
        self.assertErrorMatches("print(!1);", "`!` expects `bool`")

    def test_ordering_needs_comparable_operands(self):
        self.assertErrorMatches("print(true < false);", "cannot compare")
        self.assertErrorMatches("print(1 < 2.0);", "cannot compare `int` with `float`")

    def test_equality_needs_matching_types(self):
        self.assertErrorMatches("print(1 == true);", "cannot compare `int` with `bool`")

    # -- error handling ----------------------------------------------------
    def test_several_errors_are_reported_at_once(self):
        self.assertGreaterEqual(len(errors_of("print(1 + true); print(2.0 % false);")), 2)

    def test_a_poisoned_subexpression_does_not_cascade(self):
        # One error for `1 + true`, not a second for using its result.
        self.assertEqual(len(errors_of("print((1 + true) + 1);")), 1)

    def test_operand_kind_is_recorded_for_codegen(self):
        module = parse("print(1.5 + 2.5);")
        check(module, "print(1.5 + 2.5);")
        self.assertEqual(module.stmts[0].expr.args[0].kind, "float")


if __name__ == "__main__":
    unittest.main()
