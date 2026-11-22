"""Line-oriented lexer for NXLang Base."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import SyntaxERR


@dataclass
class Token:
    kind: str
    value: str
    line: int
    column: int


class Lexer:
    """Turn NXLang source text into a flat token stream."""

    _PUNCTUATION = set("{}();,<>:=+-*/.![]")

    def __init__(self, source: str, filename: str = "<nx>") -> None:
        self.source = source
        self.filename = filename
        self.pos = 0
        self.line = 1
        self.column = 1

    # -- cursor ---------------------------------------------------------------
    def _peek(self, offset: int = 0) -> str:
        index = self.pos + offset
        return self.source[index] if index < len(self.source) else ""

    def _advance(self, count: int = 1) -> None:
        for _ in range(count):
            if self.pos >= len(self.source):
                return
            if self.source[self.pos] == "\n":
                self.line += 1
                self.column = 1
            else:
                self.column += 1
            self.pos += 1

    # -- token readers --------------------------------------------------------
    def _string(self) -> Token:
        quote = self._peek()
        line, column = self.line, self.column
        self._advance()
        chars: list[str] = []
        escapes = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'"}
        while self.pos < len(self.source):
            char = self._peek()
            if char == quote:
                self._advance()
                return Token("STRING", "".join(chars), line, column)
            if char == "\\":
                nxt = self._peek(1)
                chars.append(escapes.get(nxt, nxt))
                self._advance(2)
                continue
            if char == "\n":
                break
            chars.append(char)
            self._advance()
        raise SyntaxERR(
            "Unterminated string literal",
            filename=self.filename,
            line=line,
            column=column,
        )

    def _number(self) -> Token:
        line, column = self.line, self.column
        start = self.pos
        while self._peek().isdigit():
            self._advance()
        if self._peek() == "." and self._peek(1).isdigit():
            self._advance()
            while self._peek().isdigit():
                self._advance()
        return Token("NUMBER", self.source[start:self.pos], line, column)

    # -- entry point ----------------------------------------------------------
    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while self.pos < len(self.source):
            char = self._peek()

            if char in " \t\r":
                self._advance()
                continue

            if char == "\n":
                tokens.append(Token("NEWLINE", "\n", self.line, self.column))
                self._advance()
                continue

            if char == "#" or (char == "/" and self._peek(1) == "/"):
                while self.pos < len(self.source) and self._peek() != "\n":
                    self._advance()
                continue

            if char in "\"'":
                tokens.append(self._string())
                continue

            if char.isdigit():
                tokens.append(self._number())
                continue

            if char.isalpha() or char == "_":
                line, column = self.line, self.column
                start = self.pos
                while self._peek().isalnum() or self._peek() == "_":
                    self._advance()
                tokens.append(Token("IDENT", self.source[start:self.pos], line, column))
                continue

            pair = self.source[self.pos:self.pos + 2]
            if pair in ("<<", ">>"):
                tokens.append(Token("OP", pair, self.line, self.column))
                self._advance(2)
                continue

            if char in self._PUNCTUATION:
                tokens.append(Token("OP", char, self.line, self.column))
                self._advance()
                continue

            raise SyntaxERR(
                f"Unexpected character {char!r}",
                filename=self.filename,
                line=self.line,
                column=self.column,
            )

        tokens.append(Token("EOF", "", self.line, self.column))
        return tokens
