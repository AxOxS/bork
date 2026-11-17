"""Command line driver for the Bork compiler."""
from __future__ import annotations

import argparse
import os
import sys
import time

from . import __version__, compile_source
from .ast_nodes import dump
from .builtins import BUILTINS
from .bytecode import deserialize, serialize
from .disasm import disassemble
from .errors import BorkError, BorkRuntimeError, render_diagnostics
from .lexer import tokenize
from .vm import VM

USAGE = """borkc <command> [options] <file>

commands:
  run      compile and execute a .bk source file (or run a .bkc object file)
  build    compile a .bk file to a .bkc bytecode object file
  build-c  compile a .bk file to a native executable, via C
  emit-c   print the C that build-c compiles
  check    type-check only, reporting errors and warnings
  dis      disassemble a .bk or .bkc file
  ast      print the type-annotated syntax tree
  tokens   print the token stream
  builtins list the built-in functions
"""


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        sys.stderr.write(f"borkc: cannot read {path}: {exc.strerror}\n")
        raise SystemExit(2)


def _use_color(stream) -> bool:
    return stream.isatty() and os.environ.get("NO_COLOR") is None


def _report(exc: BorkError) -> int:
    sys.stderr.write(render_diagnostics(exc.diagnostics, exc.source, exc.filename, _use_color(sys.stderr)))
    count = len(exc.diagnostics)
    sys.stderr.write(f"borkc: aborting due to {count} error{'s' if count != 1 else ''}\n")
    return 1


def _emit_warnings(result, filename: str) -> None:
    if result.warnings:
        sys.stderr.write(render_diagnostics(result.warnings, result.checker.source, filename,
                                            _use_color(sys.stderr)))


def _compile(path: str, args) -> tuple:
    source = _read(path)
    result = compile_source(source, path, optimise=not args.no_optimise)
    _emit_warnings(result, path)
    return source, result


# A .bk source, or an already compiled .bkc.
def _load_program(path: str, args):
    if path.endswith(".bkc"):
        with open(path, "rb") as handle:
            return deserialize(handle.read()), None
    _, result = _compile(path, args)
    return result.program, result


def cmd_run(args) -> int:
    started = time.perf_counter()
    program, result = _load_program(args.file, args)
    compiled_at = time.perf_counter()
    vm = VM(program, trace=args.trace)
    try:
        vm.run()
    except BorkRuntimeError as exc:
        sys.stdout.flush()
        sys.stderr.write(exc.render() + "\n")
        return 70
    if args.stats:
        elapsed = time.perf_counter() - compiled_at
        stats = [f"compiled in {(compiled_at - started) * 1000:.1f} ms",
                 f"ran {vm.instructions:,} instructions in {elapsed * 1000:.1f} ms"]
        if result is not None and result.optimizer is not None:
            o = result.optimizer
            stats.append(f"optimiser: {o.folds} folded, {o.branches_pruned} branches pruned, "
                         f"{o.dead_stmts} dead statements removed")
        sys.stderr.write("borkc: " + "; ".join(stats) + "\n")
    return 0


def cmd_build(args) -> int:
    source, result = _compile(args.file, args)
    out_path = args.output or os.path.splitext(args.file)[0] + ".bkc"
    blob = serialize(result.program)
    with open(out_path, "wb") as handle:
        handle.write(blob)
    total = sum(len(f.code) for f in result.program.functions)
    sys.stderr.write(f"borkc: wrote {out_path} ({len(blob)} bytes, {total} bytes of code, "
                     f"{len(result.program.functions)} functions)\n")
    return 0


def cmd_emit_c(args) -> int:
    from .cbackend import generate
    _, result = _compile(args.file, args)
    c_source = generate(result.module, result.checker, args.file)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(c_source)
    else:
        sys.stdout.write(c_source)
    return 0


def cmd_build_c(args) -> int:
    from .cbackend import CBackendError, compile_c, generate
    _, result = _compile(args.file, args)
    out_path = args.output or os.path.splitext(args.file)[0]
    try:
        c_path = compile_c(generate(result.module, result.checker, args.file), out_path)
    except CBackendError as exc:
        sys.stderr.write(f"borkc: {exc}\n")
        return 1
    sys.stderr.write(f"borkc: wrote {out_path} (C source kept at {c_path})\n")
    return 0


def cmd_check(args) -> int:
    _, result = _compile(args.file, args)
    warnings = len(result.warnings)
    sys.stderr.write(f"borkc: {args.file} is well typed"
                     + (f" ({warnings} warning{'s' if warnings != 1 else ''})\n" if warnings else "\n"))
    return 0


def cmd_dis(args) -> int:
    program, _ = _load_program(args.file, args)
    sys.stdout.write(disassemble(program))
    return 0


def cmd_ast(args) -> int:
    _, result = _compile(args.file, args)
    sys.stdout.write(dump(result.module) + "\n")
    return 0


def cmd_tokens(args) -> int:
    source = _read(args.file)
    for token in tokenize(source, args.file):
        value = "" if token.value is None or token.value == token.kind else f"  {token.value!r}"
        sys.stdout.write(f"{token.span.line:>4}:{token.span.col:<4} {token.kind:<10}{value}\n")
    return 0


def cmd_builtins(args) -> int:
    sys.stdout.write("built-in functions:\n")
    for b in BUILTINS:
        sys.stdout.write(f"  {b.doc}\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="borkc", usage=USAGE, add_help=True,
                                     description=f"The Bork compiler, version {__version__}.")
    parser.add_argument("--version", action="version", version=f"borkc {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    def add(name, handler, needs_file=True, help_text=""):
        p = sub.add_parser(name, help=help_text)
        if needs_file:
            p.add_argument("file", help="source (.bk) or object (.bkc) file")
            p.add_argument("-O0", "--no-optimise", action="store_true", help="disable the optimiser")
        p.set_defaults(handler=handler)
        return p

    run = add("run", cmd_run, help_text="compile and execute")
    run.add_argument("--stats", action="store_true", help="report compile and run statistics")
    run.add_argument("--trace", action="store_true", help="trace every instruction to stderr")

    build = add("build", cmd_build, help_text="compile to a .bkc object file")
    build.add_argument("-o", "--output", help="output path (default: alongside the source)")

    build_c = add("build-c", cmd_build_c, help_text="compile to a native executable via C")
    build_c.add_argument("-o", "--output", help="output path (default: the source without .bk)")
    emit_c = add("emit-c", cmd_emit_c, help_text="print the generated C")
    emit_c.add_argument("-o", "--output", help="write the C here instead of to stdout")

    add("check", cmd_check, help_text="type-check only")
    add("dis", cmd_dis, help_text="disassemble")
    add("ast", cmd_ast, help_text="print the annotated syntax tree")
    add("tokens", cmd_tokens, help_text="print the token stream")
    add("builtins", cmd_builtins, needs_file=False, help_text="list built-in functions")
    return parser


def main(argv: list[str] | None = None) -> int:
    # Parsing, checking and code generation all walk the tree recursively, so
    # deeply nested source needs headroom above the default limit.
    sys.setrecursionlimit(20000)
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    if not hasattr(args, "no_optimise"):
        args.no_optimise = False
    for flag in ("trace", "stats"):
        if not hasattr(args, flag):
            setattr(args, flag, False)
    try:
        return args.handler(args)
    except BorkError as exc:
        return _report(exc)
    except RecursionError:
        sys.stderr.write("borkc: expression or block nesting is too deep for this compiler\n")
        return 1
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        sys.stderr.write("borkc: interrupted\n")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
