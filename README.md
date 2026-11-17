# Bork

A small statically typed language and a complete compiler for it, in Python 3.10+
with no dependencies. Programs run on a bytecode VM, or compile to native
executables through C.

```console
$ ./borkc run examples/hello.bk
Hello from Bork!
Hello, world!
```

## Usage

```console
$ ./borkc run examples/primes.bk         # compile and run
$ ./borkc check examples/broken.bk       # type-check only
$ ./borkc build examples/sort.bk         # write sort.bkc (bytecode object file)
$ ./borkc run examples/sort.bkc          # run an object file
$ ./borkc build-c examples/fib.bk -o fib # native executable via C, keeps fib.c
$ ./borkc emit-c examples/fib.bk         # print the generated C
$ ./borkc dis | ast | tokens <file>      # inspect the bytecode, tree or tokens
$ ./borkc builtins                       # list built-in functions
```

Flags: `-O0` disables the optimiser; `run` also takes `--stats` and `--trace`.

## The language

```bork
struct Point { x: int, y: int }

fn norm2(p: Point) -> int { return p.x * p.x + p.y * p.y; }

fn main() {
    var total = 0;
    for i in 0..3 { total += norm2(Point{x: i, y: 4}); }
    print(str(total));   // 53
}
```

- Types: `int` (64-bit, wraps), `float`, `bool`, `str`, arrays `[T]`, structs,
  function values `fn(A) -> B`, and `unit`.
- `let` is immutable, `var` mutable; types are inferred unless annotated.
- `if`/`else`, `while`, `for i in a..b`, `for x in array_or_string`, `break`,
  `continue`, `return`.
- No implicit conversions: `1 + 2.0` and `"n=" + 1` are type errors.
- Arrays and structs are references. Structs are nominal.
- Functions are values, but only top-level ones. There are no closures.
- Integer division truncates toward zero; dividing an int by zero traps, a
  float gives `inf` or `nan`.
- Built-ins: `print len str int float push pop sqrt abs min max chr ord substr clock`.

Top-level statements run first, then `main` if there is one.

## How it works

```
lexer -> parser -> checker -> optimiser -> compiler -> VM
                                        \-> cbackend -> cc -> native binary
```

| File | Does |
|---|---|
| `lexer.py`, `parser.py` | tokens with source spans; recursive descent with Pratt precedence and error recovery |
| `checker.py` | resolves names to storage slots, types every expression, proves functions return |
| `optimizer.py` | constant folding with Bork's own arithmetic, dead code removal |
| `compiler.py`, `vm.py` | stack bytecode with type-specific opcodes; an iterative interpreter |
| `bytecode.py`, `disasm.py` | the `.bkc` object file format and its disassembler |
| `cbackend.py`, `runtime.c` | C code generation, and the runtime pasted into every C file |

The checker writes everything it decides onto the AST, so both back ends only
translate. The VM never inspects a type at runtime.

Errors are collected rather than raised one by one, and point at the source:

```
error: cannot apply `+` to `int` and `str`
  --> examples/broken.bk:17:17
   |
17 |     let total = 1 + "two";                // no implicit conversion
   |                 ^^^^^^^^^
   = note: use `str(x)` to convert the other operand to text
```

Runtime errors print a traceback with function names and lines.

## The C back end

A native binary behaves exactly like the VM: the same output, the same runtime
errors, the same tracebacks and the same 20,000-frame call limit. Because C
leaves evaluation order open, calls and other stateful reads are hoisted into
temporaries in source order.

It never frees memory, so a long-running program that keeps building strings
will grow.

## Tests

```console
$ python3 run_tests.py                  # 386 tests
$ BORK_BACKEND=c python3 run_tests.py   # same suite, every program built through C
```

`tests/test_cbackend.py` runs programs through both back ends and compares
stdout, stderr and the exit status. It skips itself if no C compiler is installed.

## Limits

256 locals per function, 65,536 globals and constants, 255 parameters and struct
fields, jumps of up to 32 KB, and 20,000 nested calls. Each comes from an
operand width in the bytecode and is reported as a normal compile error.
