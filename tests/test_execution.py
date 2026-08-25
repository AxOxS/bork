import unittest

from helpers import (compile_errors, constants_of, expr_output, opcodes_of, run,
                     run_main, runtime_error)
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


class TestLogicalOperators(unittest.TestCase):
    def test_truth_tables(self):
        self.assertEqual(expr_output("true && true"), "true")
        self.assertEqual(expr_output("true && false"), "false")
        self.assertEqual(expr_output("false || true"), "true")
        self.assertEqual(expr_output("false || false"), "false")

    def test_and_short_circuits(self):
        # If && evaluated both sides this would divide by zero.
        source = 'var z = 0; if z != 0 && 10 / z > 1 { print(1); } print(2);'
        self.assertEqual(run(source), "2\n")

    def test_or_short_circuits(self):
        self.assertEqual(run('var z = 0; if z == 0 || 10 / z > 1 { print(1); }'), "1\n")

    def test_and_binds_tighter_than_or(self):
        self.assertEqual(expr_output("true || false && false"), "true")

    def test_comparisons_bind_tighter_than_both(self):
        self.assertEqual(expr_output("1 < 2 && 3 > 2"), "true")

    def test_operands_must_be_bool(self):
        self.assertIn("expects `bool`", compile_errors("print(1 && true);")[0])

    def test_chained_operators(self):
        self.assertEqual(expr_output("true && true && false"), "false")
        self.assertEqual(expr_output("false || false || true"), "true")


class TestStrings(unittest.TestCase):
    def test_literals_and_concatenation(self):
        self.assertEqual(run('print("ab" + "cd");'), "abcd\n")

    def test_escapes(self):
        self.assertEqual(run(r'print("a\tb\nc");'), "a\tb\nc\n")
        self.assertEqual(run(r'print("q\"q\\");'), 'q"q\\\n')

    def test_str_converts_any_value(self):
        self.assertEqual(expr_output('str(1) + " " + str(1.5) + " " + str(true)'), "1 1.5 true")

    def test_concatenation_needs_two_strings(self):
        self.assertIn("cannot apply `+`", compile_errors('print("n=" + 1);')[0])

    def test_the_error_suggests_str(self):
        from lumen import compile_source
        from lumen.errors import LumenError
        try:
            compile_source('print("n=" + 1);', "<test>")
        except LumenError as exc:
            self.assertIn("str(x)", exc.diagnostics[0].note or "")
        else:
            self.fail("expected a compile error")

    def test_strings_compare_lexicographically(self):
        self.assertEqual(expr_output('"a" < "b"'), "true")
        self.assertEqual(expr_output('"abc" == "abc"'), "true")

    def test_unterminated_string(self):
        self.assertIn("unterminated string", compile_errors('print("oops);')[0])

    def test_unknown_escape(self):
        self.assertIn("unknown escape", compile_errors(r'print("a\q");')[0])

    def test_a_string_spanning_a_newline_is_rejected(self):
        self.assertIn("unterminated string", compile_errors('print("a\nb");')[0])


class TestArrays(unittest.TestCase):
    def test_literal_indexing_and_length(self):
        self.assertEqual(run("let xs = [10, 20, 30]; print(xs[1]); print(len(xs));"), "20\n3\n")

    def test_element_assignment(self):
        self.assertEqual(run("var xs = [1, 2]; xs[0] = 9; print(xs);"), "[9, 2]\n")

    def test_printing_an_array_quotes_nested_strings(self):
        self.assertEqual(run('print(["a", "b"]);'), '["a", "b"]\n')

    def test_nested_arrays(self):
        self.assertEqual(run("var g = [[1, 2], [3, 4]]; g[1][0] = 9; print(g);"),
                         "[[1, 2], [9, 4]]\n")

    def test_arrays_are_references(self):
        source = """
        fn fill(xs: [int]) { xs[0] = 99; }
        var xs = [1, 2]; fill(xs); print(xs);
        """
        self.assertEqual(run(source), "[99, 2]\n")

    def test_push_and_pop(self):
        source = """
        var xs: [str] = [];
        push(xs, "a"); push(xs, "b");
        let last = pop(xs);
        print(last + " " + str(xs) + " " + str(len(xs)));
        """
        self.assertEqual(run(source), 'b ["a"] 1\n')

    def test_pop_from_empty_traps(self):
        self.assertEqual(runtime_error("var xs: [int] = []; pop(xs);"), "pop from empty array")

    def test_out_of_bounds_read_and_write(self):
        self.assertIn("out of bounds", runtime_error("let xs = [1]; print(xs[3]);"))
        self.assertIn("out of bounds", runtime_error("var xs = [1]; xs[-1] = 0;"))

    def test_empty_literal_needs_an_annotation(self):
        self.assertIn("cannot infer the element type", compile_errors("let xs = [];")[0])
        self.assertEqual(run("let xs: [int] = []; print(len(xs));"), "0\n")

    def test_elements_must_share_a_type(self):
        self.assertIn("same type", compile_errors('let xs = [1, "a"];')[0])

    def test_index_must_be_an_int(self):
        self.assertIn("must be `int`", compile_errors('let xs = [1]; print(xs["a"]);')[0])

    def test_indexing_a_non_container(self):
        self.assertIn("cannot index", compile_errors("let n = 1; print(n[0]);")[0])

    def test_array_equality_is_not_defined(self):
        self.assertIn("not defined for `[int]`",
                      compile_errors("let a = [1]; let b = [2]; print(a == b);")[0])

    def test_arrays_of_arrays_have_a_type(self):
        self.assertIn("`[[int]]`", compile_errors("let g: [[int]] = [[1]]; let n: int = g;")[0])

    def test_strings_index_to_single_characters(self):
        self.assertEqual(run('let s = "abc"; print(s[0] + s[2]);'), "ac\n")

    def test_strings_cannot_be_assigned_through(self):
        self.assertIn("strings are immutable", compile_errors('var s = "ab"; s[0] = "c";')[0])


class TestFunctions(unittest.TestCase):
    def test_call_with_arguments_and_a_return_value(self):
        self.assertEqual(run("fn add(a: int, b: int) -> int { return a + b; }\n"
                             "print(add(2, 3));"), "5\n")

    def test_unit_function_falls_off_the_end(self):
        self.assertEqual(run('fn greet() { print(1); }\ngreet();'), "1\n")

    def test_early_return_without_a_value(self):
        source = """
        fn maybe(n: int) { if n < 0 { return; } print(n); }
        maybe(-1); maybe(7);
        """
        self.assertEqual(run(source), "7\n")

    def test_recursion(self):
        source = """
        fn fib(n: int) -> int { if n < 2 { return n; } return fib(n - 1) + fib(n - 2); }
        print(fib(15));
        """
        self.assertEqual(run(source), "610\n")

    def test_forward_references(self):
        self.assertEqual(run("fn a() -> int { return b() + 1; }\n"
                             "fn b() -> int { return 1; }\nprint(a());"), "2\n")

    def test_mutual_recursion(self):
        source = """
        fn is_even(n: int) -> bool { if n == 0 { return true; } return is_odd(n - 1); }
        fn is_odd(n: int) -> bool { if n == 0 { return false; } return is_even(n - 1); }
        print(is_even(10));
        """
        self.assertEqual(run(source), "true\n")

    def test_deep_recursion_does_not_hit_the_host_stack(self):
        # 5000 frames would overflow CPython's default recursion limit if the
        # interpreter recursed; the VM loop is iterative, so it must not.
        source = """
        fn count(n: int) -> int { if n == 0 { return 0; } return 1 + count(n - 1); }
        print(count(5000));
        """
        self.assertEqual(run(source), "5000\n")

    def test_stack_overflow_is_a_clean_trap(self):
        self.assertIn("call stack overflow",
                      runtime_error("fn f(n: int) -> int { return f(n + 1); }\nf(0);"))

    def test_locals_are_per_frame(self):
        source = """
        fn work(n: int) -> int { var local = n * 2; if n > 0 { local = local + work(n - 1); } return local; }
        print(work(3));
        """
        self.assertEqual(run(source), "12\n")

    def test_functions_are_values(self):
        source = """
        fn double(x: int) -> int { return x * 2; }
        fn apply(f: fn(int) -> int, v: int) -> int { return f(v); }
        print(apply(double, 21));
        """
        self.assertEqual(run(source), "42\n")

    def test_arguments_are_evaluated_left_to_right(self):
        source = """
        var log = 0;
        fn side(tag: int) -> int { log = log * 10 + tag; return 0; }
        fn two(a: int, b: int) { }
        two(side(1), side(2));
        print(log);
        """
        self.assertEqual(run(source), "12\n")

    def test_globals_are_shared_across_functions(self):
        source = """
        var hits = 0;
        fn touch() { hits = hits + 1; }
        touch(); touch(); print(hits);
        """
        self.assertEqual(run(source), "2\n")

    def test_main_runs_after_the_top_level(self):
        self.assertEqual(run('print(1);\nfn main() { print(2); }'), "1\n2\n")

    def test_a_program_without_main_runs_the_top_level_only(self):
        self.assertEqual(run("print(1);"), "1\n")

    def test_main_signature_is_checked(self):
        self.assertIn("must take no parameters", compile_errors("fn main(a: int) {}")[0])
        self.assertIn("must not return a value", compile_errors("fn main() -> int { return 1; }")[0])

    def test_arity_and_argument_types(self):
        self.assertIn("expects 1 argument", compile_errors("fn f(a: int) {}\nf(1, 2);")[0])
        self.assertIn("argument 1", compile_errors("fn f(a: int) {}\nf(true);")[0])

    def test_return_type_is_enforced(self):
        self.assertIn("expected return type `int`",
                      compile_errors("fn f() -> int { return true; }")[0])
        self.assertIn("returns nothing", compile_errors("fn f() { return 1; }")[0])

    def test_return_outside_a_function(self):
        self.assertIn("outside of a function", compile_errors("return 1;")[0])

    def test_nested_functions_are_rejected(self):
        self.assertIn("top level", compile_errors("fn outer() { fn inner() {} }")[0])

    def test_builtins_cannot_be_shadowed(self):
        self.assertIn("shadows the built-in", compile_errors("fn print(x: int) {}")[0])

    def test_functions_cannot_be_assigned_to(self):
        self.assertIn("cannot assign to function", compile_errors("fn f() {}\nf = f;")[0])

    def test_duplicate_function_names(self):
        self.assertIn("already declared", compile_errors("fn f() {}\nfn f() {}")[0])

    def test_run_main_helper(self):
        self.assertEqual(run_main("    print(1);"), "1\n")


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

    def test_short_circuit_uses_the_or_pop_jumps(self):
        self.assertIn(Op.JUMP_IF_FALSE_OR_POP, opcodes_of("var a = true; print(a && a);"))
        self.assertIn(Op.JUMP_IF_TRUE_OR_POP, opcodes_of("var a = true; print(a || a);"))

    def test_calls_lower_to_call(self):
        self.assertIn(Op.CALL, opcodes_of("fn f() {}\nf();"))
        self.assertIn(Op.RET, opcodes_of("fn f() {}\nf();", "f"))

    def test_every_function_is_compiled_separately(self):
        from helpers import program_of
        program = program_of("fn a() {}\nfn b() {}\nprint(1);")
        self.assertEqual(sorted(f.name for f in program.functions), ["<main>", "a", "b"])

    def test_string_concatenation_uses_concat(self):
        self.assertIn(Op.CONCAT, opcodes_of('var a = "x"; print(a + a);'))

    def test_len_is_lowered_to_an_intrinsic(self):
        ops = opcodes_of("let xs = [1, 2]; print(len(xs));")
        self.assertIn(Op.LEN, ops)
        # It is the only builtin call in that program, so the remaining
        # CALL_NATIVE is print's.
        self.assertEqual(ops.count(Op.CALL_NATIVE), 1)

    def test_other_builtins_still_use_call_native(self):
        self.assertIn(Op.CALL_NATIVE, opcodes_of('print("x");'))

    def test_len_still_works_on_both_kinds(self):
        self.assertEqual(run('print(len([1, 2])); print(len("abc"));'), "2\n3\n")

    def test_len_still_type_checks(self):
        self.assertIn("expects an array or `str`", compile_errors("print(len(1));")[0])

    def test_array_literals_use_make_array(self):
        self.assertIn(Op.MAKE_ARRAY, opcodes_of("let xs = [1, 2];"))

    def test_indexing_uses_index_get_and_set(self):
        self.assertIn(Op.INDEX_GET, opcodes_of("let xs = [1]; print(xs[0]);"))
        self.assertIn(Op.INDEX_SET, opcodes_of("var xs = [1]; xs[0] = 2;"))

    def test_every_program_ends_in_halt(self):
        self.assertEqual(opcodes_of("print(1);")[-1], Op.HALT)


if __name__ == "__main__":
    unittest.main()
