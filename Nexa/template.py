# Nexa/template.py
from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .nserver import Nserver, Response


# ---------------------------------------------------------------------------
# Template expression pattern
# ---------------------------------------------------------------------------

_TEMPLATE_VARIABLE = re.compile(r"\{\{\s*(.+?)\s*\}\}")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TemplateError(Exception):
    """Base class for template errors."""


class TemplateSyntaxError(TemplateError, ValueError):
    """The template source could not be parsed."""


class TemplateRenderError(TemplateError, RuntimeError):
    """An expression in the template failed to render."""


class TemplateNotFound(TemplateError, FileNotFoundError):
    """A template file could not be found or is outside the template folder."""


# ---------------------------------------------------------------------------
# Legacy Template class (kept for backwards compatibility)
# ---------------------------------------------------------------------------

class Template:
    """Simple legacy renderer supporting {{ expression }} interpolation."""

    def __init__(self, source: str, filename: str = "<template>") -> None:
        self._filename = filename
        self._parts = self._compile(source)

    def _compile(self, source: str) -> list[tuple[str, str | None]]:
        parts: list[tuple[str, str | None]] = []
        position = 0

        for match in _TEMPLATE_VARIABLE.finditer(source):
            literal = source[position:match.start()]
            if literal:
                parts.append((literal, None))

            expression = match.group(1).strip()
            if not expression:
                raise TemplateSyntaxError(
                    f"Empty template expression in {self._filename!r}"
                )

            parts.append(("", expression))
            position = match.end()

        remaining = source[position:]
        if remaining:
            parts.append((remaining, None))

        if not parts:
            parts.append(("", None))

        return parts

    def render(self, **context: Any) -> str:
        namespace: dict[str, Any] = {
            "str": str,
            "len": len,
            "range": range,
            "list": list,
            "dict": dict,
            "enumerate": enumerate,
            "zip": zip,
            "min": min,
            "max": max,
            "sum": sum,
            "abs": abs,
            "round": round,
            "bool": bool,
            "int": int,
            "float": float,
            "True": True,
            "False": False,
            "None": None,
        }
        namespace.update(context)

        chunks: list[str] = []

        for literal, expression in self._parts:
            if literal:
                chunks.append(literal)

            if expression is not None:
                try:
                    value = eval(expression, {"__builtins__": {}}, namespace)
                except Exception as exc:
                    raise TemplateRenderError(
                        f"Error evaluating {expression!r} "
                        f"in {self._filename!r}: {exc}"
                    ) from exc

                chunks.append(str(value))

        return "".join(chunks)


# ---------------------------------------------------------------------------
# NXscript template loader
# ---------------------------------------------------------------------------

def _template_loader(app: "Nserver"):
    """Return an NXscript template loader bound to this Nserver instance."""

    def load(template_name: str, **context: Any) -> str:
        template_dir = app.template_dir.resolve()
        path = (template_dir / template_name).resolve()

        # Prevent path traversal outside the template directory.
        try:
            path.relative_to(template_dir)
        except ValueError:
            raise TemplateNotFound(
                f"Template {template_name!r} resolves outside the template "
                f"folder ({app.template_folder!r})."
            ) from None

        if not path.is_file():
            raise TemplateNotFound(
                f"Template {template_name!r} not found in "
                f"{app.template_folder!r}."
            )

        # Import lazily to avoid the circular import:
        # nxscript.py imports exceptions from template.py.
        from .nxscript import NXscriptTemplate

        source = path.read_text(encoding="utf-8")
        template = NXscriptTemplate(source, filename=template_name)

        # Handle template inheritance.
        parent_name = template._structure.get("parent")

        if parent_name:
            parent_path = (template_dir / parent_name).resolve()

            try:
                parent_path.relative_to(template_dir)
            except ValueError:
                raise TemplateNotFound(
                    f"Parent template {parent_name!r} resolves outside "
                    f"the template folder."
                ) from None

            if not parent_path.is_file():
                raise TemplateNotFound(
                    f"Parent template {parent_name!r} not found in "
                    f"{app.template_folder!r}."
                )

            parent_source = parent_path.read_text(encoding="utf-8")
            parent_template = NXscriptTemplate(
                parent_source,
                filename=parent_name,
            )
            template.set_parent(parent_template)

        return template.render(**context)

    return load


# ---------------------------------------------------------------------------
# Per-request loader binding
# ---------------------------------------------------------------------------

class _PerRequestLoader:
    """Placeholder used when no Nserver request is active."""

    def __call__(self, name: str, **context: Any) -> str:
        raise RuntimeError(
            "render_template(): no active request context. "
            "It can only be called inside a route handler of an Nserver "
            "instance that has a template_folder configured."
        )


_default_loader = _PerRequestLoader()
_current_loader: Any = _default_loader


def _bind_loader(app: "Nserver") -> None:
    global _current_loader
    _current_loader = _template_loader(app)


def _unbind_loader() -> None:
    global _current_loader
    _current_loader = _default_loader


def _auto_bind_loader() -> None:
    """Bind the loader automatically when an active Nserver exists."""
    global _current_loader

    if _current_loader is not _default_loader:
        return

    from .nserver import _current_server

    server = _current_server.get()
    if server is not None:
        _current_loader = _template_loader(server)


def _get_loader():
    return _current_loader


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_template(template_name: str, **context: Any) -> "Response":
    """Render an NXscript template and return an HTML Response."""
    from .nserver import Response

    _auto_bind_loader()
    loader = _get_loader()
    body = loader(template_name, **context)

    return Response(
        body,
        content_type="text/html; charset=utf-8",
    )


def rndr_template(template_name: str, **context: Any) -> "Response":
    """Short alias for render_template()."""
    return render_template(template_name, **context)


# ---------------------------------------------------------------------------
# Request hooks
# ---------------------------------------------------------------------------

def _make_template_loader_before_request_hook(app: "Nserver"):
    """Bind this app's template loader before each request."""

    def hook(_request):
        _bind_loader(app)

    return hook


def _template_loader_after_request_hook(response_body, status, headers):
    """Unbind the template loader after a request."""
    _unbind_loader()
    return response_body, status, headers


def _template_loader_error_hook(
    response_body,
    status,
    headers,
    exc=None,
):
    """Unbind the loader if a request raises an exception."""
    _unbind_loader()
    return response_body, status, headers


def install_template_hooks(app: "Nserver") -> None:
    """Install template loader hooks on an Nserver instance."""
    app.before_request(_make_template_loader_before_request_hook(app))
    app.after_request(_template_loader_error_hook)
    app.after_request(_template_loader_after_request_hook)