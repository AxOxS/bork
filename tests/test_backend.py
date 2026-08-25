import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumen import compile_source                    # noqa: E402
from lumen.bytecode import decode                   # noqa: E402
from lumen.disasm import disassemble                # noqa: E402
from lumen.opcodes import Op, instruction_size      # noqa: E402


class TestDisassembler(unittest.TestCase):
    def test_one_line_per_instruction(self):
        fn = compile_source("1 + 2 * 3")
        body = [line for line in disassemble(fn).splitlines()
                if line.startswith("  ") and not line.startswith("  ;")]
        count = 0
        offset = 0
        while offset < len(fn.code):
            _, _, offset = decode(fn.code, offset)
            count += 1
        self.assertEqual(len(body), count)

    def test_constants_are_annotated_with_their_value(self):
        text = disassemble(compile_source("41 + 1"))
        self.assertIn("CONST", text)
        self.assertIn("; 41", text)

    def test_every_opcode_is_named(self):
        text = disassemble(compile_source("-(1 + 2 * 3 - 4 / 5 % 6)"))
        for name in ("ADD_INT", "SUB_INT", "MUL_INT", "DIV_INT", "MOD_INT", "NEG_INT", "HALT"):
            self.assertIn(name, text)

    def test_float_opcodes_are_named_too(self):
        text = disassemble(compile_source("-(1.0 + 2.0 * 3.0 - 4.0 / 5.0 % 6.0)"))
        for name in ("ADD_FLOAT", "SUB_FLOAT", "MUL_FLOAT", "DIV_FLOAT", "MOD_FLOAT", "NEG_FLOAT"):
            self.assertIn(name, text)

    def test_offsets_advance_by_the_instruction_size(self):
        fn = compile_source("1 + 2")
        offset = 0
        while offset < len(fn.code):
            op, _, next_offset = decode(fn.code, offset)
            self.assertEqual(next_offset - offset, instruction_size(op))
            offset = next_offset

    def test_header_reports_the_code_size(self):
        fn = compile_source("1")
        self.assertIn(f"{len(fn.code)} bytes", disassemble(fn))


if __name__ == "__main__":
    unittest.main()
