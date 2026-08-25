"""End-to-end tests for the `lumc` driver."""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LUMC = os.path.join(ROOT, "lumc")


def lumc(*args, expect_success=None):
    proc = subprocess.run([sys.executable, LUMC, *args], capture_output=True, text=True)
    if expect_success is True:
        assert proc.returncode == 0, f"lumc {' '.join(args)} failed:\n{proc.stderr}"
    return proc


class TestCLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.good = os.path.join(cls.tmp.name, "good.lm")
        with open(cls.good, "w") as handle:
            handle.write('fn twice(n: int) -> int { return n * 2; }\n'
                         'fn main() { print("value " + str(twice(21))); }\n')
        cls.bad = os.path.join(cls.tmp.name, "bad.lm")
        with open(cls.bad, "w") as handle:
            handle.write("fn main() { let x: int = true; }\n")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_run(self):
        self.assertEqual(lumc("run", self.good, expect_success=True).stdout, "value 42\n")

    def test_run_reports_errors_and_exits_nonzero(self):
        proc = lumc("run", self.bad)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("expected `int`", proc.stderr)
        self.assertIn("aborting due to 1 error", proc.stderr)

    def test_runtime_trap_exit_code(self):
        path = os.path.join(self.tmp.name, "trap.lm")
        with open(path, "w") as handle:
            handle.write("fn main() { let xs = [1]; print(xs[9]); }\n")
        proc = lumc("run", path)
        self.assertEqual(proc.returncode, 70)
        self.assertIn("out of bounds", proc.stderr)
        self.assertIn("at main", proc.stderr)

    def test_check(self):
        self.assertIn("well typed", lumc("check", self.good, expect_success=True).stderr)
        self.assertEqual(lumc("check", self.bad).returncode, 1)

    def test_build_then_run_object_file(self):
        obj = os.path.join(self.tmp.name, "out.lmc")
        lumc("build", self.good, "-o", obj, expect_success=True)
        self.assertTrue(os.path.exists(obj))
        with open(obj, "rb") as handle:
            self.assertEqual(handle.read(4), b"LUMC")
        self.assertEqual(lumc("run", obj, expect_success=True).stdout, "value 42\n")

    def test_build_defaults_output_next_to_source(self):
        lumc("build", self.good, expect_success=True)
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "good.lmc")))

    def test_dis(self):
        out = lumc("dis", self.good, expect_success=True).stdout
        self.assertIn("fn twice(n: int) -> int", out)
        self.assertIn("MUL_INT", out)
        self.assertIn("[entry]", out)

    def test_ast(self):
        out = lumc("ast", self.good, expect_success=True).stdout
        self.assertIn("FnDecl", out)
        self.assertIn(": int", out)      # types are annotated on the tree

    def test_tokens(self):
        out = lumc("tokens", self.good, expect_success=True).stdout
        self.assertIn("ident", out)
        self.assertTrue(out.strip().endswith("eof"))

    def test_builtins(self):
        out = lumc("builtins", expect_success=True).stdout
        self.assertIn("print(v)", out)
        self.assertIn("substr(s, i, j)", out)

    def test_stats_flag(self):
        proc = lumc("run", self.good, "--stats", expect_success=True)
        self.assertIn("instructions", proc.stderr)
        self.assertIn("optimiser:", proc.stderr)

    def test_no_optimise_flag(self):
        self.assertEqual(lumc("run", self.good, "-O0", expect_success=True).stdout, "value 42\n")

    def test_trace_flag(self):
        proc = lumc("run", self.good, "--trace", expect_success=True)
        self.assertIn("LOAD_GLOBAL", proc.stderr)
        self.assertEqual(proc.stdout, "value 42\n")

    def test_missing_file(self):
        proc = lumc("run", os.path.join(self.tmp.name, "nope.lm"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot read", proc.stderr)

    def test_no_arguments_prints_help(self):
        self.assertIn("commands:", lumc(expect_success=True).stdout)

    def test_version(self):
        self.assertIn("lumc", lumc("--version", expect_success=True).stdout)

    def test_warnings_do_not_fail_the_build(self):
        path = os.path.join(self.tmp.name, "warn.lm")
        with open(path, "w") as handle:
            handle.write('fn f() -> int { return 1; print("dead"); }\nfn main() { f(); }\n')
        proc = lumc("check", path, expect_success=True)
        self.assertIn("unreachable code", proc.stderr)


if __name__ == "__main__":
    unittest.main()
