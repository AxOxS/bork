"""Semantic analysis: name resolution, type checking and storage allocation.

The checker runs in passes so declarations can be used before the point they
appear:

  1. struct names, then struct field types (allows mutually recursive shapes)
  2. function signatures
  3. top-level statements in order (this is where globals get their slots)
  4. function bodies, with every global and function already visible

It annotates the AST in place: expressions get `.ty`, identifiers get `.ref`,
and every binding gets a storage slot. The code generator then never has to ask
a question about names or types, and neither does the VM.

Errors are collected rather than raised at the first one, so a single run can
report everything it found.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import ast_nodes as A
from . import builtins as B
from . import types as T
from .errors import Diagnostic, LumenError, Span


@dataclass
class VarInfo:
    name: str
    ty: T.Type
    mutable: bool
    kind: str          # 'global' | 'local'
    slot: int
    span: Span


class FnCtx:
    """Per-function storage allocation and return-type context."""

    def __init__(self, name: str, ret: T.Type):
        self.name = name
        self.ret = ret
        self.nlocals = 0

    def alloc(self) -> int:
        slot = self.nlocals
        self.nlocals += 1
        return slot


ARITH = {"+", "-", "*", "/", "%"}
ORDERING = {"<", "<=", ">", ">="}
EQUALITY = {"==", "!="}


class Checker:
    def __init__(self, source: str = "", filename: str = "<input>"):
        self.source = source
        self.filename = filename
        self.errors: list[Diagnostic] = []

        self.structs: dict[str, T.StructType] = {}
        self.struct_order: list[T.StructType] = []
        self.functions: list[A.FnDecl] = []
        self.fn_decls: dict[str, A.FnDecl] = {}
        self.globals: dict[str, VarInfo] = {}
        self.nglobals = 0
        self.main_fn: A.FnDecl | None = None

        self.scopes: list[dict[str, VarInfo]] = []
        self.ctx: FnCtx | None = None
        self.loop_depth = 0
        self.entry_ctx = FnCtx("<main>", T.UNIT)

    # -- diagnostics -------------------------------------------------------
    def error(self, msg: str, span: Span, note: str | None = None) -> None:
        self.errors.append(Diagnostic(msg, span, note=note))

    # -- scopes ------------------------------------------------------------
    def push_scope(self) -> None:
        self.scopes.append({})

    def pop_scope(self) -> None:
        self.scopes.pop()

    def declare(self, name: str, ty: T.Type, mutable: bool, span: Span) -> VarInfo:
        if self.scopes:
            scope = self.scopes[-1]
            if name in scope:
                self.error(f"'{name}' is already declared in this scope", span,
                           note=f"previous declaration at line {scope[name].span.line}")
            ctx = self.ctx or self.entry_ctx
            info = VarInfo(name, ty, mutable, "local", ctx.alloc(), span)
            scope[name] = info
            return info
        if name in self.globals:
            self.error(f"'{name}' is already declared", span,
                       note=f"previous declaration at line {self.globals[name].span.line}")
        if name in self.fn_decls:
            self.error(f"'{name}' is already declared as a function", span)
        info = VarInfo(name, ty, mutable, "global", self.alloc_global(), span)
        self.globals[name] = info
        return info

    def alloc_global(self) -> int:
        slot = self.nglobals
        self.nglobals += 1
        return slot

    def lookup(self, name: str) -> VarInfo | None:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return self.globals.get(name)

    # -- type expressions --------------------------------------------------
    def resolve_type(self, node: A.Node | None) -> T.Type:
        if node is None:
            return T.UNIT
        if isinstance(node, A.TypeName):
            if node.name in T.PRIMITIVES:
                return T.PRIMITIVES[node.name]
            if node.name in self.structs:
                return self.structs[node.name]
            self.error(f"unknown type '{node.name}'", node.span)
            return T.ERROR
        if isinstance(node, A.TypeArray):
            return T.ArrayType(self.resolve_type(node.elem))
        if isinstance(node, A.TypeFn):
            return T.FnType([self.resolve_type(p) for p in node.params], self.resolve_type(node.ret))
        raise AssertionError(f"unhandled type node {node!r}")

    # -- driver ------------------------------------------------------------
    def check_module(self, module: A.Module) -> A.Module:
        decls = module.stmts

        # Pass 1a: struct names (so fields may refer to any struct).
        for stmt in decls:
            if isinstance(stmt, A.StructDecl):
                if stmt.name in self.structs:
                    self.error(f"struct '{stmt.name}' is already declared", stmt.span)
                    continue
                if stmt.name in T.PRIMITIVES:
                    self.error(f"'{stmt.name}' is a built-in type name", stmt.span)
                    continue
                st = T.StructType(stmt.name, [], [])
                self.structs[stmt.name] = st
                self.struct_order.append(st)
                stmt.ty = st

        # Pass 1b: struct field types.
        for stmt in decls:
            if isinstance(stmt, A.StructDecl) and stmt.ty is not None:
                st = stmt.ty
                for fname, ftype, fspan in stmt.fields:
                    if fname in st.field_names:
                        self.error(f"duplicate field '{fname}' in struct '{stmt.name}'", fspan)
                        continue
                    st.field_names.append(fname)
                    st.field_types.append(self.resolve_type(ftype))
                if not st.field_names:
                    self.error(f"struct '{stmt.name}' must have at least one field", stmt.span)

        # Pass 2: function signatures, so any function can call any other.
        for stmt in decls:
            if isinstance(stmt, A.FnDecl):
                self.declare_function(stmt)

        # Pass 3: top-level statements in source order.
        for stmt in decls:
            if isinstance(stmt, (A.FnDecl, A.StructDecl)):
                continue
            self.check_stmt(stmt)

        # Pass 4: function bodies.
        for fn in self.functions:
            self.check_fn_body(fn)

        if self.errors:
            raise LumenError(self.errors, self.source, self.filename)
        module.entry_nlocals = self.entry_ctx.nlocals
        return module

    def declare_function(self, fn: A.FnDecl) -> None:
        if fn.name in self.fn_decls:
            self.error(f"function '{fn.name}' is already declared", fn.span,
                       note=f"previous declaration at line {self.fn_decls[fn.name].span.line}")
            return
        if B.lookup(fn.name):
            self.error(f"'{fn.name}' shadows the built-in function of the same name", fn.span,
                       note="pick a different name; built-ins cannot be redefined")
            return
        params = [self.resolve_type(p.type_expr) for p in fn.params]
        ret = self.resolve_type(fn.ret_type)
        fn.ty = T.FnType(params, ret)
        fn.global_slot = self.alloc_global()
        self.fn_decls[fn.name] = fn
        self.functions.append(fn)
        if fn.name == "main":
            if fn.params:
                self.error("'main' must take no parameters", fn.span)
            elif ret is not T.UNIT:
                self.error(f"'main' must not return a value, found `{ret}`", fn.span)
            else:
                self.main_fn = fn

    def check_fn_body(self, fn: A.FnDecl) -> None:
        self.ctx = FnCtx(fn.name, fn.ty.ret)
        self.push_scope()
        for param, ty in zip(fn.params, fn.ty.params):
            param.info = self.declare(param.name, ty, True, param.span)
        self.check_block(fn.body, new_scope=False)
        self.pop_scope()
        fn.nlocals = self.ctx.nlocals
        if fn.ty.ret is not T.UNIT and not always_returns(fn.body):
            self.error(f"function '{fn.name}' must return a value of type `{fn.ty.ret}` on all paths",
                       fn.span, note="add a `return` at the end of the function body")
        self.ctx = None

    # -- statements --------------------------------------------------------
    def check_block(self, block: A.Block, new_scope: bool = True) -> None:
        if new_scope:
            self.push_scope()
        for stmt in block.stmts:
            self.check_stmt(stmt)
        if new_scope:
            self.pop_scope()

    def check_stmt(self, stmt: A.Stmt) -> None:
        method = getattr(self, "_stmt_" + type(stmt).__name__, None)
        if method is None:
            raise AssertionError(f"unhandled statement {type(stmt).__name__}")
        method(stmt)

    def _stmt_FnDecl(self, stmt: A.FnDecl) -> None:
        self.error("functions can only be declared at the top level", stmt.span,
                   note="Lumen has no closures, so nested functions are not allowed")

    def _stmt_StructDecl(self, stmt: A.StructDecl) -> None:
        self.error("structs can only be declared at the top level", stmt.span)

    def _stmt_ReturnStmt(self, stmt: A.ReturnStmt) -> None:
        if self.ctx is None:
            self.error("`return` outside of a function", stmt.span)
            if stmt.value is not None:
                self.check_expr(stmt.value)
            return
        expected = self.ctx.ret
        if stmt.value is None:
            if expected is not T.UNIT:
                self.error(f"function '{self.ctx.name}' must return a value of type `{expected}`",
                           stmt.span)
            return
        actual = self.check_expr(stmt.value, expected=expected)
        if expected is T.UNIT:
            self.error(f"function '{self.ctx.name}' returns nothing, but this `return` has a value",
                       stmt.value.span)
        elif not T.compatible(expected, actual):
            self.error(f"expected return type `{expected}`, found `{actual}`", stmt.value.span)

    def _stmt_LetStmt(self, stmt: A.LetStmt) -> None:
        declared = self.resolve_type(stmt.type_expr) if stmt.type_expr else None
        actual = self.check_expr(stmt.init, expected=declared)
        if actual is T.UNIT:
            self.error(f"cannot bind '{stmt.name}' to a value of type `unit`", stmt.init.span)
            actual = T.ERROR
        if declared is not None and not T.compatible(declared, actual):
            self.error(f"expected `{declared}` in the initialiser of '{stmt.name}', found `{actual}`",
                       stmt.init.span)
        ty = declared if declared is not None else actual
        stmt.info = self.declare(stmt.name, ty, stmt.mutable, stmt.span)

    def _stmt_ExprStmt(self, stmt: A.ExprStmt) -> None:
        self.check_expr(stmt.expr)

    def _stmt_Block(self, stmt: A.Block) -> None:
        self.check_block(stmt)

    def _stmt_IfStmt(self, stmt: A.IfStmt) -> None:
        cond = self.check_expr(stmt.cond)
        if cond is not T.BOOL and cond is not T.ERROR:
            self.error(f"`if` condition must be `bool`, found `{cond}`", stmt.cond.span)
        self.check_block(stmt.then)
        if isinstance(stmt.otherwise, A.Block):
            self.check_block(stmt.otherwise)
        elif stmt.otherwise is not None:
            self.check_stmt(stmt.otherwise)

    def _stmt_WhileStmt(self, stmt: A.WhileStmt) -> None:
        cond = self.check_expr(stmt.cond)
        if cond is not T.BOOL and cond is not T.ERROR:
            self.error(f"`while` condition must be `bool`, found `{cond}`", stmt.cond.span)
        self.loop_depth += 1
        self.check_block(stmt.body)
        self.loop_depth -= 1

    def _stmt_BreakStmt(self, stmt: A.BreakStmt) -> None:
        if self.loop_depth == 0:
            self.error("`break` outside of a loop", stmt.span)

    def _stmt_ContinueStmt(self, stmt: A.ContinueStmt) -> None:
        if self.loop_depth == 0:
            self.error("`continue` outside of a loop", stmt.span)

    def _stmt_AssignStmt(self, stmt: A.AssignStmt) -> None:
        target = stmt.target
        target_ty = self.check_expr(target)
        if isinstance(target, A.Ident):
            info = target.ref
            if isinstance(info, A.FnDecl):
                self.error(f"cannot assign to function '{target.name}'", target.span)
            elif isinstance(info, VarInfo) and not info.mutable:
                self.error(f"cannot assign to '{target.name}' because it is not mutable", target.span,
                           note=f"declare it with `var {target.name} = ...` to make it mutable")
        elif isinstance(target, A.Index):
            if target.obj.ty is T.STR:
                self.error("strings are immutable and cannot be assigned through", target.span)

        value_ty = self.check_expr(stmt.value, expected=target_ty)
        if not T.compatible(target_ty, value_ty):
            self.error(f"cannot assign `{value_ty}` to a target of type `{target_ty}`", stmt.value.span)

    # -- expressions -------------------------------------------------------
    def check_expr(self, expr: A.Expr, expected: T.Type | None = None) -> T.Type:
        method = getattr(self, "_expr_" + type(expr).__name__, None)
        if method is None:
            raise AssertionError(f"unhandled expression {type(expr).__name__}")
        ty = method(expr, expected)
        expr.ty = ty
        return ty

    def _expr_IntLit(self, e, expected):
        return T.INT

    def _expr_FloatLit(self, e, expected):
        return T.FLOAT

    def _expr_BoolLit(self, e, expected):
        return T.BOOL

    def _expr_StrLit(self, e, expected):
        return T.STR

    def _expr_ArrayLit(self, e: A.ArrayLit, expected):
        hint = expected.elem if isinstance(expected, T.ArrayType) else None
        if not e.elements:
            if hint is None:
                self.error("cannot infer the element type of an empty array", e.span,
                           note="add a type annotation, e.g. `let xs: [int] = [];`")
                return T.ERROR
            return T.ArrayType(hint)
        elem = hint
        for item in e.elements:
            ty = self.check_expr(item, expected=elem)
            if elem is None or elem is T.ERROR:
                elem = ty
            elif not T.compatible(elem, ty):
                self.error(f"array elements must all have the same type: expected `{elem}`, "
                           f"found `{ty}`", item.span)
        if elem is T.UNIT:
            self.error("arrays cannot hold `unit` values", e.span)
            return T.ERROR
        return T.ArrayType(elem)

    def _expr_StructLit(self, e: A.StructLit, expected):
        st = self.structs.get(e.name)
        if st is None:
            if e.name in T.PRIMITIVES:
                self.error(f"`{e.name}` is not a struct type", e.span)
            else:
                self.error(f"unknown struct '{e.name}'", e.span)
            for _, value, _ in e.fields:
                self.check_expr(value)
            return T.ERROR
        e.def_ = st
        seen: dict[str, int] = {}
        for i, (fname, value, fspan) in enumerate(e.fields):
            if fname in seen:
                self.error(f"field '{fname}' is initialised more than once", fspan)
            ftype, _ = st.field(fname)
            if ftype is None:
                self.error(f"struct '{st.name}' has no field '{fname}'", fspan,
                           note="fields are: " + ", ".join(st.field_names))
                self.check_expr(value)
                continue
            seen[fname] = i
            actual = self.check_expr(value, expected=ftype)
            if not T.compatible(ftype, actual):
                self.error(f"field '{fname}' of '{st.name}' has type `{ftype}`, found `{actual}`",
                           value.span)
        missing = [n for n in st.field_names if n not in seen]
        if missing:
            self.error(f"missing field{'s' if len(missing) > 1 else ''} "
                       + ", ".join(f"'{m}'" for m in missing) + f" in '{st.name}' literal", e.span)
            return T.ERROR
        # Codegen pushes fields in declaration order; record where to find each.
        e.order = [seen[n] for n in st.field_names]
        return st

    def _expr_FieldAccess(self, e: A.FieldAccess, expected):
        obj = self.check_expr(e.obj)
        if isinstance(obj, T.StructType):
            ftype, index = obj.field(e.name)
            if ftype is None:
                self.error(f"struct '{obj.name}' has no field '{e.name}'", e.span,
                           note="fields are: " + ", ".join(obj.field_names))
                return T.ERROR
            e.index = index
            return ftype
        if obj is not T.ERROR:
            note = "use `len(x)` to get a length" if e.name == "len" else None
            self.error(f"cannot access field '{e.name}' on a value of type `{obj}`", e.obj.span,
                       note=note)
        return T.ERROR

    def _expr_Index(self, e: A.Index, expected):
        obj = self.check_expr(e.obj)
        index = self.check_expr(e.index, expected=T.INT)
        if index is not T.INT and index is not T.ERROR:
            self.error(f"array index must be `int`, found `{index}`", e.index.span)
        if isinstance(obj, T.ArrayType):
            return obj.elem
        if obj is T.STR:
            return T.STR
        if obj is not T.ERROR:
            self.error(f"cannot index a value of type `{obj}`", e.obj.span)
        return T.ERROR

    def _expr_Ident(self, e: A.Ident, expected):
        info = self.lookup(e.name)
        if info is not None:
            e.ref = info
            return info.ty
        fn = self.fn_decls.get(e.name)
        if fn is not None:
            e.ref = fn
            return fn.ty
        if B.lookup(e.name):
            self.error(f"built-in '{e.name}' can only be called, not used as a value", e.span,
                       note=f"write `{e.name}(...)` to call it")
            return T.ERROR
        self.error(f"unknown name '{e.name}'", e.span)
        return T.ERROR

    def _expr_Unary(self, e: A.Unary, expected):
        ty = self.check_expr(e.operand, expected=expected if e.op == "-" else T.BOOL)
        if e.op == "-":
            if ty is T.INT:
                e.kind = "int"
            elif ty is T.FLOAT:
                e.kind = "float"
            elif ty is not T.ERROR:
                self.error(f"cannot negate a value of type `{ty}`", e.span)
                return T.ERROR
            return ty
        if ty is not T.BOOL and ty is not T.ERROR:
            self.error(f"`!` expects `bool`, found `{ty}`", e.span)
            return T.BOOL
        e.kind = "bool"
        return T.BOOL

    def binary_result(self, op: str, left: T.Type, right: T.Type, span: Span):
        """Type and codegen kind for `left op right`. Reports its own errors."""
        if left is T.ERROR or right is T.ERROR:
            return T.ERROR, "int"
        if op in ARITH:
            if left is T.INT and right is T.INT:
                return T.INT, "int"
            if left is T.FLOAT and right is T.FLOAT:
                return T.FLOAT, "float"
            if op == "+" and left is T.STR and right is T.STR:
                return T.STR, "str"
            note = None
            if {left, right} == {T.INT, T.FLOAT}:
                note = ("Lumen does not convert between numeric types implicitly; "
                        "use `float(x)` or `int(x)`")
            elif op == "+" and (left is T.STR or right is T.STR):
                note = "use `str(x)` to convert the other operand to text"
            self.error(f"cannot apply `{op}` to `{left}` and `{right}`", span, note=note)
            return T.ERROR, "int"
        if op in ORDERING:
            if left is right and left in (T.INT, T.FLOAT, T.STR):
                return T.BOOL, left.name
            self.error(f"cannot compare `{left}` with `{right}` using `{op}`", span,
                       note="ordering comparisons work on `int`, `float` and `str`")
            return T.BOOL, "int"
        if op in EQUALITY:
            if left != right:
                self.error(f"cannot compare `{left}` with `{right}`", span)
                return T.BOOL, "int"
            if isinstance(left, (T.ArrayType, T.StructType, T.FnType)):
                self.error(f"`{op}` is not defined for `{left}`", span,
                           note="compare fields or elements individually")
                return T.BOOL, "int"
            return T.BOOL, "value"
        raise AssertionError(f"unknown operator {op}")

    def _expr_Binary(self, e: A.Binary, expected):
        hint = expected if e.op in ARITH and isinstance(expected, T.Primitive) else None
        left = self.check_expr(e.left, expected=hint)
        right = self.check_expr(e.right, expected=left if left is not T.ERROR else hint)
        result, kind = self.binary_result(e.op, left, right, e.span)
        e.kind = kind
        return result

    def _expr_Logical(self, e: A.Logical, expected):
        left = self.check_expr(e.left, expected=T.BOOL)
        right = self.check_expr(e.right, expected=T.BOOL)
        for ty, node in ((left, e.left), (right, e.right)):
            if ty is not T.BOOL and ty is not T.ERROR:
                self.error(f"`{e.op}` expects `bool` operands, found `{ty}`", node.span)
        return T.BOOL

    def _expr_Call(self, e: A.Call, expected):
        callee = e.callee
        # Built-in calls are resolved statically unless a name shadows them.
        if (isinstance(callee, A.Ident) and self.lookup(callee.name) is None
                and callee.name not in self.fn_decls):
            sig = B.lookup(callee.name)
            if sig is not None:
                return self.check_builtin_call(e, sig)

        fn_ty = self.check_expr(callee)
        argtys = [self.check_expr(a) for a in e.args]
        if fn_ty is T.ERROR:
            return T.ERROR
        if not isinstance(fn_ty, T.FnType):
            self.error(f"cannot call a value of type `{fn_ty}`", callee.span)
            return T.ERROR
        name = callee.name if isinstance(callee, A.Ident) else "this function"
        if len(argtys) != len(fn_ty.params):
            self.error(f"'{name}' expects {len(fn_ty.params)} argument"
                       f"{'' if len(fn_ty.params) == 1 else 's'}, found {len(argtys)}", e.span)
            return fn_ty.ret
        for i, (want, got) in enumerate(zip(fn_ty.params, argtys)):
            if not T.compatible(want, got):
                self.error(f"argument {i + 1} of '{name}' has type `{want}`, found `{got}`",
                           e.args[i].span)
        return fn_ty.ret

    def check_builtin_call(self, e: A.Call, sig) -> T.Type:
        e.builtin = sig.name
        argtys = [self.check_expr(a) for a in e.args]
        if not B.arity_ok(sig, len(argtys)):
            want = sig.arity if isinstance(sig.arity, int) else f"{sig.arity[0]}..{sig.arity[1]}"
            self.error(f"'{sig.name}' expects {want} argument(s), found {len(argtys)}", e.span,
                       note=sig.doc)
            return T.ERROR
        return sig.check(argtys, lambda msg: self.error(msg, e.span, note=sig.doc))


# -- control-flow analysis -------------------------------------------------
def always_returns(node) -> bool:
    """Conservative: does this statement return (or diverge) on every path?"""
    if isinstance(node, A.ReturnStmt):
        return True
    if isinstance(node, A.Block):
        return any(always_returns(s) for s in node.stmts)
    if isinstance(node, A.IfStmt):
        return node.otherwise is not None and always_returns(node.then) and always_returns(node.otherwise)
    if isinstance(node, A.WhileStmt):
        # `while true { ... }` only ends by returning, unless it can break out.
        return isinstance(node.cond, A.BoolLit) and node.cond.value and not has_break(node.body)
    return False


def has_break(node) -> bool:
    """Is there a `break` that targets the enclosing loop (not a nested one)?"""
    if isinstance(node, A.BreakStmt):
        return True
    if isinstance(node, A.Block):
        return any(has_break(s) for s in node.stmts)
    if isinstance(node, A.IfStmt):
        return has_break(node.then) or (node.otherwise is not None and has_break(node.otherwise))
    return False


def check(module: A.Module, source: str = "", filename: str = "<input>") -> Checker:
    checker = Checker(source, filename)
    checker.check_module(module)
    return checker
