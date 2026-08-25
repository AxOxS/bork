import unittest

from bork import ast_nodes as A
from bork.errors import BorkError
from bork.parser import parse


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
    if isinstance(node, A.Ident):
        return node.name
    if isinstance(node, A.Call):
        return "(call " + " ".join(shape(x) for x in [node.callee] + node.args) + ")"
    raise AssertionError(f"unexpected node {node!r}")


def first_expr(source):
    return parse(source).stmts[0].expr


def tree(source):
    return shape(first_expr(source + ";"))


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

    def test_calls_are_postfix(self):
        self.assertEqual(tree("f(1, 2)"), "(call f 1 2)")
        self.assertEqual(tree("f(1) + 2"), "(+ (call f 1) 2)")

    def test_statements_are_a_list(self):
        self.assertEqual(len(parse("let a = 1; let b = 2; print(a);").stmts), 3)

    def test_struct_literal_is_not_parsed_in_an_if_header(self):
        # `if flag { }` must not read `flag { ... }` as a struct literal.
        module = parse("var flag = true; if flag { flag = false; }")
        self.assertIsInstance(module.stmts[1].cond, A.Ident)

    def test_struct_literal_is_not_parsed_in_a_while_header(self):
        module = parse("var flag = true; while flag { flag = false; }")
        self.assertIsInstance(module.stmts[1].cond, A.Ident)

    def test_struct_literals_are_still_allowed_where_delimited(self):
        for source, index in [("f(P{a: 1});", 0), ("let x = [P{a: 1}];", 0),
                              ("let x = P{a: 1};", 0)]:
            with self.subTest(source=source):
                parse(source)      # must not raise
        # Parenthesising re-enables them inside a header.
        module = parse("if (P{a: 1}).a == 1 { }")
        self.assertIsInstance(module.stmts[0].cond, A.Binary)

    def test_the_guard_does_not_leak_out_of_a_header(self):
        # The body of the `if` is an ordinary statement position again.
        module = parse("if true { let p = P{a: 1}; }")
        self.assertIsInstance(module.stmts[0].then.stmts[0].init, A.StructLit)

    def test_blocks_nest(self):
        module = parse("{ { let x = 1; } }")
        self.assertIsInstance(module.stmts[0], A.Block)
        self.assertIsInstance(module.stmts[0].stmts[0], A.Block)

    def test_span_covers_the_whole_expression(self):
        expr = first_expr("1 + 2;")
        self.assertEqual((expr.span.col, expr.span.length), (1, 5))

    def test_missing_closing_paren(self):
        with self.assertRaises(BorkError) as ctx:
            parse("(1 + 2")
        self.assertIn("expected ')'", ctx.exception.diagnostics[0].message)

    def test_missing_operand(self):
        with self.assertRaises(BorkError) as ctx:
            parse("1 +")
        self.assertIn("expected an expression", ctx.exception.diagnostics[0].message)

    def test_recovery_reports_several_problems_in_one_run(self):
        with self.assertRaises(BorkError) as ctx:
            parse("let a = ; let b = ; let c = ;")
        self.assertGreaterEqual(len(ctx.exception.diagnostics), 3)

    def test_recovery_resumes_at_the_next_statement(self):
        with self.assertRaises(BorkError) as ctx:
            parse("let a = ;\nlet b = 2;\nlet c = ;")
        self.assertEqual(len(ctx.exception.diagnostics), 2)

    def test_recovery_works_inside_a_block(self):
        with self.assertRaises(BorkError) as ctx:
            parse("fn f() { let a = ; let b = ; }")
        self.assertGreaterEqual(len(ctx.exception.diagnostics), 2)

    def test_a_broken_function_does_not_swallow_the_next_one(self):
        with self.assertRaises(BorkError) as ctx:
            parse("fn a( { }\nfn b() { let x = ; }")
        self.assertGreaterEqual(len(ctx.exception.diagnostics), 2)

    def test_repeated_errors_on_one_token_are_collapsed(self):
        with self.assertRaises(BorkError) as ctx:
            parse("let a = ;")
        self.assertEqual(len(ctx.exception.diagnostics), 1)

    def test_expectations_are_described_in_words(self):
        with self.assertRaises(BorkError) as ctx:
            parse("fn 1() {}")
        self.assertIn("expected function name", ctx.exception.diagnostics[0].message)

    def test_missing_semicolon(self):
        with self.assertRaises(BorkError) as ctx:
            parse("let a = 1")
        self.assertIn("expected ';'", ctx.exception.diagnostics[0].message)

    def test_invalid_assignment_target(self):
        with self.assertRaises(BorkError) as ctx:
            parse("1 + 2 = 3;")
        self.assertIn("invalid assignment target", ctx.exception.diagnostics[0].message)

    def test_error_is_rendered_with_a_caret_under_the_span(self):
        try:
            parse("1 +\n  ?", "demo.bk")
        except BorkError as exc:
            text = exc.render()
        else:
            self.fail("expected a BorkError")
        self.assertIn("demo.bk:2:3", text)
        self.assertIn("  ?", text)          # the offending source line
        self.assertIn("  ^", text)          # a caret beneath it

    def test_caret_is_as_wide_as_the_span(self):
        try:
            parse("let x = 1 123;")
        except BorkError as exc:
            self.assertIn("^^^", exc.render())
        else:
            self.fail("expected a BorkError")

    def test_dump_renders_a_tree(self):
        text = A.dump(parse("1 + 2;"))
        self.assertIn("Binary", text)
        self.assertIn("IntLit", text)


if __name__ == "__main__":
    unittest.main()
