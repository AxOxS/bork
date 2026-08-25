import unittest

from lumen import compile_source
from lumen.bytecode import decode
from lumen.disasm import disassemble
from lumen.opcodes import Op, instruction_size


def entry_of(source):
    return compile_source(source, "<test>").program.entry


def text_of(source):
    return disassemble(compile_source(source, "<test>").program)


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

    def test_jump_targets_are_resolved(self):
        self.assertIn("-> ", text_of("if true { print(1); } else { print(2); }"))


if __name__ == "__main__":
    unittest.main()
