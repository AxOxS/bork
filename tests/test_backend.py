import unittest

from helpers import run
from lumen import compile_source
from lumen.bytecode import decode
from lumen.disasm import disassemble
from lumen.opcodes import Op, instruction_size


def entry_of(source):
    return compile_source(source, "<test>").program.entry


def text_of(source, optimise=True):
    return disassemble(compile_source(source, "<test>", optimise=optimise).program)


def constants_of(source, fn_name="<main>", optimise=True):
    program = compile_source(source, "<test>", optimise=optimise).program
    return next(f for f in program.functions if f.name == fn_name).consts


def opcodes_of(source, fn_name="<main>", optimise=True):
    program = compile_source(source, "<test>", optimise=optimise).program
    fn = next(f for f in program.functions if f.name == fn_name)
    ops, offset = [], 0
    while offset < len(fn.code):
        op, _, offset = decode(fn.code, offset)
        ops.append(op)
    return ops


class TestOptimiser(unittest.TestCase):
    def test_arithmetic_is_folded(self):
        self.assertEqual(constants_of("let x = 2 * 3 + 4;"), [10])
        self.assertNotIn(Op.MUL_INT, opcodes_of("let x = 2 * 3 + 4;"))

    def test_folding_uses_lumen_semantics_not_python(self):
        # Python's -7 // 2 is -4; Lumen truncates toward zero.
        self.assertEqual(constants_of("let x = -7 / 2;"), [-3])
        self.assertEqual(constants_of("let x = -7 % 2;"), [-1])

    def test_folding_wraps_at_64_bits(self):
        self.assertEqual(constants_of("let x = 9223372036854775807 + 1;"),
                         [-9223372036854775808])

    def test_division_by_zero_is_not_folded(self):
        # It must still trap at runtime rather than at compile time.
        self.assertIn(Op.DIV_INT, opcodes_of("let x = 1 / 0;"))
        self.assertIn(Op.MOD_INT, opcodes_of("let x = 1 % 0;"))

    def test_float_division_by_zero_is_not_folded(self):
        self.assertIn(Op.DIV_FLOAT, opcodes_of("let x = 1.0 / 0.0;"))

    def test_string_concatenation_is_folded(self):
        self.assertEqual(constants_of('let s = "a" + "b" + "c";'), ["abc"])

    def test_comparisons_are_folded(self):
        self.assertNotIn(Op.LT, opcodes_of("let b = 1 < 2;"))

    def test_unary_operators_are_folded(self):
        self.assertNotIn(Op.NOT, opcodes_of("let b = !true;"))

    def test_algebraic_identities(self):
        ops = opcodes_of("var n = 3; let a = n + 0; let b = n * 1; let c = n - 0; let d = n / 1;")
        self.assertNotIn(Op.ADD_INT, ops)
        self.assertNotIn(Op.MUL_INT, ops)
        self.assertNotIn(Op.SUB_INT, ops)
        self.assertNotIn(Op.DIV_INT, ops)

    def test_float_identities_are_not_applied(self):
        # x * 1.0 must stay: it normalises nothing, and x may be NaN.
        self.assertIn(Op.MUL_FLOAT, opcodes_of("var f = 1.5; let a = f * 1.0;"))

    def test_string_identities(self):
        self.assertNotIn(Op.CONCAT, opcodes_of('var s = "x"; let a = s + "";'))

    def test_short_circuit_with_a_constant_left_operand(self):
        self.assertNotIn(Op.JUMP_IF_FALSE_OR_POP,
                         opcodes_of("var b = true; let x = true && b;"))
        self.assertNotIn(Op.JUMP_IF_TRUE_OR_POP,
                         opcodes_of("var b = true; let x = false || b;"))

    def test_constant_branches_are_pruned(self):
        ops = opcodes_of('if false { print("dead"); } print("live");')
        self.assertNotIn(Op.JUMP_IF_FALSE, ops)
        self.assertEqual(constants_of('if false { print("dead"); } print("live");'), ["live"])

    def test_a_true_branch_keeps_only_the_then_arm(self):
        self.assertEqual(constants_of('if true { print("a"); } else { print("b"); }'), ["a"])

    def test_a_false_while_is_removed_entirely(self):
        ops = opcodes_of('while false { print("never"); } print("after");')
        self.assertNotIn(Op.JUMP, ops)
        self.assertEqual(constants_of('while false { print("never"); } print("after");'),
                         ["after"])

    def test_while_true_is_kept(self):
        # It is not dead -- it is an infinite loop, and break/return leave it.
        self.assertIn(Op.JUMP, opcodes_of("while true { break; }"))

    def test_dead_code_after_return_is_dropped(self):
        source = 'fn f() -> int { return 1; print("x"); }\nf();'
        result = compile_source(source, "<test>")
        self.assertGreater(result.optimizer.dead_stmts, 0)
        self.assertEqual(constants_of(source, "f"), [1])

    def test_dead_code_after_break_is_dropped(self):
        source = 'for i in 0..3 { break; print("x"); }'
        self.assertGreater(compile_source(source, "<test>").optimizer.dead_stmts, 0)

    def test_live_code_before_a_return_is_kept(self):
        source = 'fn f() -> int { print("kept"); return 1; }\nf();'
        self.assertIn("kept", constants_of(source, "f"))

    def test_counters_add_up(self):
        result = compile_source('fn f() -> int { return 1 + 1; print("x"); }\nf();', "<test>")
        opt = result.optimizer
        self.assertEqual(opt.total, opt.folds + opt.branches_pruned + opt.dead_stmts)
        self.assertGreater(opt.total, 0)

    def test_the_optimiser_never_changes_behaviour(self):
        program = """
        fn main() {
            print(str(2 * 3 + 1) + " " + str(-7 / 2) + " " + "a" + "b");
            if 1 < 2 { print("yes"); } else { print("no"); }
            while false { print("never"); }
            var n = 5;
            print(n * 1 + 0);
            for i in 0..3 { print(i * 2); }
        }
        """
        self.assertEqual(run(program, optimise=True), run(program, optimise=False))


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
        text = text_of("print(41 + 1);", optimise=False)
        self.assertIn("CONST", text)
        self.assertIn("; 41", text)

    def test_every_opcode_is_named(self):
        text = text_of("print(-(1 + 2 * 3 - 4 / 5 % 6));", optimise=False)
        for name in ("ADD_INT", "SUB_INT", "MUL_INT", "DIV_INT", "MOD_INT", "NEG_INT", "HALT"):
            self.assertIn(name, text)

    def test_float_opcodes_are_named_too(self):
        text = text_of("print(-(1.0 + 2.0 * 3.0 - 4.0 / 5.0 % 6.0));", optimise=False)
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

    def test_struct_layout_is_listed(self):
        text = text_of("struct P { x: int, y: str }\nlet p = P{x: 1, y: \"a\"};")
        self.assertIn("; struct P { x, y }", text)
        self.assertIn("MAKE_STRUCT", text)
        self.assertIn("; P", text)

    def test_source_lines_are_shown(self):
        text = text_of("print(1);\nprint(2);")
        self.assertIn("   1 ", text)
        self.assertIn("   2 ", text)

    def test_jump_targets_are_resolved(self):
        self.assertIn("-> ", text_of("var c = true; if c { print(1); } else { print(2); }"))


if __name__ == "__main__":
    unittest.main()
