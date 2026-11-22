"""Compilation pipeline for NXLang Base.

Compilation is deliberately small in 0.9.0: source → tokens → AST →
:class:`CompiledProgram`.  Later releases can add optimisation and bytecode
without changing the public entry points in :mod:`Nexa.nxlang.nx`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ast import Program
from .errors import CompileERR
from .lexer import Lexer
from .parser import Parser


@dataclass
class CompiledProgram:
    """A parsed NXLang program together with its source metadata."""

    program: Program
    filename: str
    source: str


class Compiler:
    """Front-end compiler: lex, parse and validate."""

    def compile(self, source: str, filename: str = "<nx>") -> CompiledProgram:
        if not isinstance(source, str):
            raise CompileERR("NXLang source must be a string")
        tokens = Lexer(source, filename).tokenize()
        program = Parser(tokens, filename).parse()
        return CompiledProgram(program=program, filename=filename, source=source)


def compile_source(source: str, filename: str = "<nx>") -> CompiledProgram:
    """Compile *source* into a :class:`CompiledProgram`."""
    return Compiler().compile(source, filename)
