import unittest

from bork.errors import BorkError
from bork.lexer import tokenize


def kinds(source):
    return [t.kind for t in tokenize(source)]


def values(source):
    return [t.value for t in tokenize(source) if t.kind in ("int", "float", "str", "ident")]


class TestLexer(unittest.TestCase):
    def test_numeric_forms(self):
        self.assertEqual(values("0xFF 1_000_000 3.5 1e3 2.5e-3 0.0"),
                         [255, 1000000, 3.5, 1000.0, 0.0025, 0.0])

    def test_comments_are_skipped_and_nest(self):
        self.assertEqual(kinds("1 // two\n /* 3 /* 4 */ 5 */ 6"), ["int", "int", "eof"])

    def test_a_block_comment_can_span_lines(self):
        self.assertEqual(kinds("1 /* a\nb\nc */ 2"), ["int", "int", "eof"])

    def test_a_block_comment_does_not_end_early(self):
        # The inner */ closes the inner comment, not the outer one.
        self.assertEqual(kinds("/* /* */ 1 */ 2"), ["int", "eof"])

    def test_division_is_still_division(self):
        self.assertEqual(kinds("4 / 2"), ["int", "/", "int", "eof"])

    def test_unterminated_block_comment_reports(self):
        with self.assertRaises(BorkError) as ctx:
            tokenize("1 /* never closed")
        self.assertIn("unterminated block comment", ctx.exception.diagnostics[0].message)

    def test_range_is_not_a_float(self):
        self.assertEqual(kinds("1..5"), ["int", "..", "int", "eof"])
        self.assertEqual(values("1..5"), [1, 5])

    def test_a_float_is_still_a_float(self):
        self.assertEqual(kinds("1.5"), ["float", "eof"])

    def test_string_escapes(self):
        self.assertEqual(values(r'"a\nb\t\"c\\"'), ['a\nb\t"c\\'])

    def test_strings_are_their_own_token_kind(self):
        self.assertEqual(kinds('"a" + "b"'), ["str", "+", "str", "eof"])

    def test_operators_are_longest_match(self):
        self.assertEqual(kinds("== <= < >= >"), ["==", "<=", "<", ">=", ">", "eof"])
        self.assertEqual(kinds("!= !"), ["!=", "!", "eof"])

    def test_keywords_versus_identifiers(self):
        self.assertEqual(kinds("true false truthy"), ["true", "false", "ident", "eof"])
        self.assertEqual(kinds("let letter var"), ["let", "ident", "var", "eof"])

    def test_type_names_stay_identifiers(self):
        # `int`/`float` are ordinary names so they can also be builtin calls.
        self.assertEqual(kinds("int float bool"), ["ident", "ident", "ident", "eof"])

    def test_bool_keywords_carry_their_value(self):
        self.assertEqual([t.value for t in tokenize("true false")][:2], [True, False])

    def test_a_zero_at_end_of_input_is_not_a_hex_prefix(self):
        # `"" in "xX"` is True, so peeking past the end used to look like 0x.
        self.assertEqual(kinds("0"), ["int", "eof"])
        self.assertEqual(values("1 % 0"), [1, 0])

    def test_single_integer(self):
        self.assertEqual(kinds("42"), ["int", "eof"])
        self.assertEqual(values("42"), [42])

    def test_lexing_continues_after_a_bad_character(self):
        # The error is recorded but the stream is still produced, so one run
        # can report more than the first problem.
        with self.assertRaises(BorkError) as ctx:
            tokenize("1 $ 2 $ 3")
        self.assertEqual(len(ctx.exception.diagnostics), 2)

    def test_multi_digit_integers(self):
        self.assertEqual(values("1 23 456"), [1, 23, 456])

    def test_arithmetic_operators(self):
        self.assertEqual(kinds("1 + 2 - 3 * 4 / 5 % 6"),
                         ["int", "+", "int", "-", "int", "*", "int", "/", "int", "%", "int", "eof"])

    def test_parentheses(self):
        self.assertEqual(kinds("(1 + 2)"), ["(", "int", "+", "int", ")", "eof"])

    def test_tokens_need_no_separating_whitespace(self):
        self.assertEqual(kinds("1+2"), ["int", "+", "int", "eof"])

    def test_whitespace_and_newlines_are_skipped(self):
        self.assertEqual(kinds("  1\n\t+\r\n 2  "), ["int", "+", "int", "eof"])

    def test_line_comments_are_skipped(self):
        self.assertEqual(kinds("1 // ignored + 9\n + 2"), ["int", "+", "int", "eof"])

    def test_comment_at_end_of_file(self):
        self.assertEqual(kinds("1 // trailing"), ["int", "eof"])

    def test_spans_track_line_and_column(self):
        tokens = tokenize("1 +\n  234")
        self.assertEqual((tokens[0].span.line, tokens[0].span.col), (1, 1))
        self.assertEqual((tokens[1].span.line, tokens[1].span.col), (1, 3))
        self.assertEqual((tokens[2].span.line, tokens[2].span.col), (2, 3))

    def test_span_length_covers_the_whole_token(self):
        self.assertEqual(tokenize("234")[0].span.length, 3)

    def test_empty_source_is_just_eof(self):
        self.assertEqual(kinds(""), ["eof"])
        self.assertEqual(kinds("   // nothing here\n"), ["eof"])

    def test_unexpected_character_is_an_error(self):
        with self.assertRaises(BorkError):
            tokenize("1 $ 2")

    def test_error_reports_its_position(self):
        try:
            tokenize("1 +\n  ?")
        except BorkError as exc:
            span = exc.diagnostics[0].span
            self.assertEqual((span.line, span.col), (2, 3))
            self.assertIn("unexpected character", exc.render())
        else:
            self.fail("expected a BorkError")


if __name__ == "__main__":
    unittest.main()
