import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumen.errors import LumenError          # noqa: E402
from lumen.lexer import tokenize             # noqa: E402


def kinds(source):
    return [t.kind for t in tokenize(source)]


def values(source):
    return [t.value for t in tokenize(source) if t.kind == "int"]


class TestLexer(unittest.TestCase):
    def test_single_integer(self):
        self.assertEqual(kinds("42"), ["int", "eof"])
        self.assertEqual(values("42"), [42])

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
        with self.assertRaises(LumenError):
            tokenize("1 $ 2")

    def test_error_reports_its_position(self):
        try:
            tokenize("1 +\n  ?")
        except LumenError as exc:
            span = exc.diagnostics[0].span
            self.assertEqual((span.line, span.col), (2, 3))
            self.assertIn("unexpected character", exc.render())
        else:
            self.fail("expected a LumenError")


if __name__ == "__main__":
    unittest.main()
