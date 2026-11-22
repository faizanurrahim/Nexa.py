"""Primary NXLang implementation module.

This is the public face of NXLang Base: it wires together the compiler,
runtime, module registry and execution environment.  Future releases grow the
language here rather than in the compiler module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, TextIO

from .compiler import CompiledProgram, compile_source
from .environments import Environment, get_environment
from .errors import ImportERR
from .modules import ModuleRegistry
from .runtime import Runtime

__all__ = ["NXLang", "run_source", "run_file", "execute", "compile_source"]


class NXLang:
    """A configured NXLang runtime.

    Example::

        from Nexa.nxlang import NXLang

        lang = NXLang()
        lang.run('include <base_compiler> as bc\\nprint("hello")')
    """

    def __init__(
        self,
        environment: str = "nx",
        modules: Optional[ModuleRegistry] = None,
        stream: Optional[TextIO] = None,
    ) -> None:
        self.modules = modules if modules is not None else ModuleRegistry.with_defaults()
        self.stream = stream
        self.runtime = Runtime(self.modules, stream=stream)
        self.environment: Environment = get_environment(environment)

    @property
    def environment_name(self) -> str:
        return self.environment.name

    # -- compilation ----------------------------------------------------------
    def compile(self, source: str, filename: str = "<nx>") -> CompiledProgram:
        """Compile *source* without executing it."""
        return compile_source(source, filename)

    # -- execution ------------------------------------------------------------
    def run(
        self,
        source: str,
        filename: str = "<nx>",
        args: Optional[Iterable[str]] = None,
    ) -> None:
        """Compile and execute *source*."""
        self.run_compiled(self.compile(source, filename), args)

    def run_compiled(
        self, compiled: CompiledProgram, args: Optional[Iterable[str]] = None
    ) -> None:
        self.environment.run(
            self.runtime,
            compiled.program,
            compiled.filename,
            tuple(args or ()),
        )

    def run_file(self, path: str | Path, args: Optional[Iterable[str]] = None) -> None:
        """Execute an ``.nx`` source file."""
        target = Path(path)
        if not target.is_file():
            raise ImportERR(f"NXLang source file not found: {target}")
        if target.suffix != ".nx":
            raise ImportERR(
                f"NXLang source files must use the .nx extension: {target}"
            )
        self.run(
            target.read_text(encoding="utf-8"),
            filename=target.as_posix(),
            args=args,
        )


def run_source(
    source: str,
    *,
    filename: str = "<nx>",
    args: Optional[Iterable[str]] = None,
    environment: str = "nx",
    modules: Optional[ModuleRegistry] = None,
    stream: Optional[TextIO] = None,
) -> None:
    """Convenience wrapper: compile and run NXLang *source*."""
    NXLang(environment=environment, modules=modules, stream=stream).run(
        source, filename=filename, args=args
    )


def run_file(
    path: str | Path,
    *,
    args: Optional[Iterable[str]] = None,
    environment: str = "nx",
    modules: Optional[ModuleRegistry] = None,
    stream: Optional[TextIO] = None,
) -> None:
    """Convenience wrapper: run an NXLang source file."""
    NXLang(environment=environment, modules=modules, stream=stream).run_file(
        path, args=args
    )


def execute(
    path: str | Path,
    *,
    args: Optional[Iterable[str]] = None,
    environment: str = "nx",
) -> None:
    """Alias for :func:`run_file` used by the CLI."""
    run_file(path, args=args, environment=environment)
