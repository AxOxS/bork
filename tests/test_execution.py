import unittest

from helpers import (compile_errors, constants_of, expr_output, opcodes_of, run,
                     runtime_error)
from lumen.opcodes import Op
from lumen.values import MAX_I64, MIN_I64


class TestArithmetic(unittest.TestCase):
    def test_the_four_operators(self):
        self.assertEqual(expr_output("1 + 2"), "3")
        self.assertEqual(expr_output("7 - 3"), "4")
        self.assertEqual(expr_output("6 * 7"), "42")
        self.assertEqual(expr_output("9 / 3"), "3")

    def test_precedence_and_associativity_at_runtime(self):
        self.assertEqual(expr_output("1 + 2 * 3"), "7")
        self.assertEqual(expr_output("(1 + 2) * 3"), "9")
        self.assertEqual(expr_output("10 - 2 - 3"), "5")

    def test_integer_division_truncates_toward_zero(self):
        self.assertEqual(expr_output("-7 / 2"), "-3")
        self.assertEqual(expr_output("7 / -2"), "-3")

    def test_remainder_follows_the_dividend(self):
        self.assertEqual(expr_output("-7 % 2"), "-1")
        self.assertEqual(expr_output("7 % -2"), "1")

    def test_int_arithmetic_wraps_at_64_bits(self):
        self.assertEqual(expr_output(f"{MAX_I64} + 1"), str(MIN_I64))

    def test_division_by_zero_traps(self):
        self.assertEqual(runtime_error("var z = 0; print(1 / z);"), "integer division by zero")

    def test_float_arithmetic(self):
        self.assertEqual(expr_output("1.5 + 2.5"), "4.0")
        self.assertEqual(expr_output("7.0 / 2.0"), "3.5")

    def test_float_division_is_ieee(self):
        self.assertEqual(expr_output("1.0 / 0.0"), "inf")
        self.assertEqual(expr_output("-1.0 / 0.0"), "-inf")
        self.assertEqual(expr_output("0.0 / 0.0"), "nan")

    def test_comparisons(self):
        self.assertEqual(expr_output("1 < 2"), "true")
        self.assertEqual(expr_output("2 <= 2"), "true")
        self.assertEqual(expr_output("3 > 4"), "false")
        self.assertEqual(expr_output("1 == 1"), "true")
        self.assertEqual(expr_output("!(1 == 2)"), "true")


class TestVariables(unittest.TestCase):
    def test_let_binds_a_value(self):
        self.assertEqual(run("let x = 41; print(x + 1);"), "42\n")

    def test_type_annotation_is_honoured(self):
        self.assertEqual(run("let x: float = 1.5; print(x);"), "1.5\n")

    def test_var_can_be_reassigned(self):
        self.assertEqual(run("var x = 1; x = 2; print(x);"), "2\n")

    def test_let_cannot_be_reassigned(self):
        self.assertIn("not mutable", compile_errors("let x = 1; x = 2;")[0])

    def test_assignment_type_is_checked(self):
        self.assertIn("cannot assign", compile_errors("var x = 1; x = 1.5;")[0])

    def test_unknown_name_is_an_error(self):
        self.assertIn("unknown name 'y'", compile_errors("print(y);")[0])

    def test_top_level_bindings_are_globals(self):
        self.assertIn(Op.STORE_GLOBAL, opcodes_of("let x = 1;"))
        self.assertNotIn(Op.STORE_LOCAL, opcodes_of("let x = 1;"))

    def test_block_bindings_are_locals(self):
        self.assertIn(Op.STORE_LOCAL, opcodes_of("{ let x = 1; }"))

    def test_a_block_opens_a_scope(self):
        self.assertEqual(run("let x = 1; { let x = 2; print(x); } print(x);"), "2\n1\n")

    def test_redeclaration_in_the_same_scope_is_rejected(self):
        self.assertIn("already declared", compile_errors("let x = 1; let x = 2;")[0])

    def test_statements_run_in_order(self):
        self.assertEqual(run("var n = 1; print(n); n = n + 1; print(n);"), "1\n2\n")

    def test_binding_unit_is_rejected(self):
        self.assertIn("`unit`", compile_errors("let x = print(1);")[0])


class TestControlFlow(unittest.TestCase):
    def test_if_without_else(self):
        self.assertEqual(run('if 1 < 2 { print(1); }\nif 2 < 1 { print(2); }'), "1\n")

    def test_if_else(self):
        self.assertEqual(run('if false { print(1); } else { print(2); }'), "2\n")

    def test_else_if_chain(self):
        source = """
        var n = 85;
        if n >= 90 { print(1); } else if n >= 80 { print(2); } else { print(3); }
        """
        self.assertEqual(run(source), "2\n")

    def test_nested_ifs(self):
        source = "var a = 1; var b = 2; if a == 1 { if b == 2 { print(12); } else { print(10); } }"
        self.assertEqual(run(source), "12\n")

    def test_branches_have_their_own_scope(self):
        self.assertEqual(run("let x = 1; if true { let x = 2; print(x); } print(x);"), "2\n1\n")

    def test_condition_must_be_bool(self):
        self.assertIn("must be `bool`", compile_errors("if 1 { }")[0])

    def test_only_the_taken_branch_runs(self):
        source = "var log = 0; if false { log = 1; } else { log = 2; } print(log);"
        self.assertEqual(run(source), "2\n")


class TestLoops(unittest.TestCase):
    def test_while_counts(self):
        self.assertEqual(run("var i = 0; while i < 3 { print(i); i = i + 1; }"), "0\n1\n2\n")

    def test_while_with_a_false_condition_never_runs(self):
        self.assertEqual(run('while false { print(1); } print(2);'), "2\n")

    def test_break_leaves_the_loop(self):
        source = "var i = 0; while true { if i == 2 { break; } print(i); i = i + 1; } print(9);"
        self.assertEqual(run(source), "0\n1\n9\n")

    def test_continue_returns_to_the_condition(self):
        source = """
        var i = 0; var sum = 0;
        while i < 6 {
            i = i + 1;
            if i % 2 == 0 { continue; }
            sum = sum + i;
        }
        print(sum);
        """
        self.assertEqual(run(source), "9\n")

    def test_break_targets_the_innermost_loop(self):
        source = """
        var i = 0; var count = 0;
        while i < 3 {
            var j = 0;
            while j < 3 { if j == 1 { break; } count = count + 1; j = j + 1; }
            i = i + 1;
        }
        print(count);
        """
        self.assertEqual(run(source), "3\n")

    def test_break_outside_a_loop_is_rejected(self):
        self.assertIn("outside of a loop", compile_errors("break;")[0])
        self.assertIn("outside of a loop", compile_errors("continue;")[0])

    def test_break_inside_an_if_inside_a_loop_is_fine(self):
        self.assertEqual(run("while true { if true { break; } } print(1);"), "1\n")

    def test_while_condition_must_be_bool(self):
        self.assertIn("must be `bool`", compile_errors("while 1 { }")[0])


class TestBuiltins(unittest.TestCase):
    def test_print_writes_a_line(self):
        self.assertEqual(run("print(1); print(2);"), "1\n2\n")

    def test_print_formats_by_type(self):
        self.assertEqual(run("print(true); print(1.0); print(7);"), "true\n1.0\n7\n")

    def test_wrong_arity_is_rejected(self):
        self.assertIn("expects 1 argument", compile_errors("print(1, 2);")[0])

    def test_builtins_are_not_values(self):
        self.assertIn("only be called", compile_errors("let f = print;")[0])

    def test_calling_a_non_function_is_rejected(self):
        self.assertIn("cannot call", compile_errors("let x = 1; x();")[0])


class TestCodegen(unittest.TestCase):
    def test_operators_lower_to_the_opcode_for_their_type(self):
        self.assertIn(Op.ADD_INT, opcodes_of("print(1 + 2);"))
        self.assertIn(Op.ADD_FLOAT, opcodes_of("print(1.0 + 2.0);"))

    def test_negation_picks_the_typed_opcode(self):
        self.assertIn(Op.NEG_INT, opcodes_of("print(-(1 + 2));"))
        self.assertIn(Op.NEG_FLOAT, opcodes_of("print(-(1.0 + 2.0));"))

    def test_builtins_lower_to_call_native(self):
        self.assertIn(Op.CALL_NATIVE, opcodes_of("print(1);"))

    def test_expression_statements_pop_their_value(self):
        self.assertIn(Op.POP, opcodes_of("print(1);"))

    def test_constants_are_deduplicated(self):
        self.assertEqual(constants_of("print(7); print(7); print(7);"), [7])

    def test_int_and_float_constants_do_not_collide(self):
        # Python considers 1 == 1.0; the constant pool must not merge them.
        self.assertEqual(constants_of("print(1); print(1.0);"), [1, 1.0])

    def test_booleans_have_dedicated_opcodes(self):
        self.assertEqual(constants_of("print(true);"), [])
        self.assertIn(Op.TRUE, opcodes_of("print(true);"))

    def test_jumps_are_back_patched_to_a_real_target(self):
        from lumen.bytecode import decode
        from lumen.opcodes import JUMPS
        from helpers import entry_of
        fn = entry_of("if true { print(1); } else { print(2); }")
        offset = 0
        while offset < len(fn.code):
            op, operands, offset = decode(fn.code, offset)
            if op in JUMPS:
                target = offset + operands[0]
                self.assertTrue(0 <= target <= len(fn.code),
                                f"jump to {target} outside 0..{len(fn.code)}")

    def test_if_without_else_emits_one_jump(self):
        self.assertEqual(opcodes_of("if true { print(1); }").count(Op.JUMP), 0)
        self.assertEqual(opcodes_of("if true { print(1); }").count(Op.JUMP_IF_FALSE), 1)

    def test_if_else_emits_both_jumps(self):
        ops = opcodes_of("if true { print(1); } else { print(2); }")
        self.assertEqual(ops.count(Op.JUMP_IF_FALSE), 1)
        self.assertEqual(ops.count(Op.JUMP), 1)

    def test_a_loop_emits_a_backward_jump(self):
        from lumen.bytecode import decode
        from helpers import entry_of
        fn = entry_of("var i = 0; while i < 3 { i = i + 1; }")
        offset, backward = 0, 0
        while offset < len(fn.code):
            op, operands, offset = decode(fn.code, offset)
            if op == Op.JUMP and operands[0] < 0:
                backward += 1
        self.assertEqual(backward, 1)

    def test_every_program_ends_in_halt(self):
        self.assertEqual(opcodes_of("print(1);")[-1], Op.HALT)


if __name__ == "__main__":
    unittest.main()
