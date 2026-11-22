"""Blade compiler — component-oriented NXscript extensions.

Blade adds a component model on top of the base NXscript compiler.

.. note::
    Blade is a work in progress. The API is stabilising but may change
    between releases.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class NexaSyntaxError(Exception):
    """Raised when Blade template syntax is invalid."""
    pass


class BladeNode:
    """Base class for Blade components.

    Subclasses declare a ``template`` string written in NXscript syntax and
    may override ``__init__`` to accept typed parameters and children.
    """

    template: str = ""

    def __init__(self, **attrs: Any) -> None:
        self.attrs = attrs
        self.children: list[BladeNode | str] = []

    def __repr__(self) -> str:
        cls = type(self).__name__
        return f"<{cls} {self.attrs!r}>"

    def render(self, compiler: "BladeCompiler") -> str:
        """Render this node to Python source using *compiler*."""
        return compiler.compile(self.template)


class BladeCompiler:
    """A compiler that understands Blade component nodes.

    In addition to the base NXscript grammar, BladeCompiler recognises
    ``<include src="..."/>`` as a way to inline another template file.
    """

    def __init__(self, base_path: Path | str | None = None) -> None:
        self.base_path = Path(base_path or Path.cwd())
        self._include_cache: dict[str, str] = {}

    def compile(self, source: str) -> str:
        """Compile *source* (NXscript markup) to Python source code."""
        return self._preprocess(source)

    def compile_file(self, path: str | Path) -> str:
        """Compile a template file to Python source code."""
        path = Path(path)
        source = path.read_text(encoding="utf-8")
        return self.compile(source)

    def load_include(self, src: str) -> str:
        """Return the compiled source for an included template."""
        src_path = self.base_path / src
        key = str(src_path.resolve())
        if key not in self._include_cache:
            self._include_cache[key] = self.compile_file(src_path)
        return self._include_cache[key]

    def _preprocess(self, source: str) -> str:
        """Resolve ``<include>`` directives before delegating to the base compiler."""
        import re
        lines = source.splitlines()
        out: list[str] = []
        for line in lines:
            stripped = line.strip()
            m = re.fullmatch(r'<include\s+src="([^"]+)"\s*/>', stripped)
            if m:
                src = m.group(1)
                included = self.load_include(src)
                out.extend(included.splitlines())
            else:
                out.append(line)
        return "\n".join(out) + "\n"


def install_blade_loader(server: Any, compiler: BladeCompiler) -> None:
    """Install a template loader that understands Blade includes.

    After calling this, ``render_template("name.nx")`` will preprocess
    ``<include>`` directives before compiling.
    """
    original_loader = getattr(server, "_template_loader", None)
    _blade_compiler = compiler

    def blade_loader(template_name: str) -> str:
        source = server._read_template_file(template_name)
        return _preprocess_includes(source, _blade_compiler, server._project_dir)

    server._template_loader = blade_loader


def _preprocess_includes(source: str, compiler: BladeCompiler, base_dir: Path) -> str:
    """Replace ``<include src="..."/>`` tags with the included template source."""
    import re
    lines = source.splitlines()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        m = re.fullmatch(r'<include\s+src="([^"]+)"\s*/>', stripped)
        if m:
            src = m.group(1)
            included = compiler.load_include(src)
            out.extend(included.splitlines())
        else:
            out.append(line)
    return "\n".join(out) + "\n"
