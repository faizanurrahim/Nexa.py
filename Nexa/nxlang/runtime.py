"""Tree-walking NXLang runtime for NXLang Base."""

from __future__ import annotations

import sys
from typing import Any, Iterable, Optional, TextIO

from .ast import (
    Call,
    DoBlock,
    Expression,
    ExpressionStatement,
    Identifier,
    IncludeStatement,
    Literal,
    Program,
    Statement,
    ThrowStatement,
)
from .errors import ERROR_TYPES, ERR, NameERR, RuntimeERR, TypeERR, resolve_error_type
from .modules import ModuleRegistry


class Runtime:
    """Execute NXLang statements against a module registry."""

    def __init__(
        self,
        modules: Optional[ModuleRegistry] = None,
        stream: Optional[TextIO] = None,
    ) -> None:
        self.modules = modules if modules is not None else ModuleRegistry.with_defaults()
        self.stream: TextIO = stream if stream is not None else sys.stdout
        self.globals: dict[str, Any] = {"print": self._builtin_print, "args": []}
        self.globals.update(ERROR_TYPES)

    # -- entry point ----------------------------------------------------------
    def execute(
        self,
        program: Program,
        *,
        filename: str = "<nx>",
        args: Iterable[str] = (),
    ) -> None:
        scope = dict(self.globals)
        scope["args"] = list(args)
        self._exec_block(program.body, scope, filename)

    # -- builtins -------------------------------------------------------------
    def _builtin_print(self, *values: Any, sep: str = " ", end: str = "\n") -> None:
        self.stream.write(sep.join(str(value) for value in values) + end)

    # -- statements -----------------------------------------------------------
    def _exec_block(
        self, body: list[Statement], scope: dict[str, Any], filename: str
    ) -> None:
        for statement in body:
            self._exec_statement(statement, scope, filename)

    def _exec_statement(
        self, statement: Statement, scope: dict[str, Any], filename: str
    ) -> None:
        if isinstance(statement, IncludeStatement):
            scope[statement.alias] = self.modules.resolve(
                statement.module,
                internal=statement.internal,
                filename=filename,
                line=statement.line,
                column=statement.column,
            )
            return

        if isinstance(statement, DoBlock):
            self._exec_do(statement, scope, filename)
            return

        if isinstance(statement, ThrowStatement):
            value = (
                self._eval(statement.expression, scope, filename)
                if statement.expression is not None
                else None
            )
            if not isinstance(value, ERR):
                raise TypeERR(
                    'throw() requires an NXLang error object, e.g. throw(ERR("message"))',
                    filename=filename,
                    line=statement.line,
                    column=statement.column,
                )
            raise value.with_location(filename, statement.line, statement.column)

        if isinstance(statement, ExpressionStatement):
            if statement.expression is not None:
                self._eval(statement.expression, scope, filename)
            return

        raise RuntimeERR(
            f"Unsupported statement: {type(statement).__name__}", filename=filename
        )

    def _exec_do(self, statement: DoBlock, scope: dict[str, Any], filename: str) -> None:
        """Run a ``do`` block, dispatching raised errors to ``unless`` handlers.

        Handlers are matched in source order by error type, including
        inheritance: ``unless ERR`` catches ``SyntaxERR`` because
        ``SyntaxERR`` is an ``ERR``.  The first matching handler wins.  An
        error with no matching handler propagates to the caller.
        """
        try:
            self._exec_block(statement.body, scope, filename)
        except ERR as exc:
            for handler in statement.handlers:
                try:
                    error_type = resolve_error_type(handler.error_type)
                except NameERR as err:
                    raise err.with_location(
                        filename, handler.line, handler.column
                    ) from None
                if isinstance(exc, error_type):
                    handler_scope = dict(scope)
                    handler_scope[handler.alias] = exc
                    self._exec_block(handler.body, handler_scope, filename)
                    return
            raise

    # -- expressions ----------------------------------------------------------
    def _eval(
        self, expression: Optional[Expression], scope: dict[str, Any], filename: str
    ) -> Any:
        if isinstance(expression, Literal):
            return expression.value

        if isinstance(expression, Identifier):
            if expression.name in scope:
                return scope[expression.name]
            raise NameERR(
                f"Undefined name {expression.name!r}",
                filename=filename,
                line=expression.line,
                column=expression.column,
            )

        if isinstance(expression, Call):
            if expression.name not in scope:
                raise NameERR(
                    f"Undefined name {expression.name!r}",
                    filename=filename,
                    line=expression.line,
                    column=expression.column,
                )
            callee = scope[expression.name]
            if not callable(callee):
                raise TypeERR(
                    f"{expression.name!r} is not callable",
                    filename=filename,
                    line=expression.line,
                    column=expression.column,
                )
            arguments = [self._eval(arg, scope, filename) for arg in expression.arguments]
            return callee(*arguments)

        raise RuntimeERR(
            f"Unsupported expression: {type(expression).__name__}", filename=filename
        )
