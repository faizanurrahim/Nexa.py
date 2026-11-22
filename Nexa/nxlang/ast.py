"""Abstract syntax tree nodes for NXLang Base."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Node:
    line: int = 1
    column: int = 1


@dataclass
class Program(Node):
    body: list["Statement"] = field(default_factory=list)


@dataclass
class Statement(Node):
    pass


@dataclass
class IncludeStatement(Statement):
    """``include <name> as alias`` or ``include <<name>> as alias``."""

    module: str = ""
    alias: str = ""
    internal: bool = False


@dataclass
class UnlessHandler(Node):
    """``unless ERR as e { ... }`` attached to the preceding ``do`` block."""

    error_type: str = "ERR"
    alias: str = "e"
    body: list[Statement] = field(default_factory=list)


@dataclass
class DoBlock(Statement):
    body: list[Statement] = field(default_factory=list)
    handlers: list[UnlessHandler] = field(default_factory=list)


@dataclass
class ThrowStatement(Statement):
    """``throw(ERR("message"))``."""

    expression: Optional["Expression"] = None


class Expression(Node):
    pass


@dataclass
class Literal(Expression):
    value: Any = None


@dataclass
class Identifier(Expression):
    name: str = ""


@dataclass
class Call(Expression):
    name: str = ""
    arguments: list[Expression] = field(default_factory=list)


@dataclass
class ExpressionStatement(Statement):
    expression: Optional[Expression] = None
