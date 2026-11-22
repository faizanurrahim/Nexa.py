"""NXLang error hierarchy.

All NXLang errors inherit from :class:`ERR`.  The framework never uses
Python-style ``try``/``except`` as *NXLang syntax*; handlers are expressed with
``do { } unless ERR as e { }``, and the runtime matches errors by type,
including subclasses.
"""

from __future__ import annotations

from typing import Optional


class ERR(Exception):
    """Root of the NXLang error hierarchy."""

    kind = "ERR"

    def __init__(
        self,
        message: str = "",
        *,
        filename: Optional[str] = None,
        line: Optional[int] = None,
        column: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.message = str(message)
        self.filename = filename
        self.line = line
        self.column = column

    # -- presentation ---------------------------------------------------------
    @property
    def location(self) -> str:
        """``file:line:column`` for the error, omitting unknown parts."""
        parts: list[str] = []
        if self.filename:
            parts.append(self.filename)
        if self.line is not None:
            parts.append(str(self.line))
            if self.column is not None:
                parts.append(str(self.column))
        return ":".join(parts)

    def with_location(self, filename: Optional[str], line: Optional[int], column: Optional[int]) -> "ERR":
        """Attach source information when it is not already present."""
        if self.filename is None:
            self.filename = filename
        if self.line is None:
            self.line = line
        if self.column is None:
            self.column = column
        return self

    def __str__(self) -> str:
        if self.location:
            return f"{self.location}: {self.message}"
        return self.message

    def format(self) -> str:
        """Return ``ERR: file:line:column: message``."""
        return f"{self.kind}: {self}" if self.message else f"{self.kind}: {self.location}"


class SyntaxERR(ERR):
    kind = "SyntaxERR"


class CompileERR(ERR):
    kind = "CompileERR"


class RuntimeERR(ERR):
    kind = "RuntimeERR"


class ImportERR(ERR):
    kind = "ImportERR"


class ModuleERR(ERR):
    kind = "ModuleERR"


class EnvironmentERR(ERR):
    kind = "EnvironmentERR"


class TypeERR(ERR):
    kind = "TypeERR"


class NameERR(ERR):
    kind = "NameERR"


class InternalERR(ERR):
    kind = "InternalERR"


ERROR_TYPES: dict[str, type[ERR]] = {
    cls.__name__: cls
    for cls in (
        ERR,
        SyntaxERR,
        CompileERR,
        RuntimeERR,
        ImportERR,
        ModuleERR,
        EnvironmentERR,
        TypeERR,
        NameERR,
        InternalERR,
    )
}


def resolve_error_type(name: str) -> type[ERR]:
    """Return the error class called *name*.

    Raises:
        NameERR: when no such error type is defined.
    """
    try:
        return ERROR_TYPES[name]
    except KeyError:
        known = ", ".join(sorted(ERROR_TYPES))
        raise NameERR(f"Unknown NXLang error type {name!r} (known: {known})") from None
