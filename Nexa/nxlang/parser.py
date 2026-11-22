"""Recursive-descent parser for NXLang Base."""

from __future__ import annotations

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
    UnlessHandler,
)
from .errors import SyntaxERR
from .lexer import Token


class Parser:
    """Parse a token stream into a :class:`Program`."""

    def __init__(self, tokens: list[Token], filename: str = "<nx>") -> None:
        self.tokens = tokens
        self.filename = filename
        self.pos = 0

    # -- token helpers --------------------------------------------------------
    def _peek(self, offset: int = 0) -> Token:
        index = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[index]

    def _advance(self) -> Token:
        token = self._peek()
        if token.kind != "EOF":
            self.pos += 1
        return token

    def _at(self, kind: str, value: str | None = None) -> bool:
        token = self._peek()
        if token.kind != kind:
            return False
        return value is None or token.value == value

    def _match(self, kind: str, value: str | None = None) -> Token | None:
        if self._at(kind, value):
            return self._advance()
        return None

    def _expect(self, kind: str, value: str | None = None, what: str | None = None) -> Token:
        token = self._peek()
        if self._at(kind, value):
            return self._advance()
        expected = what or (f"{kind} {value!r}" if value is not None else kind)
        found = "end of file" if token.kind == "EOF" else f"{token.kind} {token.value!r}"
        raise SyntaxERR(
            f"Expected {expected}, found {found}",
            filename=self.filename,
            line=token.line,
            column=token.column,
        )

    def _skip_separators(self) -> None:
        while self._at("NEWLINE") or self._at("OP", ";"):
            self._advance()

    # -- grammar --------------------------------------------------------------
    def parse(self) -> Program:
        body: list[Statement] = []
        self._skip_separators()
        while not self._at("EOF"):
            body.append(self._statement())
            self._skip_separators()
        return Program(body=body)

    def _statement(self) -> Statement:
        token = self._peek()
        if token.kind == "IDENT":
            if token.value == "include":
                return self._include()
            if token.value == "do":
                return self._do_block()
            if token.value == "throw":
                return self._throw()
        expression = self._expression()
        statement = ExpressionStatement(
            expression=expression, line=token.line, column=token.column
        )
        self._end_statement()
        return statement

    def _end_statement(self) -> None:
        if self._at("NEWLINE") or self._at("OP", ";") or self._at("EOF") or self._at("OP", "}"):
            return
        token = self._peek()
        raise SyntaxERR(
            f"Unexpected {token.value!r} after statement",
            filename=self.filename,
            line=token.line,
            column=token.column,
        )

    def _include(self) -> IncludeStatement:
        keyword = self._advance()  # include
        internal = False
        if self._match("OP", "<<"):
            internal = True
            closing = ">>"
        elif self._match("OP", "<"):
            closing = ">"
        else:
            token = self._peek()
            raise SyntaxERR(
                "Expected '<module>' or '<<module>>' after 'include'",
                filename=self.filename,
                line=token.line,
                column=token.column,
            )

        name_parts: list[str] = []
        while not self._at("OP", closing):
            token = self._peek()
            if token.kind != "IDENT":
                raise SyntaxERR(
                    f"Expected a module name or {closing!r}, found {token.value!r}",
                    filename=self.filename,
                    line=token.line,
                    column=token.column,
                )
            name_parts.append(self._advance().value)
        self._expect("OP", closing)

        if not name_parts:
            raise SyntaxERR(
                "Empty module name in include statement",
                filename=self.filename,
                line=keyword.line,
                column=keyword.column,
            )

        self._expect("IDENT", "as", what="'as' and an alias")
        alias = self._expect("IDENT", what="an alias after 'as'")
        self._end_statement()
        return IncludeStatement(
            module="".join(name_parts),
            alias=alias.value,
            internal=internal,
            line=keyword.line,
            column=keyword.column,
        )

    def _do_block(self) -> DoBlock:
        keyword = self._advance()  # do
        self._expect("OP", "{", what="'{' after 'do'")
        body = self._block()
        self._expect("OP", "}", what="'}' to close the do block")
        handlers: list[UnlessHandler] = []

        # `unless` blocks belong to the most recent `do` block.
        while True:
            self._skip_separators()
            if not self._at("IDENT", "unless"):
                break
            handlers.append(self._unless_handler())

        return DoBlock(body=body, handlers=handlers, line=keyword.line, column=keyword.column)

    def _unless_handler(self) -> UnlessHandler:
        keyword = self._advance()  # unless
        error_token = self._expect("IDENT", what="an error type after 'unless'")
        self._expect("IDENT", "as", what="'as' and an alias")
        alias = self._expect("IDENT", what="an alias after 'as'")
        self._expect("OP", "{", what="'{' to open the unless block")
        body = self._block()
        self._expect("OP", "}", what="'}' to close the unless block")
        return UnlessHandler(
            error_type=error_token.value,
            alias=alias.value,
            body=body,
            line=keyword.line,
            column=keyword.column,
        )

    def _block(self) -> list[Statement]:
        body: list[Statement] = []
        self._skip_separators()
        while not self._at("OP", "}") and not self._at("EOF"):
            body.append(self._statement())
            self._skip_separators()
        return body

    def _throw(self) -> ThrowStatement:
        keyword = self._advance()  # throw
        self._expect("OP", "(", what="'(' after 'throw'")
        expression = self._expression()
        self._expect("OP", ")", what="')' to close throw()")
        self._end_statement()
        return ThrowStatement(
            expression=expression, line=keyword.line, column=keyword.column
        )

    def _expression(self) -> Expression:
        token = self._peek()

        if token.kind == "STRING":
            self._advance()
            return Literal(value=token.value, line=token.line, column=token.column)

        if token.kind == "NUMBER":
            self._advance()
            value = float(token.value) if "." in token.value else int(token.value)
            return Literal(value=value, line=token.line, column=token.column)

        if token.kind == "IDENT":
            self._advance()
            name = token.value
            if self._match("OP", "("):
                arguments: list[Expression] = []
                if not self._at("OP", ")"):
                    while True:
                        arguments.append(self._expression())
                        if not self._match("OP", ","):
                            break
                self._expect("OP", ")", what="')' to close the call")
                return Call(name=name, arguments=arguments, line=token.line, column=token.column)
            return Identifier(name=name, line=token.line, column=token.column)

        found = "end of file" if token.kind == "EOF" else repr(token.value)
        raise SyntaxERR(
            f"Expected an expression, found {found}",
            filename=self.filename,
            line=token.line,
            column=token.column,
        )
