import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumen import ast_nodes as A            # noqa: E402
from lumen.errors import LumenError         # noqa: E402
from lumen.parser import parse              # noqa: E402


def shape(node):
    """Render a tree as an s-expression, so nesting is easy to assert on."""
    if isinstance(node, A.IntLit):
        return str(node.value)
    if isinstance(node, A.FloatLit):
        return repr(node.value)
    if isinstance(node, A.BoolLit):
        return "true" if node.value else "false"
    if isinstance(node, A.Unary):
        return f"({node.op} {shape(node.operand)})"
    if isinstance(node, A.Binary):
        return f"({node.op} {shape(node.left)} {shape(node.right)})"
    raise AssertionError(f"unexpected node {node!r}")


def tree(source):
    return shape(parse(source).expr)


class TestParser(unittest.TestCase):
    def test_single_literal(self):
        self.assertEqual(tree("42"), "42")

    def test_multiplication_binds_tighter_than_addition(self):
        self.assertEqual(tree("1 + 2 * 3"), "(+ 1 (* 2 3))")
        self.assertEqual(tree("1 * 2 + 3"), "(+ (* 1 2) 3)")

    def test_binary_operators_are_left_associative(self):
        self.assertEqual(tree("1 - 2 - 3"), "(- (- 1 2) 3)")
        self.assertEqual(tree("8 / 4 / 2"), "(/ (/ 8 4) 2)")

    def test_parentheses_override_precedence(self):
        self.assertEqual(tree("(1 + 2) * 3"), "(* (+ 1 2) 3)")

    def test_modulo_shares_precedence_with_multiplication(self):
        self.assertEqual(tree("1 + 7 % 3"), "(+ 1 (% 7 3))")

    def test_unary_minus_binds_tighter_than_binary(self):
        self.assertEqual(tree("-2 + 3"), "(+ -2 3)")
        self.assertEqual(tree("-2 * 3"), "(* -2 3)")

    def test_unary_minus_folds_into_a_literal(self):
        self.assertEqual(tree("-2"), "-2")
        self.assertEqual(tree("--2"), "2")

    def test_unary_minus_on_a_non_literal_stays_a_node(self):
        self.assertEqual(tree("-(2 + 3)"), "(- (+ 2 3))")

    def test_comparisons_bind_looser_than_arithmetic(self):
        self.assertEqual(tree("1 + 2 < 4"), "(< (+ 1 2) 4)")
        self.assertEqual(tree("1 < 2 == true"), "(== (< 1 2) true)")

    def test_equality_binds_loosest(self):
        self.assertEqual(tree("1 < 2 != 3 > 4"), "(!= (< 1 2) (> 3 4))")

    def test_not_is_a_unary_operator(self):
        self.assertEqual(tree("!true"), "(! true)")
        self.assertEqual(tree("!(1 == 2)"), "(! (== 1 2))")

    def test_float_literals(self):
        self.assertEqual(tree("1.5 + 2.0"), "(+ 1.5 2.0)")
        self.assertEqual(tree("-1.5"), "-1.5")

    def test_span_covers_the_whole_expression(self):
        expr = parse("1 + 2").expr
        self.assertEqual((expr.span.col, expr.span.length), (1, 5))

    def test_missing_closing_paren(self):
        with self.assertRaises(LumenError) as ctx:
            parse("(1 + 2")
        self.assertIn("expected ')'", ctx.exception.diagnostics[0].message)

    def test_missing_operand(self):
        with self.assertRaises(LumenError) as ctx:
            parse("1 +")
        self.assertIn("expected an expression", ctx.exception.diagnostics[0].message)

    def test_trailing_tokens_are_rejected(self):
        with self.assertRaises(LumenError) as ctx:
            parse("1 2")
        self.assertIn("after the expression", ctx.exception.diagnostics[0].message)

    def test_error_is_rendered_with_a_caret_under_the_span(self):
        try:
            parse("1 +\n  ?", "demo.lm")
        except LumenError as exc:
            text = exc.render()
        else:
            self.fail("expected a LumenError")
        self.assertIn("demo.lm:2:3", text)
        self.assertIn("  ?", text)          # the offending source line
        self.assertIn("  ^", text)          # a caret beneath it

    def test_caret_is_as_wide_as_the_span(self):
        try:
            parse("123 456")
        except LumenError as exc:
            self.assertIn("^^^", exc.render())
        else:
            self.fail("expected a LumenError")

    def test_dump_renders_a_tree(self):
        text = A.dump(parse("1 + 2").expr)
        self.assertIn("Binary", text)
        self.assertIn("IntLit", text)


if __name__ == "__main__":
    unittest.main()
