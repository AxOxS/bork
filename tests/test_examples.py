"""Every example must compile, run, and keep producing the same output."""
import io
import os
import unittest

from helpers import compile_errors
from lumen import compile_source, deserialize, serialize
from lumen.vm import VM

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")


def run_example(name: str) -> str:
    path = os.path.join(EXAMPLES, name)
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    result = compile_source(source, path)
    buffer = io.StringIO()
    VM(result.program, out=buffer).run()
    return buffer.getvalue()


class TestExamples(unittest.TestCase):
    def test_hello(self):
        self.assertEqual(run_example("hello.lm"), "Hello from Lumen!\nHello, world!\n")

    def test_fizzbuzz(self):
        self.assertEqual(run_example("fizzbuzz.lm"),
                         "1 2 Fizz 4 Buzz Fizz 7 8 Fizz Buzz 11 Fizz 13 14 FizzBuzz 16 17 Fizz 19 Buzz\n")

    def test_fib(self):
        lines = run_example("fib.lm").splitlines()
        self.assertEqual(lines[0], "fib(22) = 17711 (recursive)")
        self.assertEqual(lines[1], "fib(22) = 17711 (iterative)")
        self.assertTrue(lines[3].startswith("first 15: 0 1 1 2 3 5 8 13 21 34 55 89 144 233 377"))

    def test_primes(self):
        lines = run_example("primes.lm").splitlines()
        self.assertEqual(lines[0], "primes below 100 (25 of them):")
        self.assertTrue(lines[1].startswith("2 3 5 7 11 13"))
        self.assertEqual(lines[2], "their sum is 1060")

    def test_sort(self):
        lines = run_example("sort.lm").splitlines()
        values = [int(v) for v in lines[1].replace("sorted:", "").strip(" []").split(",")]
        self.assertEqual(values, sorted(values))
        self.assertEqual(lines[2], "ordered:  true")
        self.assertTrue(lines[4].endswith("returns -1"))

    def test_structs(self):
        self.assertEqual(run_example("structs.lm").splitlines()[0],
                         "ida ended at (2.0, 4.0), speed 2.23606797749979")
        self.assertIn("aliased through the array: (100.0, 4.0)", run_example("structs.lm"))

    def test_mandelbrot(self):
        lines = run_example("mandelbrot.lm").splitlines()
        self.assertEqual(len(lines), 24)
        self.assertTrue(all(len(line) == 70 for line in lines))
        # The real axis from about -2 to 0.25 lies inside the set.
        self.assertGreater(lines[12].count("@"), 40)

    def test_brainfuck(self):
        output = run_example("brainfuck.lm")
        self.assertIn("Hello World!", output)
        self.assertIn("7", output.splitlines()[-1])

    def test_broken_example_reports_every_error(self):
        with open(os.path.join(EXAMPLES, "broken.lm"), encoding="utf-8") as handle:
            errors = compile_errors(handle.read())
        self.assertEqual(len(errors), 8)
        # The poisoned `p` must not produce a cascading second field error.
        self.assertEqual(sum("has no field 'z'" in e for e in errors), 1)

    def test_every_example_survives_an_object_file_round_trip(self):
        for name in sorted(os.listdir(EXAMPLES)):
            if not name.endswith(".lm") or name in ("broken.lm", "fib.lm"):
                continue        # fib.lm prints timings, which vary between runs
            with self.subTest(example=name), open(os.path.join(EXAMPLES, name), encoding="utf-8") as f:
                result = compile_source(f.read(), name)
                direct, restored = io.StringIO(), io.StringIO()
                VM(result.program, out=direct).run()
                VM(deserialize(serialize(result.program)), out=restored).run()
                self.assertEqual(direct.getvalue(), restored.getvalue())

    def test_every_example_gives_identical_output_unoptimised(self):
        for name in sorted(os.listdir(EXAMPLES)):
            if not name.endswith(".lm") or name in ("broken.lm", "fib.lm"):
                continue        # fib.lm prints timings, which vary
            with self.subTest(example=name), open(os.path.join(EXAMPLES, name), encoding="utf-8") as f:
                source = f.read()
                fast, plain = io.StringIO(), io.StringIO()
                VM(compile_source(source, name, optimise=True).program, out=fast).run()
                VM(compile_source(source, name, optimise=False).program, out=plain).run()
                self.assertEqual(fast.getvalue(), plain.getvalue())


if __name__ == "__main__":
    unittest.main()
