"""Runs programs through both back ends and checks they print exactly the same thing."""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from helpers import run_native
from bork import compile_source
from bork.cbackend import c_float, c_int, c_string
from bork.errors import BorkRuntimeError
from bork.values import MAX_I64, MIN_I64
from bork.vm import VM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "examples")
HAVE_CC = shutil.which(os.environ.get("CC", "cc")) is not None


# Exit status, stdout and stderr, as `borkc run` would give them.
def run_vm(source: str, filename: str, optimise: bool = True):
    out = io.StringIO()
    try:
        VM(compile_source(source, filename, optimise).program, out=out).run()
    except BorkRuntimeError as exc:
        return 70, out.getvalue(), exc.render() + "\n"
    return 0, out.getvalue(), ""


@unittest.skipUnless(HAVE_CC, "no C compiler")
class Differential(unittest.TestCase):
    def assertSame(self, source: str, optimise: bool = True, filename: str = "prog.bk"):
        proc = run_native(source, optimise, filename)
        expected = run_vm(source, filename, optimise)
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), expected)
        return expected

    def assertSameMain(self, body: str, prelude: str = ""):
        return self.assertSame(prelude + "\nfn main() {\n" + body + "\n}\n")


class TestExamples(Differential):
    def test_every_example(self):
        for name in sorted(os.listdir(EXAMPLES)):
            if not name.endswith(".bk") or name in ("broken.bk", "fib.bk"):
                continue
            with self.subTest(example=name), open(os.path.join(EXAMPLES, name), encoding="utf-8") as f:
                self.assertSame(f.read(), filename=f"examples/{name}")

    def test_fib_apart_from_its_timings(self):
        with open(os.path.join(EXAMPLES, "fib.bk"), encoding="utf-8") as f:
            source = f.read()
        native = run_native(source).stdout.splitlines()
        _, vm, _ = run_vm(source, "<test>")
        vm = vm.splitlines()
        self.assertEqual(native[:2], vm[:2])
        self.assertEqual(native[3:], vm[3:])


class TestNumbers(Differential):
    def test_float_formatting(self):
        values = ["0.1 + 0.2", "1.0 / 3.0", "1e16", "1.5e16", "12345678901234567.0", "1e22",
                  "1e100", "1.5e-5", "0.0001", "0.00001", "123456.789", "-0.0", "0.0 - 0.0",
                  "-1.0 * 0.0", "1.0 / 0.0", "-1.0 / 0.0", "0.0 / 0.0", "5e-324", "1.7976931348623157e308",
                  "2.5", "-2.5", "100.0", "9999999999999998.0", "0.30000000000000004 * 3.0",
                  "float(" + str(MAX_I64) + ")", "float(-7)", "sqrt(2.0)", "sqrt(-0.0)"]
        self.assertSameMain("\n".join(f"    print({v});" for v in values))

    def test_integer_edges(self):
        low = f"(-{MAX_I64} - 1)"      # MIN_I64 itself does not lex as a literal
        cases = [f"{MAX_I64} + 1", f"{low} - 1", f"{low} / -1", f"{low} % -1",
                 f"-{low}", f"{MAX_I64} * 2", "-7 / 2", "7 / -2", "-7 % 2", "7 % -2",
                 f"abs({low})", "abs(-5)", "min(3, -4)", "max(3, -4)"]
        self.assertSameMain("    var z = 1;\n" + "\n".join(
            f"    print(z * ({c}));" for c in cases))

    def test_float_remainder_and_minmax_with_nan(self):
        self.assertSameMain("""
    let nan = 0.0 / 0.0;
    let inf = 1.0 / 0.0;
    print(7.5 % 2.0); print(-7.5 % 2.0); print(1.0 % 0.0); print(inf % 2.0); print(2.0 % inf);
    print(min(nan, 1.0)); print(min(1.0, nan)); print(max(nan, 1.0)); print(max(1.0, nan));
    print(nan == nan); print(nan < 1.0); print(abs(-0.0)); print(abs(-inf));""")

    def test_conversions(self):
        self.assertSameMain("""
    print(int(3.99)); print(int(-3.99)); print(int(1e19)); print(int(-1e19)); print(int(1e300));
    print(int(true)); print(int(false));
    print(int("42")); print(int("  -17  ")); print(int("+5")); print(int("1_000_000"));
    print(int("99999999999999999999")); print(int("007"));
    print(float("2.5")); print(float(" -1e3 ")); print(float(".5")); print(float("5."));
    print(float("inf")); print(float("-Infinity")); print(float("nan")); print(float("1_0.2_5"));
    print(float("1e400")); print(float("-0")); print(float(12));""")

    def test_display(self):
        self.assertSame("""
struct P { name: str, xs: [float], ok: bool }
struct Node { v: int, kids: [Node] }
fn double(x: int) -> int { return x * 2; }
fn main() {
    let p = P{name: "a \\"q\\"\\n\\tb", xs: [1.0, 0.5, -0.0], ok: true};
    print(p);
    print([["x", "y"], [], ["\\\\"]]);
    print(Node{v: 1, kids: [Node{v: 2, kids: []}]});
    print(double);
    let fs = [double];
    print(fs);
    print(str(1) + str(2.0) + str(false) + str("s"));
}""")


class TestStrings(Differential):
    def test_unicode_counts_characters(self):
        self.assertSameMain("""
    let s = "héllo wörld ✓ 𝄞";
    print(s); print(len(s)); print(s[1]); print(s[14]); print(substr(s, 6, 11));
    for ch in "añ𝄞" { print(str(ord(ch)) + " " + ch); }
    print(chr(233) + chr(10003) + chr(119070));
    print("b" < "a"); print("ab" < "b"); print("é" > "z"); print("" < "a"); print("abc" == "ab" + "c");""")

    def test_string_building(self):
        self.assertSameMain("""
    var s = "";
    for i in 0..1000 { s = s + chr(65 + i % 26); }
    print(len(s)); print(substr(s, 990, 1000)); print([s[0], s[25], s[26]]);""")


class TestEvaluationOrder(Differential):
    PRELUDE = """
var log: [str] = [];
var g = 1;
fn note(s: str, v: int) -> int { push(log, s); return v; }
fn bump() -> int { g = g + 10; return g; }
"""

    def test_operands_and_arguments_run_left_to_right(self):
        self.assertSameMain("""
    print(note("a", 1) + note("b", 2) * note("c", 3));
    print(note("d", 1) < note("e", 2));
    print(max(note("f", 1), note("g", 2)));
    print([note("h", 1), note("i", 2)]);
    print(log);""", self.PRELUDE)

    def test_a_global_is_read_before_a_later_call_changes_it(self):
        self.assertSameMain("""
    print(g + bump());
    print(bump() + g);
    let xs = [g, bump(), g];
    print(xs);""", self.PRELUDE)

    def test_heap_reads_happen_in_order(self):
        self.assertSame("""
struct Box { v: int }
fn poke(b: Box, xs: [int]) -> int { b.v = 100; xs[0] = 100; push(xs, 7); return 1; }
fn main() {
    let b = Box{v: 1};
    let xs = [1];
    print(b.v + poke(b, xs) + b.v);
    print(xs[0] + poke(b, xs) + xs[0]);
    print(len(xs) + poke(b, xs) + len(xs));
}""")

    def test_struct_fields_run_in_declaration_order(self):
        self.assertSame("""
struct P { a: int, b: int }
fn say(s: str, v: int) -> int { print(s); return v; }
fn main() { let p = P{b: say("b", 2), a: say("a", 1)}; print(p); }""")

    def test_short_circuit(self):
        self.assertSameMain("""
    print(false && note("x", 1) == 1);
    print(true || note("y", 1) == 1);
    print(true && note("z", 1) == 1);
    print(log);""", self.PRELUDE)


class TestControlFlow(Differential):
    def test_loops_break_and_continue(self):
        self.assertSameMain("""
    var out: [int] = [];
    for i in 0..10 { if i % 2 == 0 { continue; } if i > 7 { break; } push(out, i); }
    var j = 0;
    while j < 10 { j += 1; if j == 3 { continue; } if j == 6 { break; } push(out, j * 10); }
    for x in [5, 6, 7] { if x == 6 { continue; } push(out, x * 100); }
    print(out);""")

    def test_for_in_sees_the_array_grow(self):
        self.assertSameMain("""
    var xs = [1, 2, 3];
    for x in xs { if x < 3 { push(xs, x + 10); } }
    print(xs);""")

    def test_range_bounds_are_evaluated_once(self):
        self.assertSameMain("""
    var n = 3;
    for i in 0..n { n = 10; print(i); }""")

    def test_compound_assignment_on_every_target(self):
        self.assertSame("""
struct C { n: int, f: float, s: str }
var total = 5;
fn main() {
    var xs = [10, 20];
    let c = C{n: 7, f: 1.5, s: "a"};
    xs[1] += 3; xs[0] /= 3; xs[1] %= 7;
    c.n *= 6; c.f /= 0.5; c.s += "b";
    total -= 2;
    var loc = 9; loc /= 2;
    print(xs); print(c); print(total); print(loc);
}""")

    def test_shadowing_and_top_level_scopes(self):
        self.assertSame("""
let x = 1;
{ let x = 2; print(x); }
for i in 0..2 { let x = i * 100; print(x); }
fn main() { let x = "inner"; { let x = 3.5; print(x); } print(x); }""")

    def test_function_values(self):
        self.assertSame("""
fn inc(x: int) -> int { return x + 1; }
fn twice(f: fn(int) -> int, x: int) -> int { return f(f(x)); }
fn pick(b: bool) -> fn(int) -> int { if b { return inc; } return neg; }
fn neg(x: int) -> int { return -x; }
let g = inc;
fn main() {
    print(twice(inc, 5)); print(twice(pick(false), 5)); print(g(1));
    let table = [inc, neg];
    print(table[1](4));
}""")

    def test_deep_recursion(self):
        self.assertSame("""
fn depth(n: int) -> int { if n == 0 { return 0; } return 1 + depth(n - 1); }
fn main() { print(depth(5000)); }""")


class TestRuntimeErrors(Differential):
    def test_each_trap_reports_the_same_message_and_traceback(self):
        programs = {
            "div": "var z = 0; print(1 / z);",
            "mod": "var z = 0; print(1 % z);",
            "index": "let a = [1, 2]; print(a[2]);",
            "negative index": "let a = [1, 2]; print(a[-1]);",
            "string index": 'let s = "ab"; print(s[5]);',
            "store": "var a = [1]; a[3] = 1;",
            "compound store": "var a = [1]; a[3] += 1;",
            "pop": "var a: [int] = []; print(pop(a));",
            "sqrt int": "print(sqrt(-4));",
            "sqrt float": "print(sqrt(-0.5));",
            "chr": "print(chr(1114112));",
            "chr negative": "print(chr(-1));",
            "ord": 'print(ord("ab"));',
            "substr": 'print(substr("abc", 2, 1));',
            "int nan": "print(int(0.0 / 0.0));",
            "int inf": "print(int(-1.0 / 0.0));",
            "parse int": "print(int(\"12x\"));",
            "parse int quotes": "print(int(\"it's\"));",
            "parse int both quotes": "print(int(\"'\\\"\"));",
            "parse int escapes": "print(int(\"a\\tb\\n\"));",
            "parse int empty": "print(int(\"\"));",
            "parse int underscore": "print(int(\"1__0\"));",
            "parse float": "print(float(\"1.2.3\"));",
            "parse float unicode": "print(float(\"é\"));",
            "parse float hex": "print(float(\"0x10\"));",
        }
        for name, body in programs.items():
            with self.subTest(trap=name):
                status, _, err = self.assertSameMain("    print(\"before\");\n    " + body)
                self.assertEqual(status, 70, err)

    def test_traceback_through_several_frames_and_a_multiline_call(self):
        self.assertSame("""fn get(a: [int], i: int) -> int {
    return a[i];
}
fn middle(a: [int]) -> int {
    return get(a,
               9);
}
fn main() {
    print(middle([1, 2, 3]));
}""")

    def test_error_in_top_level_code(self):
        self.assertSame("""print("top");
let xs = [1];
print(xs[4]);""")

    def test_global_used_before_initialised(self):
        self.assertSame("""let early = read();
fn read() -> int { return late; }
let late = 2;""")

    def test_stack_overflow_traceback_is_abbreviated(self):
        _, _, err = self.assertSame("""fn forever(n: int) -> int {
    return forever(n + 1) + 1;
}
fn main() { print(forever(0)); }""")
        self.assertIn("call stack overflow", err)
        self.assertIn("frames omitted", err)


class TestOptimiser(Differential):
    def test_unoptimised_builds_agree_too(self):
        source = """
fn f(x: int) -> int { if true { return x * 1 + 0; } return 0; }
fn main() { print(f(3) + 2 * 3); print("a" + "" + "b"); while false { print(1); } }"""
        self.assertSame(source, optimise=False)
        self.assertSame(source, optimise=True)


class TestLiterals(unittest.TestCase):
    def test_c_int(self):
        self.assertEqual(c_int(5), "5")
        self.assertEqual(c_int(-5), "(-5)")
        self.assertEqual(c_int(MIN_I64), "INT64_MIN")
        self.assertEqual(c_int(MAX_I64), f"INT64_C({MAX_I64})")

    def test_c_float(self):
        self.assertEqual(c_float(float("inf")), "INFINITY")
        self.assertEqual(c_float(float("-inf")), "(-INFINITY)")
        self.assertEqual(c_float(float("nan")), "NAN")
        self.assertEqual(c_float(-0.0), "(-0.0)")
        self.assertEqual(c_float(1e16), "1e+16")

    def test_c_string_escapes_everything_risky(self):
        self.assertEqual(c_string('a"b\\c??=\n'), '"a\\"b\\\\c\\?\\?=\\012"')
        self.assertEqual(c_string("é"), '"\\303\\251"')


@unittest.skipUnless(HAVE_CC, "no C compiler")
class TestCli(unittest.TestCase):
    def borkc(self, *args):
        return subprocess.run([sys.executable, os.path.join(ROOT, "borkc"), *args],
                              capture_output=True, text=True)

    def test_build_c_produces_a_working_binary_and_keeps_the_c(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "hello")
            proc = self.borkc("build-c", os.path.join(EXAMPLES, "hello.bk"), "-o", out)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(os.path.exists(out + ".c"))
            run = subprocess.run([out], capture_output=True, text=True)
            self.assertEqual(run.stdout, "Hello from Bork!\nHello, world!\n")

    def test_emit_c_prints_a_translation_unit(self):
        proc = self.borkc("emit-c", os.path.join(EXAMPLES, "hello.bk"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("static bork_unit fn_main(void)", proc.stdout)
        self.assertIn("int main(void)", proc.stdout)

    def test_type_errors_are_reported_before_any_c_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "broken")
            proc = self.borkc("build-c", os.path.join(EXAMPLES, "broken.bk"), "-o", out)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("aborting due to 8 errors", proc.stderr)
            self.assertFalse(os.path.exists(out + ".c"))

    def test_a_missing_c_compiler_is_a_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, CC="definitely-not-a-c-compiler")
            proc = subprocess.run([sys.executable, os.path.join(ROOT, "borkc"), "build-c",
                                   os.path.join(EXAMPLES, "hello.bk"), "-o", os.path.join(tmp, "h")],
                                  capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("no C compiler found", proc.stderr)


if __name__ == "__main__":
    unittest.main()
