# Lumen

A small statically typed programming language, and a complete compiler for it:
lexer, parser, type checker, optimiser, bytecode code generator, object file
format, disassembler, and a virtual machine that runs the result.

No dependencies beyond Python 3.10+.

```console
$ ./lumc run examples/hello.lm
Hello from Lumen!
Hello, world!
```

---

## Contents

- [Quick start](#quick-start)
- [The language](#the-language)
- [Compiler architecture](#compiler-architecture)
- [The bytecode](#the-bytecode)
- [Object files](#object-files)
- [Diagnostics](#diagnostics)
- [Project layout](#project-layout)
- [Tests](#tests)
- [Deliberate design decisions](#deliberate-design-decisions)
- [Limits](#limits)

---

## Quick start

```console
$ ./lumc run examples/primes.lm         # compile and execute
$ ./lumc check examples/broken.lm       # type-check only, print diagnostics
$ ./lumc build examples/sort.lm         # emit sort.lmc, a bytecode object file
$ ./lumc run examples/sort.lmc          # run a pre-compiled object file
$ ./lumc dis examples/fib.lm            # disassemble
$ ./lumc ast examples/hello.lm          # print the type-annotated syntax tree
$ ./lumc tokens examples/hello.lm       # print the token stream
$ ./lumc builtins                       # list built-in functions
```

Useful flags: `--stats` (compile/run timings and optimiser counts), `--trace`
(dump every instruction as it executes), `-O0` (disable the optimiser).

The compiler is also a library:

```python
from lumen import compile_source, run_source
run_source('fn main() { print("hi"); }')
```

---

## The language

Lumen is statically typed with local type inference, eager evaluation, and
**no implicit conversions of any kind**. Every type error is caught before the
program runs.

### Program structure

A file is a sequence of top-level statements, function declarations and struct
declarations. Top-level statements run in order, then `main` is called if a
function of that name exists (it must take no parameters and return nothing).
Functions and structs are hoisted, so they can be used before they appear.

```lumen
struct Point { x: int, y: int }

fn norm2(p: Point) -> int { return p.x * p.x + p.y * p.y; }

fn main() {
    print(str(norm2(Point{x: 3, y: 4})));   // 25
}
```

### Types

| Type | Notes |
|---|---|
| `int` | 64-bit signed, wraps on overflow |
| `float` | IEEE-754 double |
| `bool` | `true` / `false` |
| `str` | immutable UTF-8 text |
| `[T]` | growable array, a reference |
| `struct` | named record, a reference, nominally typed |
| `fn(A, B) -> C` | function value (top-level functions only; no closures) |
| `unit` | the type of a function that returns nothing |

### Bindings

`let` binds immutably, `var` binds mutably. The type is inferred from the
initialiser unless annotated.

```lumen
let answer = 42;             // int
var total: float = 0.0;      // annotated
let names: [str] = [];       // annotation needed: an empty literal infers nothing
```

Shadowing in an inner scope is allowed; redeclaring in the same scope is not.

### Control flow

```lumen
if x > 0 { ... } else if x < 0 { ... } else { ... }

while condition { ... }

for i in 0..10 { ... }       // range, end exclusive, bounds evaluated once
for item in array { ... }    // arrays
for ch in "text" { ... }     // strings, one character at a time

break;  continue;  return value;
```

Conditions must be `bool` — there is no truthiness. Braces are always required.
`&&` and `||` short-circuit.

### Functions

Parameter and return types are always written out; a missing return type means
`unit`. A function whose return type is not `unit` must return on every path,
and the checker proves it.

```lumen
fn apply(f: fn(int) -> int, v: int) -> int { return f(v); }
fn double(x: int) -> int { return x * 2; }

fn main() { print(str(apply(double, 21))); }   // 42
```

### Arrays and structs

Both are references: passing one to a function and mutating it is visible to the
caller. Struct types are nominal — two structs with identical fields are
different types.

```lumen
var xs = [3, 1, 2];
xs[0] = 9;
push(xs, 4);
let n = len(xs);
```

### Operators

Precedence, loosest to tightest: `||`, `&&`, `== !=`, `< <= > >=`, `+ -`,
`* / %`, unary `- !`, then calls, indexing and field access. All binary
operators are left-associative.

`+` is arithmetic on `int` and `float`, and concatenation on `str`. Ordering
comparisons work on `int`, `float` and `str`; `==` works on primitives only —
comparing arrays or structs is a type error rather than a silent identity
comparison.

Compound assignment (`+= -= *= /= %=`) works on variables, array elements and
struct fields.

### Built-in functions

`print` `len` `str` `int` `float` `push` `pop` `sqrt` `abs` `min` `max` `chr`
`ord` `substr` `clock` — run `./lumc builtins` for signatures. They can be
called but not passed around as values.

---

## Compiler architecture

```
source text
    |
    v
  Lexer          lumen/lexer.py       characters -> tokens, each carrying a Span
    |
    v
  Parser         lumen/parser.py      recursive descent + Pratt precedence
    |                                 panic-mode recovery reports many errors
    v
  AST            lumen/ast_nodes.py
    |
    v
  Checker        lumen/checker.py     4 passes: struct names, struct fields,
    |                                 function signatures, then bodies.
    |                                 Resolves names to storage slots, types
    |                                 every expression, proves all paths return
    v
  Optimiser      lumen/optimizer.py   type-directed constant folding, algebraic
    |                                 identities, dead branch/code elimination
    v
  Code gen       lumen/compiler.py    syntax-directed emission, back-patched
    |                                 jumps, per-function constant pools
    v
  Bytecode       lumen/bytecode.py    Program / Function / .lmc serialisation
    |
    v
  VM             lumen/vm.py          iterative stack interpreter
```

The checker is the only phase that makes decisions. It writes its conclusions
onto the AST — `.ty` on every expression, a storage slot on every binding, a
field index on every access, an operand class on every operator — so the code
generator is a pure translation with no lookups, and the VM never inspects a
type at runtime.

### Passes in the checker

Four passes exist so that declaration order does not matter:

1. **Struct names** — registered first, so fields may refer to any struct,
   including recursively (`struct Node { children: [Node] }`).
2. **Struct fields** — resolved now that every name exists.
3. **Function signatures** — so functions can call each other in any order,
   including mutual recursion.
4. **Bodies** — top-level statements in source order (this is where globals get
   their slots), then every function body with the full environment visible.

### Storage

Bindings at the top level become **globals** (a flat array in the VM). Bindings
inside a function or block become **locals**, addressed as an offset from the
current frame base. Slots are assigned at compile time, so variable access is an
array index, never a hash lookup.

---

## The bytecode

A stack machine. One opcode byte plus fixed-width operands, so the stream
decodes linearly for both the VM and the disassembler.

Arithmetic opcodes are **specialised by static type** — `ADD_INT` and
`ADD_FLOAT` are different instructions — because the checker has already proved
the operand types. The VM never dispatches on a value's type to do arithmetic.

`len(x)` is an **intrinsic**: it compiles to a single `LEN` instruction rather
than a call. Other built-ins become `CALL_NATIVE`.

```console
$ ./lumc dis examples/hello.lm
```

```
=== [0] main
fn main()
  ; 28 bytes, 0 param(s), 1 local slot(s), 4 constant(s)
     3     0  CONST                 0      ; "Hello from Lumen!"
           3  CALL_NATIVE           0, 1   ; print
           6  POP
     5     7  CONST                 1      ; "world"
          10  STORE_LOCAL           0
     6    12  CONST                 2      ; "Hello, "
          15  LOAD_LOCAL            0
          17  CONCAT
          18  CONST                 3      ; "!"
          21  CONCAT
          22  CALL_NATIVE           0, 1   ; print
          25  POP
          26  UNIT
          27  RET
```

The left column is the source line, from a line table stored with each function
and used to build runtime tracebacks.

### Calling convention

```
... callee arg0 arg1 ... argN-1 [extra locals] <temporaries>
    ^                           ^
    base-1                      base+N
```

`LOAD_LOCAL i` is `stack[base + i]`; parameters are simply the first locals.
`RET` truncates the stack back to `base-1` and pushes the result. Frames are an
explicit list, so recursion depth is bounded by the VM's own limit (20,000
frames) rather than the host language's call stack — 5,000-deep Lumen recursion
works fine and overflow is a clean trap with a truncated traceback.

---

## Object files

`lumc build` writes a `.lmc` file: magic `LUMC`, a version byte, then the struct
table, global initialiser table, debug names, and every function with its code,
constant pool and line table. `lumc run` and `lumc dis` accept them directly.
The format is versioned and rejects truncated or foreign files.

---

## Diagnostics

Errors are collected, not thrown one at a time — a single run reports
everything it can find. The parser resynchronises at statement boundaries; the
checker poisons a bad expression's type so one mistake does not cascade into
five.

```console
$ ./lumc check examples/broken.lm
```

```
error: cannot apply `+` to `int` and `str`
  --> examples/broken.lm:17:17
   |
17 |     let total = 1 + "two";                // no implicit conversion
   |                 ^^^^^^^^^
   = note: use `str(x)` to convert the other operand to text

error: cannot assign to 'total' because it is not mutable
  --> examples/broken.lm:19:5
   |
19 |     total = 9;                            // 'total' is not mutable
   |     ^^^^^
   = note: declare it with `var total = ...` to make it mutable
```

Unknown names get a spelling suggestion. Unreachable code is a warning, not an
error. Runtime traps print a traceback with function names and line numbers:

```
runtime error: index 4 is out of bounds for array of length 3
    at get (rt.lm:2)
    at middle (rt.lm:5)
    at main (rt.lm:9)
```

---

## Project layout

```
lumc                  the compiler driver (executable)
run_tests.py          runs the whole test suite
lumen/
  lexer.py            tokens and source spans
  ast_nodes.py        AST dataclasses and the tree printer
  types.py            the type lattice
  parser.py           recursive descent + Pratt expressions
  checker.py          name resolution, type checking, slot allocation
  optimizer.py        constant folding and dead code elimination
  opcodes.py          the instruction set
  bytecode.py         Program/Function and .lmc serialisation
  compiler.py         code generation
  disasm.py           disassembler
  vm.py               the virtual machine
  builtins.py         built-in functions (checking rules + implementations)
  values.py           runtime values and integer semantics
  errors.py           diagnostics and rendering
  cli.py              command line driver
examples/             sample programs, including one that deliberately fails
tests/                153 tests across every phase
```

---

## Tests

```console
$ python3 run_tests.py
Ran 153 tests in 5.1s
OK
```

Coverage spans every phase: lexing edge cases (`1..5` is a range, not a float),
parser precedence and error recovery, ~30 distinct type errors, execution
semantics, optimiser correctness (folding must use *Lumen's* division
semantics, not Python's), object file round-trips, resource limits, the CLI,
and golden outputs for every example. Two properties are checked across all
examples: optimised and unoptimised builds must produce identical output, and
so must a program run before and after a serialisation round-trip.

---

## Deliberate design decisions

**No implicit conversions.** `1 + 2.0` is an error, and so is `"n=" + 1`. The
error message names the conversion you need. This keeps arithmetic opcodes
monomorphic and makes the cost of every operation visible in the source.

**C-style integer division.** `-7 / 2` is `-3` and `-7 % 2` is `-1` — truncation
toward zero, with the remainder taking the sign of the dividend. Python's `//`
floors instead, so the constant folder implements the language's semantics
explicitly rather than inheriting the host's.

**Integers wrap.** `int` is exactly 64 bits; `MAX_INT + 1` is `MIN_INT`, in the
optimiser as well as at runtime. The host's arbitrary-precision integers are
never allowed to leak through.

**Floats follow IEEE-754.** `1.0 / 0.0` is `inf`, `0.0 / 0.0` is `nan`, and
negative zero prints as `-0.0`. Integer division by zero, by contrast, traps.

**Operations that can trap are never folded.** `1 / 0` stays in the bytecode so
the error surfaces at the line the programmer wrote, not at compile time.

**Float identities are not applied.** `x + 0` folds to `x` for integers, but
`x * 1.0` is left alone: those identities are unsound around `NaN` and signed
zero.

**Struct fields are evaluated in declaration order**, not in the order written
in the literal, so `P{b: f(), a: g()}` calls `g` first. This is the one place
where evaluation order is not left-to-right, and it is what lets a struct
literal compile to a single `MAKE_STRUCT`.

**No closures.** Functions are values, but only top-level ones, so a function
value is always just a global slot — no capture analysis, no heap-allocated
environments. Nested `fn` declarations are rejected with an explanation rather
than silently misbehaving.

**Compiler limits are diagnostics.** Exceeding an operand width — too many
locals, too many struct fields, a jump longer than 32KB — reports a normal
error with a source location and a suggested fix.

---

## Limits

| Limit | Value | Reason |
|---|---|---|
| Locals per function | 256 | `LOAD_LOCAL` takes a `u8` |
| Globals per module | 65,536 | `LOAD_GLOBAL` takes a `u16` |
| Constants per function | 65,536 | `CONST` takes a `u16` |
| Parameters per function | 255 | `CALL` takes a `u8` count |
| Fields per struct | 255 | `FIELD_GET` takes a `u8` index |
| Jump distance | ±32,767 bytes | jumps take an `s16` displacement |
| Call depth | 20,000 frames | VM frame limit |

### Things Lumen does not have

Closures, generics, modules and imports, methods, pattern matching, a garbage
collector of its own (the host's collector owns runtime values), and a native
code backend. The bytecode and its object file format are the compilation
target.
