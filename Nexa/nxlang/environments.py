"""Execution environments for NXLang.

0.9.0 ships the native ``nx`` environment.  The ``py`` environment is part of
the public interface but intentionally not implemented yet; it must not be
emulated with Python's built-in ``exec()``.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from .ast import Program
from .errors import EnvironmentERR


class Environment:
    """Base class for NXLang execution environments."""

    name = "base"
    description = "Abstract NXLang environment"

    def run(
        self,
        runtime: Any,
        program: Program,
        filename: str = "<nx>",
        args: Iterable[str] = (),
    ) -> None:
        raise NotImplementedError


class NativeEnvironment(Environment):
    """Execute NXLang directly on the NXLang runtime."""

    name = "nx"
    description = "Native NXLang execution"

    def run(
        self,
        runtime: Any,
        program: Program,
        filename: str = "<nx>",
        args: Iterable[str] = (),
    ) -> None:
        runtime.execute(program, filename=filename, args=tuple(args))


class PythonEnvironment(Environment):
    """Placeholder for future Python interoperability."""

    name = "py"
    description = "Python interoperability (planned)"

    def run(
        self,
        runtime: Any,
        program: Program,
        filename: str = "<nx>",
        args: Iterable[str] = (),
    ) -> None:
        raise EnvironmentERR(
            "The 'py' environment is not implemented in NXLang Base; "
            "use the native 'nx' environment"
        )


_ENVIRONMENTS: dict[str, Environment] = {
    "nx": NativeEnvironment(),
    "py": PythonEnvironment(),
}


def get_environment(name: str = "nx") -> Environment:
    """Return the environment registered as *name*."""
    try:
        return _ENVIRONMENTS[name]
    except KeyError:
        known = ", ".join(sorted(_ENVIRONMENTS))
        raise EnvironmentERR(
            f"Unknown NXLang environment {name!r} (available: {known})"
        ) from None


def list_environments() -> list[str]:
    return sorted(_ENVIRONMENTS)
