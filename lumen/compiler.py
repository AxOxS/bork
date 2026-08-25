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
from .bytecode import Function, Program
from .checker import Checker, VarInfo
from .opcodes import ARITH_OPS, COMPARE_OPS, NEG_OPS, OPERANDS, WIDTH, Op

PLACEHOLDER = 0x7FFF

class FunctionEmitter:
    def __init__(self, name: str, nlocals: int = 0):
        self.fn = Function(name, nlocals)
        self.const_index: dict = {}

    def emit(self, op: Op, *operands: int) -> int:
        offset = len(self.fn.code)
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

    @property
    def here(self) -> int:
        return len(self.fn.code)


class Compiler:
    def __init__(self, checker: Checker, source_name: str = "<input>"):
        self.checker = checker
        self.program = Program(source_name)
        self.e: FunctionEmitter = None      # current emitter

    # -- driver ------------------------------------------------------------
    def compile_module(self, module: A.Module) -> Program:
        for name, info in self.checker.globals.items():
            self.program.global_names[info.slot] = name
        self.program.nglobals = self.checker.nglobals

        self.e = FunctionEmitter("<main>", getattr(module, "entry_nlocals", 0))
        for stmt in module.stmts:
            self.stmt(stmt)
        self.e.emit(Op.HALT)
        self.program.entry_index = self.program.add_function(self.e.fn)
        return self.program

    # -- statements --------------------------------------------------------
    def stmt(self, node) -> None:
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

    def _stmt_AssignStmt(self, node: A.AssignStmt) -> None:
        self.expr(node.value)
        self.store(node.target.ref)

    # -- expressions -------------------------------------------------------
    def expr(self, node) -> None:
        method = getattr(self, "_expr_" + type(node).__name__)
        method(node)

    def _expr_IntLit(self, node: A.IntLit) -> None:
        self.e.emit_const(node.value)

    def _expr_FloatLit(self, node: A.FloatLit) -> None:
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

    def _expr_Ident(self, node: A.Ident) -> None:
        self.load(node.ref)

    def _expr_Call(self, node: A.Call) -> None:
        for arg in node.args:
            self.expr(arg)
        self.e.emit(Op.CALL_NATIVE, B.BUILTIN_INDEX[node.builtin], len(node.args))

    # -- storage -----------------------------------------------------------
    def load(self, ref: VarInfo) -> None:
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
