"""Code generation: typed AST -> stack bytecode.

A syntax-directed translation. Every expression leaves exactly one value on the
stack, which is the invariant the whole instruction set is built around.

Because the checker has annotated each operator with the type it works on, this
pass picks the instruction from a table instead of deferring the decision to
runtime.
"""
from __future__ import annotations

from . import ast_nodes as A
from . import builtins as B
from . import types as T
from .bytecode import Function, Program, StructDef
from .checker import Checker, VarInfo
from .opcodes import ARITH_OPS, COMPARE_OPS, NEG_OPS, OPERANDS, WIDTH, Op

PLACEHOLDER = 0x7FFF


class LoopCtx:
    """Jumps out of, and back to the top of, the loop being compiled.
    Both land somewhere that is not known until the loop is finished."""

    def __init__(self):
        self.breaks: list[int] = []
        self.continues: list[int] = []

class FunctionEmitter:
    def __init__(self, name: str, arity: int = 0, nlocals: int = 0, signature: str = ""):
        self.fn = Function(name, arity, nlocals, signature)
        self.const_index: dict = {}
        self.line = 0

    # -- raw emission ------------------------------------------------------
    def set_line(self, span) -> None:
        line = getattr(span, "line", 0)
        if line:
            self.line = line

    def emit(self, op: Op, *operands: int) -> int:
        offset = len(self.fn.code)
        if not self.fn.lines or self.fn.lines[-1][1] != self.line:
            self.fn.lines.append((offset, self.line))
        self.fn.code.append(int(op))
        kinds = OPERANDS.get(op, ())
        assert len(kinds) == len(operands), f"{op.name} takes {len(kinds)} operands, got {len(operands)}"
        for kind, value in zip(kinds, operands):
            self.fn.code += int(value).to_bytes(WIDTH[kind], "little", signed=(kind == "s16"))
        return offset

    def constant(self, value) -> int:
        # bool and int are distinct constants even when Python says 1 == True,
        # and so are 1 and 1.0.
        key = (type(value).__name__, value)
        if key not in self.const_index:
            self.const_index[key] = len(self.fn.consts)
            self.fn.consts.append(value)
        return self.const_index[key]

    def emit_const(self, value) -> None:
        self.emit(Op.CONST, self.constant(value))

    # -- jumps -------------------------------------------------------------
    def emit_jump(self, op: Op) -> int:
        """Emit a jump whose target is not known yet; returns the operand
        position so it can be back-patched once it is."""
        self.emit(op, PLACEHOLDER)
        return len(self.fn.code) - 2

    def patch(self, operand_pos: int, target: int | None = None) -> None:
        target = len(self.fn.code) if target is None else target
        delta = target - (operand_pos + 2)
        self.fn.code[operand_pos:operand_pos + 2] = delta.to_bytes(2, "little", signed=True)

    def emit_loop(self, target: int) -> None:
        pos = self.emit_jump(Op.JUMP)
        self.patch(pos, target)

    @property
    def here(self) -> int:
        return len(self.fn.code)


class Compiler:
    def __init__(self, checker: Checker, source_name: str = "<input>"):
        self.checker = checker
        self.program = Program(source_name)
        self.loops: list[LoopCtx] = []
        self.e: FunctionEmitter = None      # current emitter

    # -- driver ------------------------------------------------------------
    def compile_module(self, module: A.Module) -> Program:
        for i, st in enumerate(self.checker.struct_order):
            st.index = i
            self.program.structs.append(StructDef(st.name, list(st.field_names)))

        for fn in self.checker.functions:
            index = self.compile_function(fn)
            self.program.global_inits.append((fn.global_slot, index))
            self.program.global_names[fn.global_slot] = fn.name

        for name, info in self.checker.globals.items():
            self.program.global_names[info.slot] = name
        self.program.nglobals = self.checker.nglobals

        entry = FunctionEmitter("<main>", 0, getattr(module, "entry_nlocals", 0), "entry point")
        self.e = entry
        for stmt in module.stmts:
            if isinstance(stmt, (A.FnDecl, A.StructDecl)):
                continue
            self.stmt(stmt)
        main = self.checker.main_fn
        if main is not None:
            entry.set_line(main.span)
            entry.emit(Op.LOAD_GLOBAL, main.global_slot)
            entry.emit(Op.CALL, 0)
            entry.emit(Op.POP)
        entry.emit(Op.HALT)
        self.program.entry_index = self.program.add_function(entry.fn)
        return self.program

    def compile_function(self, fn: A.FnDecl) -> int:
        signature = f"fn {fn.name}({', '.join(f'{p.name}: {t}' for p, t in zip(fn.params, fn.ty.params))})"
        if fn.ty.ret is not T.UNIT:
            signature += f" -> {fn.ty.ret}"
        emitter = FunctionEmitter(fn.name, len(fn.params), fn.nlocals, signature)
        previous, self.e = self.e, emitter
        emitter.set_line(fn.span)
        self.stmt(fn.body)
        # Falling off the end of a unit function returns unit implicitly.
        emitter.emit(Op.UNIT)
        emitter.emit(Op.RET)
        self.e = previous
        return self.program.add_function(emitter.fn)

    # -- statements --------------------------------------------------------
    def stmt(self, node) -> None:
        self.e.set_line(node.span)
        method = getattr(self, "_stmt_" + type(node).__name__)
        method(node)

    def _stmt_Block(self, node: A.Block) -> None:
        for s in node.stmts:
            self.stmt(s)

    def _stmt_LetStmt(self, node: A.LetStmt) -> None:
        self.expr(node.init)
        self.store(node.info)

    def _stmt_ExprStmt(self, node: A.ExprStmt) -> None:
        self.expr(node.expr)
        self.e.emit(Op.POP)          # every expression leaves exactly one value

    def _stmt_ReturnStmt(self, node: A.ReturnStmt) -> None:
        if node.value is None:
            self.e.emit(Op.UNIT)
        else:
            self.expr(node.value)
        self.e.emit(Op.RET)

    def _stmt_IfStmt(self, node: A.IfStmt) -> None:
        self.expr(node.cond)
        else_jump = self.e.emit_jump(Op.JUMP_IF_FALSE)
        self.stmt(node.then)
        if node.otherwise is None:
            self.e.patch(else_jump)
            return
        end_jump = self.e.emit_jump(Op.JUMP)
        self.e.patch(else_jump)
        self.stmt(node.otherwise)
        self.e.patch(end_jump)

    def _stmt_WhileStmt(self, node: A.WhileStmt) -> None:
        top = self.e.here
        self.expr(node.cond)
        exit_jump = self.e.emit_jump(Op.JUMP_IF_FALSE)
        loop = LoopCtx()
        self.loops.append(loop)
        self.stmt(node.body)
        self.loops.pop()
        for pos in loop.continues:
            self.e.patch(pos, top)
        self.e.emit_loop(top)
        self.e.patch(exit_jump)
        for pos in loop.breaks:
            self.e.patch(pos)

    def _stmt_ForRange(self, node: A.ForRange) -> None:
        # i = start; limit = end; while i < limit { body; i = i + 1 }
        self.expr(node.start)
        self.store(node.info)
        self.expr(node.end)
        self.e.emit(Op.STORE_LOCAL, node.limit_slot)

        top = self.e.here
        self.load(node.info)
        self.e.emit(Op.LOAD_LOCAL, node.limit_slot)
        self.e.emit(Op.LT)
        exit_jump = self.e.emit_jump(Op.JUMP_IF_FALSE)

        loop = LoopCtx()
        self.loops.append(loop)
        self.stmt(node.body)
        self.loops.pop()

        increment = self.e.here            # `continue` lands here, not at the top
        self.load(node.info)
        self.e.emit_const(1)
        self.e.emit(Op.ADD_INT)
        self.store(node.info)
        self.e.emit_loop(top)

        self.e.patch(exit_jump)
        for pos in loop.continues:
            self.e.patch(pos, increment)
        for pos in loop.breaks:
            self.e.patch(pos)

    def _stmt_ForIn(self, node: A.ForIn) -> None:
        # seq = iterable; i = 0; while i < len(seq) { x = seq[i]; body; i = i + 1 }
        self.expr(node.iterable)
        self.e.emit(Op.STORE_LOCAL, node.arr_slot)
        self.e.emit_const(0)
        self.e.emit(Op.STORE_LOCAL, node.idx_slot)

        top = self.e.here
        self.e.emit(Op.LOAD_LOCAL, node.idx_slot)
        self.e.emit(Op.LOAD_LOCAL, node.arr_slot)
        self.e.emit(Op.LEN)
        self.e.emit(Op.LT)
        exit_jump = self.e.emit_jump(Op.JUMP_IF_FALSE)

        self.e.emit(Op.LOAD_LOCAL, node.arr_slot)
        self.e.emit(Op.LOAD_LOCAL, node.idx_slot)
        self.e.emit(Op.INDEX_GET)
        self.store(node.info)

        loop = LoopCtx()
        self.loops.append(loop)
        self.stmt(node.body)
        self.loops.pop()

        increment = self.e.here
        self.e.emit(Op.LOAD_LOCAL, node.idx_slot)
        self.e.emit_const(1)
        self.e.emit(Op.ADD_INT)
        self.e.emit(Op.STORE_LOCAL, node.idx_slot)
        self.e.emit_loop(top)

        self.e.patch(exit_jump)
        for pos in loop.continues:
            self.e.patch(pos, increment)
        for pos in loop.breaks:
            self.e.patch(pos)

    def _stmt_BreakStmt(self, node: A.BreakStmt) -> None:
        self.loops[-1].breaks.append(self.e.emit_jump(Op.JUMP))

    def _stmt_ContinueStmt(self, node: A.ContinueStmt) -> None:
        self.loops[-1].continues.append(self.e.emit_jump(Op.JUMP))

    def _stmt_AssignStmt(self, node: A.AssignStmt) -> None:
        target, op = node.target, node.op
        binop = None if op == "=" else self.binary_opcode(node.kind, op[0])

        if isinstance(target, A.Ident):
            if binop is None:
                self.expr(node.value)
            else:
                self.load(target.ref)
                self.expr(node.value)
                self.e.emit(binop)
            self.store(target.ref)
            return

        if isinstance(target, A.Index):
            self.expr(target.obj)
            self.expr(target.index)
            if binop is not None:
                self.e.emit(Op.DUP2)              # keep arr+idx for the store
                self.e.emit(Op.INDEX_GET)
                self.expr(node.value)
                self.e.emit(binop)
            else:
                self.expr(node.value)
            self.e.emit(Op.INDEX_SET)
            return

        if isinstance(target, A.FieldAccess):
            self.expr(target.obj)
            if binop is not None:
                self.e.emit(Op.DUP)
                self.e.emit(Op.FIELD_GET, target.index)
                self.expr(node.value)
                self.e.emit(binop)
            else:
                self.expr(node.value)
            self.e.emit(Op.FIELD_SET, target.index)
            return

        raise AssertionError("unreachable: invalid assignment target survived checking")

    # -- expressions -------------------------------------------------------
    def expr(self, node) -> None:
        self.e.set_line(node.span)
        method = getattr(self, "_expr_" + type(node).__name__)
        method(node)

    def _expr_IntLit(self, node: A.IntLit) -> None:
        self.e.emit_const(node.value)

    def _expr_FloatLit(self, node: A.FloatLit) -> None:
        self.e.emit_const(node.value)

    def _expr_StrLit(self, node: A.StrLit) -> None:
        self.e.emit_const(node.value)

    def _expr_BoolLit(self, node: A.BoolLit) -> None:
        self.e.emit(Op.TRUE if node.value else Op.FALSE)

    def _expr_Unary(self, node: A.Unary) -> None:
        self.expr(node.operand)
        self.e.emit(Op.NOT if node.op == "!" else NEG_OPS[node.kind])

    def _expr_Binary(self, node: A.Binary) -> None:
        self.expr(node.left)
        self.expr(node.right)
        self.e.emit(self.binary_opcode(node.kind, node.op))

    @staticmethod
    def binary_opcode(kind: str, op: str) -> Op:
        if op in COMPARE_OPS:
            return COMPARE_OPS[op]
        try:
            return ARITH_OPS[(kind, op)]
        except KeyError:
            raise AssertionError(f"no opcode for {kind} {op}") from None

    def _expr_Logical(self, node: A.Logical) -> None:
        # The jump leaves the deciding value on the stack and skips the right
        # operand entirely; otherwise it pops and evaluates it.
        self.expr(node.left)
        jump_op = Op.JUMP_IF_FALSE_OR_POP if node.op == "&&" else Op.JUMP_IF_TRUE_OR_POP
        short = self.e.emit_jump(jump_op)
        self.expr(node.right)
        self.e.patch(short)

    def _expr_ArrayLit(self, node: A.ArrayLit) -> None:
        for item in node.elements:
            self.expr(item)
        self.e.emit(Op.MAKE_ARRAY, len(node.elements))

    def _expr_StructLit(self, node: A.StructLit) -> None:
        # Field initialisers run in declaration order, not source order.
        for source_index in node.order:
            self.expr(node.fields[source_index][1])
        self.e.emit(Op.MAKE_STRUCT, node.def_.index)

    def _expr_FieldAccess(self, node: A.FieldAccess) -> None:
        self.expr(node.obj)
        self.e.emit(Op.FIELD_GET, node.index)

    def _expr_Index(self, node: A.Index) -> None:
        self.expr(node.obj)
        self.expr(node.index)
        self.e.emit(Op.INDEX_GET)

    def _expr_Ident(self, node: A.Ident) -> None:
        self.load(node.ref)

    def _expr_Call(self, node: A.Call) -> None:
        if node.builtin is not None:
            # `len` is an intrinsic: it becomes a single instruction.
            if node.builtin == "len":
                self.expr(node.args[0])
                self.e.emit(Op.LEN)
                return
            for arg in node.args:
                self.expr(arg)
            self.e.emit(Op.CALL_NATIVE, B.BUILTIN_INDEX[node.builtin], len(node.args))
            return
        self.expr(node.callee)
        for arg in node.args:
            self.expr(arg)
        self.e.emit(Op.CALL, len(node.args))

    # -- storage -----------------------------------------------------------
    def load(self, ref) -> None:
        if isinstance(ref, A.FnDecl):
            self.e.emit(Op.LOAD_GLOBAL, ref.global_slot)
            return
        assert isinstance(ref, VarInfo)
        if ref.kind == "local":
            self.e.emit(Op.LOAD_LOCAL, ref.slot)
        else:
            self.e.emit(Op.LOAD_GLOBAL, ref.slot)

    def store(self, ref: VarInfo) -> None:
        if ref.kind == "local":
            self.e.emit(Op.STORE_LOCAL, ref.slot)
        else:
            self.e.emit(Op.STORE_GLOBAL, ref.slot)


def compile_module(module: A.Module, checker: Checker, source_name: str = "<input>") -> Program:
    return Compiler(checker, source_name).compile_module(module)
