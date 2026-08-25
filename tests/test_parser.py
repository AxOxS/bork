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

    def test_span_covers_the_whole_expression(self):
        expr = parse("1 + 2").expr
        self.assertEqual((expr.span.col, expr.span.length), (1, 5))

    def test_missing_closing_paren(self):
        with self.assertRaises(LumenError) as ctx:
            parse("(1 + 2")
        self.assertIn("expected ')'", ctx.exception.message)

    def test_missing_operand(self):
        with self.assertRaises(LumenError) as ctx:
            parse("1 +")
        self.assertIn("expected an expression", ctx.exception.message)

    def test_trailing_tokens_are_rejected(self):
        with self.assertRaises(LumenError) as ctx:
            parse("1 2")
        self.assertIn("after the expression", ctx.exception.message)

    def test_dump_renders_a_tree(self):
        text = A.dump(parse("1 + 2").expr)
        self.assertIn("Binary", text)
        self.assertIn("IntLit", text)


if __name__ == "__main__":
    unittest.main()
