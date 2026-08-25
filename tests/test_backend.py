import unittest

from lumen import compile_source
from lumen.bytecode import decode
from lumen.disasm import disassemble
from lumen.opcodes import Op, instruction_size


def entry_of(source):
    return compile_source(source, "<test>").program.entry


def text_of(source):
    return disassemble(compile_source(source, "<test>").program)


class TestLineTable(unittest.TestCase):
    def test_offsets_map_back_to_source_lines(self):
        source = "fn main() {\n    print(1);\n\n    print(2);\n}"
        fn = next(f for f in compile_source(source, "<test>").program.functions
                  if f.name == "main")
        self.assertEqual(fn.line_for(0), 2)
        self.assertEqual(fn.line_for(len(fn.code) - 3), 4)

    def test_the_table_only_records_changes(self):
        fn = entry_of("print(1); print(2); print(3);")
        self.assertEqual(len(fn.lines), 1)      # all on one line

    def test_a_traceback_names_every_frame(self):
        from lumen.errors import LumenRuntimeError
        from lumen.vm import VM
        source = ("fn inner(n: int) -> int { return 1 / n; }\n"
                  "fn outer() -> int { return inner(0); }\n"
                  "fn main() { print(outer()); }\n")
        try:
            VM(compile_source(source, "prog.lm").program).run()
        except LumenRuntimeError as exc:
            text = exc.render()
        else:
            self.fail("expected a runtime error")
        self.assertIn("division by zero", text)
        self.assertIn("at inner (prog.lm:1)", text)
        self.assertIn("at outer (prog.lm:2)", text)
        self.assertIn("at main (prog.lm:3)", text)

    def test_a_deep_traceback_is_abbreviated(self):
        from lumen.errors import LumenRuntimeError
        from lumen.vm import VM
        source = ("fn down(n: int) -> int { if n == 0 { return 1 / n; } return down(n - 1); }\n"
                  "fn main() { print(down(100)); }\n")
        try:
            VM(compile_source(source, "deep.lm").program).run()
        except LumenRuntimeError as exc:
            self.assertIn("frames omitted", exc.render())
            self.assertLess(len(exc.traceback_lines), 20)
        else:
            self.fail("expected a runtime error")


class TestDisassembler(unittest.TestCase):
    def test_one_line_per_instruction(self):
        fn = entry_of("print(1 + 2 * 3);")
        body = [line for line in text_of("print(1 + 2 * 3);").splitlines()
                if line.startswith("  ") and not line.startswith("  ;")]
        count = 0
        offset = 0
        while offset < len(fn.code):
            _, _, offset = decode(fn.code, offset)
            count += 1
        self.assertEqual(len(body), count)

    def test_constants_are_annotated_with_their_value(self):
        text = text_of("print(41 + 1);")
        self.assertIn("CONST", text)
        self.assertIn("; 41", text)

    def test_every_opcode_is_named(self):
        text = text_of("print(-(1 + 2 * 3 - 4 / 5 % 6));")
        for name in ("ADD_INT", "SUB_INT", "MUL_INT", "DIV_INT", "MOD_INT", "NEG_INT", "HALT"):
            self.assertIn(name, text)

    def test_float_opcodes_are_named_too(self):
        text = text_of("print(-(1.0 + 2.0 * 3.0 - 4.0 / 5.0 % 6.0));")
        for name in ("ADD_FLOAT", "SUB_FLOAT", "MUL_FLOAT", "DIV_FLOAT", "MOD_FLOAT", "NEG_FLOAT"):
            self.assertIn(name, text)

    def test_offsets_advance_by_the_instruction_size(self):
        fn = entry_of("print(1 + 2);")
        offset = 0
        while offset < len(fn.code):
            op, _, next_offset = decode(fn.code, offset)
            self.assertEqual(next_offset - offset, instruction_size(op))
            offset = next_offset

    def test_header_reports_the_code_size(self):
        fn = entry_of("print(1);")
        self.assertIn(f"{len(fn.code)} bytes", text_of("print(1);"))

    def test_globals_are_annotated_with_their_name(self):
        self.assertIn("; total", text_of("let total = 1; print(total);"))

    def test_native_calls_name_the_builtin(self):
        self.assertIn("; print", text_of("print(1);"))

    def test_the_entry_function_is_marked(self):
        self.assertIn("[entry]", text_of("print(1);"))

    def test_source_lines_are_shown(self):
        text = text_of("print(1);\nprint(2);")
        self.assertIn("   1 ", text)
        self.assertIn("   2 ", text)

    def test_jump_targets_are_resolved(self):
        self.assertIn("-> ", text_of("if true { print(1); } else { print(2); }"))


if __name__ == "__main__":
    unittest.main()
