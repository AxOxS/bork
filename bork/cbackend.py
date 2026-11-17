"""Second back end: turns the checked AST into one self-contained C file.
The binary has to behave exactly like the VM, error messages and tracebacks included."""
from __future__ import annotations

import os
import subprocess
import tempfile

from . import ast_nodes as A
from . import types as T
from .checker import Checker, VarInfo
from .values import MIN_I64

RUNTIME_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime.c")

CFLAGS = ["-std=c11", "-O2", "-fwrapv", "-ffp-contract=off"]
LIBS = ["-lm", "-pthread"]

# Builtins whose implementation can fail, and therefore need the line set.
FALLIBLE_BUILTINS = {"int", "float", "pop", "sqrt", "chr", "ord", "substr"}


# cc is missing, or refused what we generated.
class CBackendError(Exception):
    pass


# -- small helpers ---------------------------------------------------------
# UTF-8, with anything outside printable ASCII as an octal escape.
def c_string(text: str) -> str:
    out = []
    for byte in text.encode("utf-8", "surrogatepass"):
        ch = chr(byte)
        if ch in '"\\?':                  # `?` because of trigraphs in strict C11
            out.append("\\" + ch)
        elif 0x20 <= byte < 0x7F:
            out.append(ch)
        else:
            out.append(f"\\{byte:03o}")
    return '"' + "".join(out) + '"'


def c_comment(text: str) -> str:
    return text.replace("*/", "* /").replace("\n", "\\n")


def c_int(value: int) -> str:
    if value == MIN_I64:
        return "INT64_MIN"                 # -9223372036854775808 is not a literal in C
    text = str(value) if -(1 << 31) <= value < (1 << 31) else f"INT64_C({value})"
    return f"({text})" if value < 0 else text


def c_float(value: float) -> str:
    if value != value:
        return "NAN"
    if value in (float("inf"), float("-inf")):
        return "INFINITY" if value > 0 else "(-INFINITY)"
    text = repr(value)
    if not any(c in text for c in ".eE"):
        text += ".0"
    return f"({text})" if text.startswith("-") else text


def paren(expr: str) -> str:
    if expr.startswith("(") and expr.endswith(")"):
        depth = 0
        for i, ch in enumerate(expr):
            depth += ch == "("
            depth -= ch == ")"
            if depth == 0 and i < len(expr) - 1:
                break
        else:
            return expr
    return f"({expr})"


# Names and literals can be used twice without a temporary.
def is_simple(expr: str) -> bool:
    stripped = expr.strip("()-")
    return stripped.replace("_", "").replace(".", "").isalnum()


# -- the generator ---------------------------------------------------------
# C doesn't fix the order operands and arguments are evaluated in, and Bork
# runs left to right. So anything that reads or changes state (calls, globals,
# indexing, fields, builtins) goes into a temporary in source order, and only
# pure arithmetic stays inline. Locals are safe as they are: with no closures,
# nothing else can touch them.
class CGenerator:
    def __init__(self, checker: Checker, filename: str = "<input>"):
        self.checker = checker
        self.filename = filename
        self.fn_typedefs: dict[str, str] = {}       # str(FnType) -> typedef name
        self.typedef_lines: list[str] = []
        self.shows: dict[str, T.Type] = {}          # show function name -> type
        self.show_queue: list[T.Type] = []
        self.strings: dict[str, str] = {}           # constant text -> C name
        # per-function state
        self.out: list[str] = []
        self.depth = 1
        self.ntemp = 0
        self.line = 0
        self.marked: int | None = None
        self.in_entry = False

    # -- types -------------------------------------------------------------
    def ctype(self, ty) -> str:
        if ty is T.INT:
            return "int64_t"
        if ty is T.FLOAT:
            return "double"
        if ty is T.BOOL:
            return "bool"
        if ty is T.STR:
            return "BorkStr *"
        if ty is T.UNIT:
            return "bork_unit"
        if isinstance(ty, T.ArrayType):
            return "BorkArr *"
        if isinstance(ty, T.StructType):
            return f"S_{ty.name} *"
        if isinstance(ty, T.FnType):
            key = str(ty)
            if key not in self.fn_typedefs:
                params = ", ".join(self.ctype(p) for p in ty.params) or "void"
                ret = self.ctype(ty.ret)
                name = f"bork_fn{len(self.fn_typedefs)}"
                self.fn_typedefs[key] = name
                self.typedef_lines.append(f"typedef {ret} (*{name})({params});"
                                          f"   /* {c_comment(key)} */")
            return self.fn_typedefs[key]
        raise AssertionError(f"no C type for {ty}")

    def decl(self, ty, name: str) -> str:
        ct = self.ctype(ty)
        return f"{ct}{name}" if ct.endswith("*") else f"{ct} {name}"

    @staticmethod
    def member(ty) -> str:
        if ty is T.INT:
            return "i"
        if ty is T.FLOAT:
            return "f"
        if ty is T.BOOL:
            return "b"
        if ty is T.STR:
            return "s"
        if ty is T.UNIT:
            return "u"
        if isinstance(ty, T.ArrayType):
            return "a"
        if isinstance(ty, T.StructType):
            return "p"
        if isinstance(ty, T.FnType):
            return "fn"
        raise AssertionError(f"no BorkV member for {ty}")

    def to_v(self, ty, expr: str) -> str:
        if isinstance(ty, T.FnType):
            return f"(BorkV){{.fn = (void (*)(void)){expr}}}"
        return f"(BorkV){{.{self.member(ty)} = {expr}}}"

    def from_v(self, ty, expr: str) -> str:
        if isinstance(ty, T.StructType):
            return f"((S_{ty.name} *){expr}.p)"
        if isinstance(ty, T.FnType):
            return f"(({self.ctype(ty)}){expr}.fn)"
        return f"{expr}.{self.member(ty)}"

    # Show functions are generated on demand, one per type.
    def show(self, ty) -> str:
        if ty is T.INT:
            return "bork_show_int"
        if ty is T.FLOAT:
            return "bork_show_float"
        if ty is T.BOOL:
            return "bork_show_bool"
        if ty is T.STR:
            return "bork_show_str"
        if ty is T.UNIT:
            return "bork_show_unit"
        if isinstance(ty, T.FnType):
            return "bork_show_fn"
        name = "bork_show_" + self.mangle(ty)
        if name not in self.shows:
            self.shows[name] = ty
            self.show_queue.append(ty)
        return name

    def mangle(self, ty) -> str:
        if isinstance(ty, T.ArrayType):
            return "arr_" + self.mangle(ty.elem)
        if isinstance(ty, T.StructType):
            return "S_" + ty.name
        if isinstance(ty, T.FnType):
            return "fn"
        return str(ty)

    # -- names -------------------------------------------------------------
    @staticmethod
    def var(info: VarInfo) -> str:
        if info.kind == "global":
            return f"g{info.slot}_{info.name}"
        return f"v{info.slot}_{info.name}"

    @staticmethod
    def fn_name(fn: A.FnDecl) -> str:
        return f"fn_{fn.name}"

    def string_const(self, text: str) -> str:
        if text not in self.strings:
            self.strings[text] = f"bork_k{len(self.strings)}"
        return self.strings[text]

    # -- output ------------------------------------------------------------
    def w(self, text: str) -> None:
        self.out.append("    " * self.depth + text)

    def open(self, header: str) -> None:
        self.w(f"{header} {{" if header else "{")
        self.depth += 1
        self.marked = None

    def close(self, trailer: str = "") -> None:
        self.depth -= 1
        self.w("}" + trailer)
        self.marked = None

    def temp(self, ty, expr: str) -> str:
        self.ntemp += 1
        name = f"t{self.ntemp}"
        self.w(f"{self.decl(ty, name)} = {expr};")
        return name

    def atom(self, ty, expr: str) -> str:
        return expr if is_simple(expr) else self.temp(ty, expr)

    # -- line tracking -----------------------------------------------------
    # Same visits, same order as compiler.py, so both back ends blame the same
    # line, even for a call whose arguments span several lines.
    def set_line(self, span) -> None:
        line = getattr(span, "line", 0)
        if line:
            self.line = line

    # Before anything that can fail, so the traceback names this line.
    def mark(self) -> None:
        if self.marked != self.line:
            self.w(f"fr.line = {self.line};")
            self.marked = self.line

    # -- driver ------------------------------------------------------------
    def generate(self, module: A.Module) -> str:
        checker = self.checker
        functions = []
        for fn in checker.functions:
            functions.append(self.function(fn))
        entry = self.entry(module)

        struct_bodies = []
        for st in checker.struct_order:
            fields = "".join(f"    {self.decl(t, 'f_' + n)};\n"
                             for n, t in zip(st.field_names, st.field_types))
            struct_bodies.append(f"struct S_{st.name} {{\n{fields}}};")

        show_protos, show_bodies = self.show_functions()

        parts = [f"/* Generated by borkc from {c_comment(self.filename)}. Do not edit. */\n",
                 _runtime_source()]
        if checker.struct_order:
            parts.append("/* ---- structs ---- */")
            parts += [f"typedef struct S_{st.name} S_{st.name};" for st in checker.struct_order]
        if self.typedef_lines:
            parts.append("\n/* ---- function types ---- */")
            parts += self.typedef_lines
        if struct_bodies:
            parts.append("")
            parts += struct_bodies

        if checker.functions:
            parts.append("\n/* ---- prototypes ---- */")
            parts += [self.prototype(fn) + ";" for fn in checker.functions]

        # How a function value prints: `<fn name>`.
        parts.append("\nstatic const struct { void (*fn)(void); const char *name; } bork_fn_table[] = {")
        for fn in checker.functions:
            parts.append(f"    {{(void (*)(void)){self.fn_name(fn)}, {c_string(fn.name)}}},")
        parts.append("    {NULL, NULL},")
        parts.append("};")
        parts.append(SHOW_FN)
        if show_protos:
            parts.append("/* ---- display ---- */")
            parts += show_protos
            parts.append("")
            parts += show_bodies

        parts.append("\n/* ---- string constants ---- */")
        for text, name in self.strings.items():
            parts.append(f"static BorkStr *{name};   /* {c_comment(repr(text))} */")
        parts.append("\nstatic void bork_init_strings(void) {")
        for text, name in self.strings.items():
            if all(ord(c) < 0x80 for c in text):
                parts.append(f"    {name} = bork_str_ascii({c_string(text)}, {len(text)});")
            else:
                cps = ", ".join(str(ord(c)) for c in text)
                parts.append(f"    static const uint32_t {name}_cp[] = {{{cps}}};")
                parts.append(f"    {name} = bork_str_cps({name}_cp, {len(text)});")
        parts.append("}")

        if checker.globals:
            parts.append("\n/* ---- globals ---- */")
            for info in sorted(checker.globals.values(), key=lambda i: i.slot):
                name = self.var(info)
                parts.append(f"static {self.decl(info.ty, name)};")
                parts.append(f"static bool {name}_ok;")

        parts.append("\n/* ---- program ---- */")
        parts += functions
        parts.append(entry)
        parts.append(MAIN.replace("@SOURCE@", c_string(self.filename)))
        return "\n".join(p for p in parts if p is not None) + "\n"

    def show_functions(self):
        protos, bodies = [], []
        while self.show_queue:
            ty = self.show_queue.pop(0)
            name = "bork_show_" + self.mangle(ty)
            protos.append(f"static void {name}(BorkBuf *b, BorkV v, bool repr);")
            if isinstance(ty, T.ArrayType):
                inner = self.show(ty.elem)
                bodies.append(
                    f"static void {name}(BorkBuf *b, BorkV v, bool repr) {{\n"
                    f"    (void)repr;\n"
                    f"    bork_put(b, '[');\n"
                    f"    for (int64_t i = 0; i < v.a->len; i++) {{\n"
                    f"        if (i) bork_put_ascii(b, \", \");\n"
                    f"        {inner}(b, v.a->data[i], true);\n"
                    f"    }}\n"
                    f"    bork_put(b, ']');\n"
                    f"}}\n")
            else:
                lines = [f"static void {name}(BorkBuf *b, BorkV v, bool repr) {{",
                         "    (void)repr;",
                         f"    S_{ty.name} *s = v.p;",
                         f"    bork_put_ascii(b, {c_string(ty.name + '{')});"]
                for i, (fname, ftype) in enumerate(zip(ty.field_names, ty.field_types)):
                    sep = ", " if i else ""
                    lines.append(f"    bork_put_ascii(b, {c_string(sep + fname + ': ')});")
                    lines.append(f"    {self.show(ftype)}(b, {self.to_v(ftype, 's->f_' + fname)}, true);")
                lines.append("    bork_put(b, '}');")
                lines.append("}\n")
                bodies.append("\n".join(lines))
        return protos, bodies

    def prototype(self, fn: A.FnDecl) -> str:
        params = ", ".join(self.decl(t, self.var(p.info)) for p, t in zip(fn.params, fn.ty.params))
        ret = self.ctype(fn.ty.ret)
        sep = "" if ret.endswith("*") else " "
        return f"static {ret}{sep}{self.fn_name(fn)}({params or 'void'})"

    def begin_function(self) -> None:
        self.out = []
        self.depth = 1
        self.ntemp = 0
        self.line = 0
        self.marked = None

    def function(self, fn: A.FnDecl) -> str:
        self.begin_function()
        self.in_entry = False
        self.set_line(fn.span)
        self.w(f"BORK_ENTER({c_string(fn.name)});")
        self.body(fn.body)
        if fn.ty.ret is T.UNIT:
            self.w("BORK_LEAVE();")
            self.w("return 0;")
        else:
            self.w("abort();   /* the checker proved every path returns */")
        signature = ", ".join(f"{p.name}: {t}" for p, t in zip(fn.params, fn.ty.params))
        ret = f" -> {fn.ty.ret}" if fn.ty.ret is not T.UNIT else ""
        comment = f"/* fn {c_comment(fn.name + '(' + signature + ')' + ret)} */"
        return "\n".join([comment, self.prototype(fn) + " {", *self.out, "}\n"])

    def entry(self, module: A.Module) -> str:
        self.begin_function()
        self.in_entry = True
        self.w('BORK_ENTER("<main>");')
        for stmt in module.stmts:
            if isinstance(stmt, (A.FnDecl, A.StructDecl)):
                continue
            self.stmt(stmt)
        main = self.checker.main_fn
        if main is not None:
            self.set_line(main.span)
            self.mark()
            self.w(f"{self.fn_name(main)}();")
        self.w("BORK_LEAVE();")
        return "\n".join(["/* top-level statements, then main */",
                          "static void bork_entry(void) {", *self.out, "}\n"])

    # -- statements --------------------------------------------------------
    def stmt(self, node) -> None:
        self.set_line(node.span)
        getattr(self, "_stmt_" + type(node).__name__)(node)

    def _stmt_Block(self, node: A.Block) -> None:
        self.open("")
        for s in node.stmts:
            self.stmt(s)
        self.close()

    # Loop and `if` bodies already have braces of their own.
    def body(self, block: A.Block) -> None:
        self.set_line(block.span)
        for s in block.stmts:
            self.stmt(s)

    def _stmt_LetStmt(self, node: A.LetStmt) -> None:
        value = self.expr(node.init)
        self.store(node.info, value, declare=True)

    def _stmt_ExprStmt(self, node: A.ExprStmt) -> None:
        value = self.expr(node.expr)
        if not is_simple(value):
            self.w(f"(void)({value});")

    def _stmt_ReturnStmt(self, node: A.ReturnStmt) -> None:
        value = "0" if node.value is None else self.expr(node.value)
        self.w("BORK_LEAVE();")
        self.w(f"return {value};")

    def _stmt_IfStmt(self, node: A.IfStmt) -> None:
        cond = self.expr(node.cond)
        self.open(f"if {paren(cond)}")
        self.body(node.then)
        if node.otherwise is None:
            self.close()
            return
        self.depth -= 1
        self.w("} else {")
        self.depth += 1
        self.marked = None
        if isinstance(node.otherwise, A.Block):
            self.body(node.otherwise)
        else:
            self.stmt(node.otherwise)
        self.close()

    def _stmt_WhileStmt(self, node: A.WhileStmt) -> None:
        # The condition may need statements of its own, so it goes inside.
        self.open("for (;;)")
        cond = self.expr(node.cond)
        self.w(f"if (!{paren(cond)}) break;")
        self.body(node.body)
        self.close()

    def _stmt_ForRange(self, node: A.ForRange) -> None:
        self.open("")
        start = self.expr(node.start)
        var = self.var(node.info)
        self.w(f"int64_t {var} = {start};")
        end = self.expr(node.end)
        limit = f"v{node.limit_slot}_limit"
        self.w(f"int64_t {limit} = {end};")
        # `continue` runs the increment, as in the VM; i < limit rules out overflow.
        self.open(f"for (; {var} < {limit}; {var}++)")
        self.body(node.body)
        self.close()
        self.close()

    def _stmt_ForIn(self, node: A.ForIn) -> None:
        self.open("")
        iterable = self.expr(node.iterable)
        seq = f"v{node.arr_slot}_seq"
        idx = f"v{node.idx_slot}_idx"
        is_str = node.iterable.ty is T.STR
        self.w(f"{'BorkStr' if is_str else 'BorkArr'} *{seq} = {iterable};")
        # The length is re-read every time round, because the body may push.
        self.open(f"for (int64_t {idx} = 0; {idx} < {seq}->len; {idx}++)")
        item = f"bork_char({seq}->cp[{idx}])" if is_str else self.from_v(node.info.ty, f"{seq}->data[{idx}]")
        self.w(f"{self.decl(node.info.ty, self.var(node.info))} = {item};")
        self.body(node.body)
        self.close()
        self.close()

    def _stmt_BreakStmt(self, node) -> None:
        self.w("break;")

    def _stmt_ContinueStmt(self, node) -> None:
        self.w("continue;")

    def _stmt_AssignStmt(self, node: A.AssignStmt) -> None:
        target, op = node.target, node.op
        compound = op != "="
        ty = target.ty

        if isinstance(target, A.Ident):
            current = self.load(target.ref) if compound else None
            value = self.expr(node.value)
            if compound:
                value = self.binary(node.kind, op[0], current, value)
            self.store(target.ref, value)
            return

        if isinstance(target, A.Index):
            obj = self.atom(target.obj.ty, self.expr(target.obj))
            index = self.atom(T.INT, self.expr(target.index))
            if compound:
                self.mark()
                current = self.temp(ty, self.from_v(ty, f"bork_arr_get({obj}, {index})"))
                value = self.binary(node.kind, op[0], current, self.expr(node.value))
            else:
                value = self.expr(node.value)
            self.mark()
            self.w(f"bork_arr_set({obj}, {index}, {self.to_v(ty, value)});")
            return

        if isinstance(target, A.FieldAccess):
            obj = self.atom(target.obj.ty, self.expr(target.obj))
            field = f"{obj}->f_{target.name}"
            if compound:
                current = self.temp(ty, field)
                value = self.binary(node.kind, op[0], current, self.expr(node.value))
            else:
                value = self.expr(node.value)
            self.w(f"{field} = {value};")
            return

        raise AssertionError("unreachable: invalid assignment target survived checking")

    # -- storage -----------------------------------------------------------
    def load(self, ref) -> str:
        if isinstance(ref, A.FnDecl):
            return self.fn_name(ref)
        name = self.var(ref)
        if ref.kind == "local":
            return name
        # A function can run before a global's initialiser has, so reads there
        # are checked. Top-level code only sees globals declared above it.
        if not self.in_entry:
            self.mark()
            self.w(f"if (!{name}_ok) bork_uninit({c_string(ref.name)});")
        return self.temp(ref.ty, name)

    def store(self, info: VarInfo, value: str, declare: bool = False) -> None:
        name = self.var(info)
        if info.kind == "local":
            self.w(f"{self.decl(info.ty, name) if declare else name} = {value};")
            return
        self.w(f"{name} = {value};")
        if declare or not self.in_entry:
            self.w(f"{name}_ok = true;")

    # -- expressions -------------------------------------------------------
    # Emits the statements `node` needs and returns a C expression for its value.
    # That expression is pure, so it can be used later without changing behaviour.
    def expr(self, node) -> str:
        self.set_line(node.span)
        return getattr(self, "_expr_" + type(node).__name__)(node)

    def _expr_IntLit(self, node) -> str:
        return c_int(node.value)

    def _expr_FloatLit(self, node) -> str:
        return c_float(node.value)

    def _expr_BoolLit(self, node) -> str:
        return "true" if node.value else "false"

    def _expr_StrLit(self, node) -> str:
        return self.string_const(node.value)

    def _expr_Ident(self, node: A.Ident) -> str:
        return self.load(node.ref)

    def _expr_Unary(self, node: A.Unary) -> str:
        operand = self.expr(node.operand)
        if node.op == "!":
            return f"(!{operand})"
        if node.kind == "int":
            return f"BORK_NEG({operand})"
        return f"(-{operand})"

    def _expr_Binary(self, node: A.Binary) -> str:
        left = self.expr(node.left)
        right = self.expr(node.right)
        if node.op in ("==", "!=", "<", "<=", ">", ">="):
            return self.compare(node, left, right)
        return self.binary(node.kind, node.op, left, right)

    def binary(self, kind: str, op: str, left: str, right: str) -> str:
        if kind == "int":
            if op in ("/", "%"):
                self.mark()
                helper = "bork_idiv" if op == "/" else "bork_imod"
                return self.temp(T.INT, f"{helper}({left}, {right})")
            macro = {"+": "BORK_ADD", "-": "BORK_SUB", "*": "BORK_MUL"}[op]
            return f"{macro}({left}, {right})"
        if kind == "float":
            if op == "%":
                return f"bork_fmod({left}, {right})"
            return f"({left} {op} {right})"
        if kind == "str":
            return f"bork_concat({left}, {right})"
        raise AssertionError(f"no C for {kind} {op}")

    def compare(self, node: A.Binary, left: str, right: str) -> str:
        if node.left.ty is T.STR:
            if node.op == "==":
                return f"bork_str_eq({left}, {right})"
            if node.op == "!=":
                return f"(!bork_str_eq({left}, {right}))"
            return f"(bork_str_cmp({left}, {right}) {node.op} 0)"
        return f"({left} {node.op} {right})"

    def _expr_Logical(self, node: A.Logical) -> str:
        left = self.expr(node.left)
        result = self.temp(T.BOOL, left)
        self.open(f"if ({result})" if node.op == "&&" else f"if (!{result})")
        right = self.expr(node.right)
        self.w(f"{result} = {right};")
        self.close()
        return result

    def _expr_ArrayLit(self, node: A.ArrayLit) -> str:
        items = [self.expr(item) for item in node.elements]
        elem = node.ty.elem
        arr = self.temp(node.ty, f"bork_arr_new({len(items)})")
        for i, item in enumerate(items):
            self.w(f"{arr}->data[{i}] = {self.to_v(elem, item)};")
        return arr

    def _expr_StructLit(self, node: A.StructLit) -> str:
        st = node.def_
        # Field initialisers run in declaration order, not source order.
        values = [self.expr(node.fields[i][1]) for i in node.order]
        obj = self.temp(st, f"bork_alloc(sizeof(S_{st.name}))")
        for fname, value in zip(st.field_names, values):
            self.w(f"{obj}->f_{fname} = {value};")
        return obj

    def _expr_FieldAccess(self, node: A.FieldAccess) -> str:
        obj = self.expr(node.obj)
        return self.temp(node.ty, f"{obj}->f_{node.name}")

    def _expr_Index(self, node: A.Index) -> str:
        obj = self.expr(node.obj)
        index = self.expr(node.index)
        self.mark()
        if node.obj.ty is T.STR:
            return self.temp(T.STR, f"bork_str_index({obj}, {index})")
        return self.temp(node.ty, self.from_v(node.ty, f"bork_arr_get({obj}, {index})"))

    def _expr_Call(self, node: A.Call) -> str:
        if node.builtin is not None:
            return self.builtin(node)
        callee = self.expr(node.callee)
        args = [self.expr(a) for a in node.args]
        self.mark()
        call = f"{callee}({', '.join(args)})"
        if node.ty is T.UNIT:
            self.w(call + ";")
            return "0"
        return self.temp(node.ty, call)

    def builtin(self, node: A.Call) -> str:
        name = node.builtin
        args = [self.expr(a) for a in node.args]
        tys = [a.ty for a in node.args]
        if name in FALLIBLE_BUILTINS:
            self.mark()

        if name == "print":
            ty = tys[0]
            if ty is T.STR:
                self.w(f"bork_print({args[0]});")
            elif ty is T.INT:
                self.w(f"bork_print_int({args[0]});")
            else:
                self.w(f"bork_print(bork_to_str({self.show(ty)}, {self.to_v(ty, args[0])}));")
            return "0"
        if name == "len":
            return self.temp(T.INT, f"{args[0]}->len")
        if name == "str":
            if tys[0] is T.STR:
                return args[0]
            return self.temp(T.STR, f"bork_to_str({self.show(tys[0])}, {self.to_v(tys[0], args[0])})")
        if name == "int":
            ty = tys[0]
            expr = {T.INT: "{}", T.BOOL: "({} ? 1 : 0)", T.FLOAT: "bork_float_to_int({})",
                    T.STR: "bork_parse_int({})"}[ty].format(args[0])
            return self.temp(T.INT, expr)
        if name == "float":
            ty = tys[0]
            expr = {T.INT: "(double){}", T.FLOAT: "{}", T.STR: "bork_parse_float({})"}[ty].format(args[0])
            return self.temp(T.FLOAT, expr)
        if name == "push":
            self.w(f"bork_arr_push({args[0]}, {self.to_v(tys[0].elem, args[1])});")
            return "0"
        if name == "pop":
            return self.temp(node.ty, self.from_v(node.ty, f"bork_arr_pop({args[0]})"))
        if name == "sqrt":
            helper = "bork_sqrt_int" if tys[0] is T.INT else "bork_sqrt_float"
            return self.temp(T.FLOAT, f"{helper}({args[0]})")
        if name == "abs":
            helper = "bork_iabs" if tys[0] is T.INT else "fabs"
            return self.temp(node.ty, f"{helper}({args[0]})")
        if name in ("min", "max"):
            # Exactly the VM's comparison, which matters for NaN.
            cmp = "<=" if name == "min" else ">="
            a, b = (self.atom(node.ty, x) for x in args)
            return self.temp(node.ty, f"{a} {cmp} {b} ? {a} : {b}")
        if name == "chr":
            return self.temp(T.STR, f"bork_chr({args[0]})")
        if name == "ord":
            return self.temp(T.INT, f"bork_ord({args[0]})")
        if name == "substr":
            return self.temp(T.STR, f"bork_substr({', '.join(args)})")
        if name == "clock":
            return self.temp(T.FLOAT, "bork_clock()")
        raise AssertionError(f"no C for builtin {name}")


SHOW_FN = r'''
static void bork_show_fn(BorkBuf *b, BorkV v, bool repr) {
    (void)repr;
    bork_put_ascii(b, "<fn ");
    for (int i = 0; bork_fn_table[i].fn; i++)
        if (bork_fn_table[i].fn == v.fn) { bork_put_ascii(b, bork_fn_table[i].name); break; }
    bork_put(b, '>');
}
'''

MAIN = r'''static void *bork_thread(void *arg) {
    (void)arg;
    bork_init_strings();
    bork_entry();
    return NULL;
}

int main(void) {
    bork_source = @SOURCE@;
    static char outbuf[1 << 16];
    setvbuf(stdout, outbuf, isatty(STDOUT_FILENO) ? _IOLBF : _IOFBF, sizeof outbuf);
    /* Bork allows 20,000 nested calls; give them a stack that can hold them. */
    pthread_attr_t attr;
    pthread_t thread;
    pthread_attr_init(&attr);
    pthread_attr_setstacksize(&attr, (size_t)256 << 20);
    if (pthread_create(&thread, &attr, bork_thread, NULL) == 0)
        pthread_join(thread, NULL);
    else
        bork_thread(NULL);
    fflush(stdout);
    return 0;
}'''


_runtime_cache: str | None = None


def _runtime_source() -> str:
    global _runtime_cache
    if _runtime_cache is None:
        with open(RUNTIME_PATH, encoding="utf-8") as handle:
            _runtime_cache = handle.read()
    return _runtime_cache


# -- entry points ----------------------------------------------------------
def generate(module: A.Module, checker: Checker, filename: str = "<input>") -> str:
    return CGenerator(checker, filename).generate(module)


def to_c(source: str, filename: str = "<input>", optimise: bool = True) -> str:
    from . import compile_source
    result = compile_source(source, filename, optimise)
    return generate(result.module, result.checker, filename)


# The .c file is kept next to the binary by default; reading it is half the point.
def compile_c(c_source: str, out_path: str, cc: str | None = None, keep_c: bool = True) -> str:
    cc = cc or os.environ.get("CC", "cc")
    if keep_c:
        c_path = os.path.splitext(out_path)[0] + ".c"
        if os.path.abspath(c_path) == os.path.abspath(out_path):
            c_path = out_path + ".c"
        with open(c_path, "w", encoding="utf-8") as handle:
            handle.write(c_source)
    else:
        handle = tempfile.NamedTemporaryFile("w", suffix=".c", delete=False, encoding="utf-8")
        handle.write(c_source)
        handle.close()
        c_path = handle.name

    try:
        proc = subprocess.run([cc, *CFLAGS, c_path, "-o", out_path, *LIBS],
                              capture_output=True, text=True)
    except FileNotFoundError:
        raise CBackendError(f"no C compiler found (tried {cc!r}; set $CC to choose one)") from None
    finally:
        if not keep_c:
            os.unlink(c_path)

    if proc.returncode != 0:
        raise CBackendError(f"{cc} rejected the generated C:\n{proc.stderr.strip()}")
    return c_path


def build(source: str, out_path: str, filename: str = "<input>", optimise: bool = True,
          cc: str | None = None, keep_c: bool = True) -> str:
    return compile_c(to_c(source, filename, optimise), out_path, cc=cc, keep_c=keep_c)
