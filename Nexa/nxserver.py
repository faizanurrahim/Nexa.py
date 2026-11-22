from __future__ import annotations

import asyncio
import errno
import io
import ipaddress
import json
import operator
import traceback
import urllib.parse
import warnings
from contextvars import ContextVar
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer as HTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, unquote, urlparse

from .__json import JSONResponse
from .__json import jsonify as _jsonify
from .log import _get_default as _get_default_logger
from .nx import Element, Fragment
from .template import _unbind_loader, install_template_hooks  # noqa: F401 (re-exported by nserver.py)
from .template import render_template as _render_template
from .template import rndr_template as _rndr_template

# Module-level aliases so route handlers that import from nxserver can use
# ``render_template`` without importing from Nexa.template directly.
render_template = _render_template
rndr_template = _rndr_template

# Lazy import of websocket module to avoid circular imports at load time.
_websocket_mod = None
_devtools_mod = None

def _get_websocket() -> Any:
    """Return the websocket module, importing it on first use."""
    global _websocket_mod
    if _websocket_mod is None:
        from . import websocket as _ws
        _websocket_mod = _ws
    return _websocket_mod

def _get_devtools() -> Any:
    """Return the devtools module, importing it on first use."""
    global _devtools_mod
    if _devtools_mod is None:
        from . import devtools as _dt
        _devtools_mod = _dt
    return _devtools_mod


# ---------------------------------------------------------------------------
# Request context — one per concurrent call, never shared globally
# ---------------------------------------------------------------------------

class Request:
    """Holds the parsed data for the HTTP request currently being handled.

    This object is created fresh for every request and is NOT shared between
    concurrent requests. Route handlers obtain the current request through
    ``nxserver.request``, which is backed by a ``contextvars.ContextVar``.
    """

    def __init__(
        self,
        method: str,
        path: str,
        url: str,
        query_string: str,
        headers: dict[str, str],
        body_bytes: bytes,
        remote_addr: str,
        max_body_size: int,
        server_name: str = "",
        server_port: str = "",
    ) -> None:
        self._method = method
        self._path = path
        self._url = url
        self._query_string = query_string
        self._headers = headers
        self._body_bytes = body_bytes
        self._remote_addr = remote_addr
        self._max_body_size = max_body_size
        self._server_name = server_name
        self._server_port = server_port

        # Cached parsed values — computed lazily so we do not pay for them
        # when a handler never touches them.
        self._parsed_url: Optional[urllib.parse.ParseResult] = None
        self._query: Optional[dict[str, list[str]]] = None
        self._args: Optional[dict[str, Any]] = None
        self._json: Any = _UNSET
        self._text: Optional[str] = None
        self._form: Optional[dict[str, Any]] = None
        self._files: Optional[dict[str, Any]] = None
        self._cookies: Optional[dict[str, str]] = None

    # -- convenience properties ------------------------------------------------

    @property
    def method(self) -> str:
        return self._method

    @property
    def path(self) -> str:
        return self._path

    @property
    def url(self) -> str:
        return self._url

    @property
    def query(self) -> str:
        """Raw query string, e.g. ``page=2&limit=10``."""
        return self._query_string

    @property
    def headers(self) -> dict[str, str]:
        return self._headers

    @property
    def content_type(self) -> Optional[str]:
        return self._headers.get("Content-Type")

    @property
    def content_length(self) -> Optional[int]:
        raw = self._headers.get("Content-Length")
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    @property
    def body(self) -> bytes:
        return self._body_bytes

    @property
    def text(self) -> str:
        if self._text is None:
            self._text = self._body_bytes.decode("utf-8", errors="replace")
        return self._text

    @property
    def json(self) -> Any:
        if self._json is _UNSET:
            self._json = self._parse_json()
        return self._json

    @property
    def form(self) -> dict[str, Any]:
        if self._form is None:
            self._form = self._parse_form()
        return self._form

    @property
    def files(self) -> Optional[dict[str, Any]]:
        if self._files is None:
            self._files = self._parse_files()
        return self._files

    @property
    def cookies(self) -> dict[str, str]:
        if self._cookies is None:
            self._cookies = self._parse_cookies()
        return self._cookies

    @property
    def args(self) -> dict[str, Any]:
        """Query parameters as a flat dict.

        Repeated parameters are collapsed to a single value when only one
        occurrence exists; otherwise the list is preserved.
        """
        if self._args is None:
            self._args = _flatten_qs(self.query_params)
        return self._args

    @property
    def query_params(self) -> dict[str, list[str]]:
        """Query parameters parsed with ``parse_qs``, preserving repeats."""
        if self._query is None:
            self._query = parse_qs(self._query_string, keep_blank_values=True)
        return self._query

    @property
    def remote_addr(self) -> str:
        return self._remote_addr

    @property
    def server_name(self) -> str:
        return self._server_name

    @property
    def server_port(self) -> str:
        return self._server_port

    # -- internal helpers ------------------------------------------------------

    def _check_body_size(self) -> None:
        length = self.content_length
        if length is not None and length > self._max_body_size:
            raise _RequestError(
                413,
                "Content Too Large",
                f"Request body size ({length} bytes) exceeds the "
                f"maximum allowed ({self._max_body_size} bytes).",
            )

    def _parse_json(self) -> Any:
        self._check_body_size()
        ct = (self.content_type or "").lower()
        if not ct.startswith("application/json"):
            # Return None instead of raising when there's no JSON content-type.
            # This allows handlers that check request.json on non-JSON requests
            # to get None rather than an error.
            return None
        if not self._body_bytes:
            return None
        try:
            return json.loads(self._body_bytes)
        except json.JSONDecodeError as exc:
            raise _RequestError(
                400,
                "Bad Request",
                f"Malformed JSON body: {exc}",
            ) from exc

    def _parse_form(self) -> dict[str, Any]:
        self._check_body_size()
        ct = (self.content_type or "").lower()
        body = self._body_bytes
        if not body:
            return {}
        if "application/x-www-form-urlencoded" in ct:
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise _RequestError(
                    400,
                    "Bad Request",
                    "URL-encoded form body is not valid UTF-8.",
                ) from exc
            parsed = parse_qs(text, keep_blank_values=True)
            return _flatten_qs(parsed)
        if "multipart/form-data" in ct:
            return self._parse_multipart_form()
        # Not a supported form content type — return an empty form so that
        # handlers that check ``request.form`` still get a dict.
        return {}

    def _parse_files(self) -> Optional[dict[str, Any]]:
        ct = (self.content_type or "").lower()
        if "multipart/form-data" not in ct:
            return None
        return self._parse_multipart_files()

    def _parse_multipart_form(self) -> dict[str, Any]:
        form, _ = _parse_multipart(self._body_bytes, self._headers.get("Content-Type", ""))
        return form

    def _parse_multipart_files(self) -> Optional[dict[str, Any]]:
        _, files = _parse_multipart(self._body_bytes, self._headers.get("Content-Type", ""))
        return files

    def _parse_cookies(self) -> dict[str, str]:
        raw = self._headers.get("Cookie", "")
        if not raw:
            return {}
        result: dict[str, str] = {}
        for part in raw.split(";"):
            part = part.strip()
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            result[name.strip()] = value.strip()
        return result


_UNSET = object()  # sentinel used for lazy properties


def _flatten_qs(qs: dict[str, list[str]]) -> dict[str, Any]:
    """Turn ``parse_qs`` output into a friendlier dict.

    When a key appears once the value is returned directly; repeated keys
    keep their list so callers can still detect multiple values.
    """
    out: dict[str, Any] = {}
    for key, values in qs.items():
        if len(values) == 1:
            out[key] = values[0]
        else:
            out[key] = values
    return out


# ---------------------------------------------------------------------------
# Minimal multipart parser — no third-party dependency
# ---------------------------------------------------------------------------

def _parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Parse a multipart/form-data body into (form_fields, files).

    This is intentionally lightweight. It handles the common boundary-driven
    layout produced by browsers and the stdlib ``cgi`` module. File payloads
    are returned as dicts with ``filename``, ``content_type``, and ``data``
    keys so that callers can choose to store them to disk or keep them in
    memory.
    """
    form: dict[str, Any] = {}
    files: dict[str, Any] = {}

    if not body:
        return form, files

    # Extract the boundary from the Content-Type header.
    boundary = _extract_boundary(content_type)
    if boundary is None:
        return form, files

    boundary_bytes = boundary.encode("utf-8")
    # The proper delimiter is "--" + boundary, but some test data uses just
    # the boundary without the "--" prefix. Handle both cases.
    delimiter = b"--" + boundary_bytes
    alt_delimiter = boundary_bytes  # for non-standard bodies

    def find_part_boundaries(body: bytes, delim: bytes) -> list[tuple[int, int]]:
        """Find (start, end) positions of parts between delimiters.

        Handles both:
        - Standard format: --boundary ... --boundary-- (closing)
        - Non-standard format: boundary ... boundary-- (closing)
        """
        parts = []
        idx = 0
        while True:
            idx = body.find(delim, idx)
            if idx == -1:
                break

            # Check if this is a closing delimiter (delim followed by "--")
            closing_marker = idx + len(delim)
            is_closing = body[closing_marker:closing_marker + 2] == b"--"

            if is_closing:
                # This is the closing delimiter, we're done
                break

            content_start = idx + len(delim)
            # Skip leading CRLF if present
            if body[content_start:content_start + 2] == b"\r\n":
                content_start += 2
            elif body[content_start:content_start + 1] == b"\n":
                content_start += 1

            # Find the next delimiter to determine end of this part
            next_idx = body.find(delim, content_start)
            if next_idx == -1:
                # No more delimiters, this is the last part (might end with closing)
                closing = delim + b"--"
                close_idx = body.find(closing, content_start)
                if close_idx != -1:
                    parts.append((content_start, close_idx))
                else:
                    # No closing found, take rest of body
                    parts.append((content_start, len(body)))
                break

            parts.append((content_start, next_idx))
            idx = next_idx
        return parts

    # Try the proper delimiter first
    parts = find_part_boundaries(body, delimiter)
    used_delimiter = delimiter
    if not parts:
        # Try the alternative (non-standard) delimiter
        parts = find_part_boundaries(body, alt_delimiter)
        used_delimiter = alt_delimiter

    for content_start, content_end in parts:
        part_data = body[content_start:content_end]
        # Note: we do NOT strip trailing CRLF here because in some formats
        # (e.g., when the boundary in the body doesn't have the -- prefix),
        # the CRLF before the boundary is part of the payload.

        header_block, _, payload = part_data.partition(b"\r\n\r\n")
        if header_block:
            headers = _parse_multipart_headers(header_block)
            # Headers are lowercased by _parse_multipart_headers
            content_disposition = headers.get("content-disposition", "")

            name = _cd_field(content_disposition, "name")
            filename = _cd_field(content_disposition, "filename")

            if name is not None:
                if filename:
                    files[name] = {
                        "filename": filename,
                        "content_type": headers.get("content-type", "application/octet-stream"),
                        "data": payload,
                    }
                else:
                    # For form fields, strip trailing CRLF as it's part of the delimiter
                    if payload.endswith(b"\r\n"):
                        payload = payload[:-2]
                    elif payload.endswith(b"\n"):
                        payload = payload[:-1]
                    form[name] = payload.decode("utf-8", errors="replace")

    return form, files


def _extract_boundary(content_type: str) -> Optional[str]:
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            value = part[len("boundary="):]
            # Strip surrounding quotes if present.
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value
    return None


def _parse_multipart_headers(header_block: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in header_block.split(b"\r\n"):
        if b":" not in line:
            continue
        name, value = line.split(b":", 1)
        result[name.decode("utf-8", errors="replace").strip().lower()] = (
            value.decode("utf-8", errors="replace").strip()
        )
    return result


def _cd_field(content_disposition: str, field: str) -> Optional[str]:
    """Extract a field from a Content-Disposition header value."""
    for part in content_disposition.split(";"):
        part = part.strip()
        if part.lower().startswith(field + "="):
            value = part[len(field) + 1:].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value
    return None


# ---------------------------------------------------------------------------
# Request-error helper — turned into a proper HTTP response by the handler
# ---------------------------------------------------------------------------

class _RequestError(Exception):
    """A client error that should be rendered as an HTTP error response."""

    def __init__(self, status: int, title: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.title = title
        self.detail = detail


# ---------------------------------------------------------------------------
# Current-request contextvar
# ---------------------------------------------------------------------------

_current_request: ContextVar[Optional[Request]] = ContextVar(
    "nexa_current_request", default=None
)

# ---------------------------------------------------------------------------
# Current-server contextvar (for template loader auto-binding)
# ---------------------------------------------------------------------------

_current_server: ContextVar[Optional[NXserver]] = ContextVar(
    "nexa_current_server", default=None
)


def get_request() -> Request:
    """Return the request currently being handled.

    Raises ``RuntimeError`` when called outside of an active request context
    (for example, during application startup before the server accepts a
    connection).
    """
    req = _current_request.get()
    if req is None:
        raise RuntimeError(
        "nxserver.request is only available inside a route handler that is "
            "processing an HTTP request. There is no active request right now."
        )
    return req


# ---------------------------------------------------------------------------
# Current-request proxy object
# ---------------------------------------------------------------------------

class _RequestProxy:
    """A proxy that forwards attribute access to the current request.

    This allows ``from nxserver import request`` and then ``request.method``,
    ``request.json``, etc. While a request is active this behaves like the
    request object; outside a request it raises a clear RuntimeError.
    """

    def __getattribute__(self, name: str) -> Any:
        if name in {"__class__", "__dict__", "__wrapper__", "__wrapped__", "__spec__"}:
            return super().__getattribute__(name)
        req = get_request()
        return getattr(req, name)

    def __dir__(self) -> list[str]:
        try:
            return dir(get_request())
        except RuntimeError:
            return []


# Re-export the request object under the short name that the PRD documents.
import __main__ as _main

_request_proxy_singleton = _RequestProxy()
if getattr(_main, "__file__", None) == __file__:
    request = _request_proxy_singleton
else:
    request = _request_proxy_singleton



# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


class Response:
    """A building block for HTTP responses.

    Example usage::

        return Response("Created", status=201, headers={"X-Powered-By": "Nexa"})
    """

    def __init__(
        self,
        body: Any = "",
        status: int = 200,
        content_type: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.body = body
        self.status = status
        self.content_type = content_type
        self.headers = headers or {}

    def render(self) -> tuple[bytes, str, int, dict[str, str]]:
        """Return ``(body_bytes, content_type, status, extra_headers)``."""
        headers = dict(self.headers)

        if isinstance(self.body, bytes):
            body_bytes = self.body
        elif isinstance(self.body, str):
            body_bytes = self.body.encode("utf-8")
        elif self.body is None:
            body_bytes = b""
        else:
            body_bytes = str(self.body).encode("utf-8")

        header_content_type = next(
            (
                value
                for name, value in headers.items()
                if name.lower() == "content-type"
            ),
            None,
        )
        if self.content_type:
            content_type = self.content_type
        elif header_content_type:
            content_type = header_content_type
        elif body_bytes:
            content_type = "text/html; charset=utf-8"
        else:
            content_type = "text/html; charset=utf-8"

        return body_bytes, content_type, self.status, headers


def redirect(location: str, status: int = 302, headers: Optional[dict[str, str]] = None) -> Response:
    """Return a redirect response.

    Args:
        location: The URL to redirect to.
        status: HTTP status code. Defaults to 302 (Found). Use 301 for a
            permanent redirect or 303/307/308 as appropriate.
        headers: Extra headers to include in the response.

    Example::

        return redirect("/login")
        return redirect("https://example.com", status=301)
    """
    h = {"Location": location}
    if headers:
        h.update(headers)
    return Response("", status=status, headers=h)


def html(body: str, status: int = 200, headers: Optional[dict[str, str]] = None) -> Response:
    """Return an HTML response."""
    h = dict(headers) if headers else {}
    h.setdefault("Content-Type", "text/html; charset=utf-8")
    return Response(body, status=status, content_type="text/html; charset=utf-8", headers=h)


def text(body: str, status: int = 200, content_type: Optional[str] = None, headers: Optional[dict[str, str]] = None) -> Response:
    """Return a plain-text response."""
    if content_type is None:
        content_type = "text/plain; charset=utf-8"
    h = dict(headers) if headers else {}
    h.setdefault("Content-Type", content_type)
    return Response(body, status=status, content_type=content_type, headers=h)


def json_response(data: Any, status: int = 200, headers: Optional[dict[str, str]] = None) -> Response:
    """Return a JSON response (uses ``__json.jsonify`` under the hood)."""
    jr = _jsonify(data, status=status)
    # json_response should return a Response with the JSON body pre-encoded.
    return Response(jr.render(), status=status, content_type="application/json; charset=utf-8", headers=headers)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

_METHOD_NAMES = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


@dataclass
class _Route:
    pattern: str
    handler: Callable
    methods: set[str] = field(default_factory=lambda: {"GET", "HEAD"})
    param_names: list[str] = field(default_factory=list)
    original_path: str = ""


class Router:
    """A small path-router with support for static and parameterized routes.

    Parameterized paths look like ``"/api/users/<user_id>"``. Parameter names
    must be valid Python identifiers. Static routes take priority over
    parameterized ones, and more-specific parameterized routes are preferred
    over less-specific ones when the number of static segments is equal.
    """

    def __init__(self) -> None:
        self._static: dict[str, _Route] = {}
        self._params: list[_Route] = []
        # Aliases for the DevTools property on NXserver.
        self._static_routes = self._static
        self._param_routes = self._params

    def add(
        self,
        path: str,
        handler: Callable,
        methods: set[str] | None = None,
    ) -> None:
        if not path.startswith("/"):
            raise ValueError("Routes must start with '/'")

        # Normalize method names to uppercase.
        if methods is not None:
            method_set = {m.upper() for m in methods}
        else:
            method_set = {"GET", "HEAD"}
        # HEAD is implicitly allowed wherever GET is allowed,
        # and also wherever any other methods are registered.
        if "HEAD" not in method_set:
            method_set.add("HEAD")

        route = self._build_route(path, handler, method_set)
        route._original_path = path
        if self._is_param_path(path):
            self._params.append(route)
        else:
            if path in self._static:
                raise ValueError(f"Route {path!r} already registered")
            self._static[path] = route

    def _build_route(
        self, path: str, handler: Callable, methods: set[str]
    ) -> _Route:
        param_names: list[str] = []
        segments: list[str] = []
        for seg in path.strip("/").split("/"):
            if not seg:
                continue
            if seg.startswith("<") and seg.endswith(">"):
                name = seg[1:-1]
                if not name.isidentifier():
                    raise ValueError(
                        f"Invalid parameter name {name!r} in route {path!r}"
                    )
                param_names.append(name)
                segments.append(None)  # placeholder for a param segment
            else:
                segments.append(seg)
        pattern = "/" + "/".join(
            f"<{i}>" if s is None else s for i, s in enumerate(segments)
        )
        return _Route(pattern=pattern, handler=handler, methods=methods, param_names=param_names, original_path=path)

    def _is_param_path(self, path: str) -> bool:
        return "<" in path

    def match(self, path: str) -> tuple[Optional[_Route], dict[str, str]]:
        """Return ``(route, params)`` or ``(None, {})`` when there is no match."""
        # Exact static match first.
        if path in self._static:
            return self._static[path], {}

        # Attempt parameterized routes. Among matching parameterized routes
        # prefer the one with the most literal segments (most specific).
        best: Optional[_Route] = None
        best_params: dict[str, str] = {}
        best_literal_count = -1

        for route in self._params:
            params = self._match_param_route(route, path)
            if params is None:
                continue
            literal_count = sum(1 for seg in route.pattern.strip("/").split("/") if not seg.startswith("<"))
            if literal_count > best_literal_count:
                best = route
                best_params = params
                best_literal_count = literal_count

        if best is not None:
            return best, best_params
        return None, {}

    def _match_param_route(self, route: _Route, path: str) -> Optional[dict[str, str]]:
        route_segments = [s for s in route.pattern.strip("/").split("/") if s]
        path_segments = [s for s in path.strip("/").split("/") if s]

        if len(route_segments) != len(path_segments):
            return None

        params: dict[str, str] = {}
        for rs, ps in zip(route_segments, path_segments):
            if rs.startswith("<"):
                params[route.param_names[len(params)]] = ps
            elif rs != ps:
                return None
        return params

    def route_for_path(self, path: str) -> Optional[_Route]:
        """Return any route registered for *path*, ignoring method."""
        if path in self._static:
            return self._static[path]
        for route in self._params:
            if self._match_param_route(route, path) is not None:
                return route
        return None


# ---------------------------------------------------------------------------
# CORS configuration
# ---------------------------------------------------------------------------

@dataclass
class CorsConfig:
    """Cross-Origin Resource Sharing configuration.

    By default CORS is disabled. Enable it explicitly for the origins you
    want to allow.
    """

    enabled: bool = False
    allowed_origins: list[str] = field(default_factory=list)
    allowed_methods: list[str] = field(
        default_factory=lambda: ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    )
    allowed_headers: list[str] = field(
        default_factory=lambda: ["Content-Type", "Authorization", "X-Requested-With"]
    )
    expose_headers: list[str] = field(default_factory=list)
    max_age: int = 600
    allow_credentials: bool = False

    def is_origin_allowed(self, origin: Optional[str]) -> bool:
        if not self.enabled or not origin:
            return False
        if "*" in self.allowed_origins:
            return True
        return origin in self.allowed_origins

    def echo_origin(self, origin: Optional[str]) -> Optional[str]:
        if not self.enabled or not origin:
            return None
        if "*" in self.allowed_origins:
            return origin if self.allow_credentials else "*"
        if origin in self.allowed_origins:
            return origin
        return None


# ---------------------------------------------------------------------------
# NXserver — the main HTTP server class
# ---------------------------------------------------------------------------


class NXserver:
    """Nexa's built-in HTTP server.

    Example::

        from Nexa import NXserver, jsonify

        server = NXserver("myapp", port=3000)
        server.get("/")(lambda: jsonify({"hello": "world"}))
        server.run()
    """

    def __init__(
        self,
        name: str,
        port: int = 3000,
        static_folder: str = "static",
        template_folder: str = "templates",
        max_body_size: int = 1_048_576,  # 1 MiB default
        cors: Optional[CorsConfig] = None,
        debug: bool = False,
        host: str = "127.0.0.1",
    ) -> None:
        self.name = name
        if isinstance(port, bool):
            raise ValueError("Invalid port; expected an integer between 0 and 65535.")
        try:
            self.port = int(port) if isinstance(port, str) else operator.index(port)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid port {port!r}; expected an integer between 0 and 65535."
            ) from exc
        if not 0 <= self.port <= 65535:
            raise ValueError(
                f"Invalid port {self.port}; expected an integer between 0 and 65535."
            )
        if not isinstance(host, str) or not host.strip():
            raise ValueError(
                "Invalid host; use '127.0.0.1', '0.0.0.0', 'localhost', "
                "or a local IPv4 address."
            )
        host = host.strip()
        if host.lower() != "localhost":
            try:
                ipaddress.IPv4Address(host)
            except ipaddress.AddressValueError as exc:
                raise ValueError(
                    f"Invalid host {host!r}; use '127.0.0.1', '0.0.0.0', "
                    "'localhost', or a local IPv4 address."
                ) from exc
        self.host = host
        self.static_folder = static_folder
        self.template_folder = template_folder
        self.max_body_size = max_body_size
        self.cors = cors or CorsConfig()
        self.debug = debug

        self.router = Router()
        self._before_request_handlers: list[Callable[[Request], None]] = []
        self._after_request_handlers: list[Callable[[Any, int, dict[str, str]], Any]] = []
        self._blueprints: list[Any] = []
        self._startup_handlers: list[Callable[[], None]] = []
        self._shutdown_handlers: list[Callable[[], None]] = []
        self._error_handlers: dict[type[BaseException], Callable[[Request, BaseException], tuple[bytes, int, dict[str, str]]]] = {}
        self._ws_handlers: dict[str, Callable] = {}
        self._devtools: Optional["DevTools"] = None  # noqa: F821 (lazy import)
        self._mount: Optional["DevTools._DevToolsMount"] = None  # noqa: F821 (lazy import)

        project_dir = Path.cwd().resolve()
        self.project_dir = project_dir
        self.static_dir = (project_dir / static_folder).resolve()
        self.template_dir = (project_dir / template_folder).resolve()

    # -- route registration ---------------------------------------------------

    def route(self, path: str, methods: Optional[list[str]] = None):
        """Register a handler for *path*.

        Args:
            path: URL path, e.g. ``"/"`` or ``"/api/users/<id>"``.
            methods: Optional explicit list of HTTP methods. When omitted the
                handler responds to GET and HEAD.

        Example::

            @server.route("/")
            def home():
                return "<h1>Hello</h1>"

            @server.route("/api/users", methods=["GET", "POST"])
            def users():
                ...
        """
        method_set: set[str] | None = None
        if methods is not None:
            method_set = set(m.upper() for m in methods)
            # Validate method names.
            for m in method_set:
                if m not in _METHOD_NAMES and m != "HEAD":
                    raise ValueError(f"Unsupported HTTP method {m!r}")

        def decorator(handler: Callable):
            self.router.add(path, handler, method_set)
            return handler

        return decorator

    def ws(self, path: str):
        """Register an async WebSocket handler for *path*.

        The handler receives a :class:`~Nexa.websocket.WebSocket` and can use
        ``async for message in ws:`` to read messages and
``ws.send_text(...)`` / ``ws.send_bytes(...)`` / ``ws.close(...)`` to send
        data.  The connection is upgraded only when the client sends a proper
        ``Sec-WebSocket-Key`` header.

        Example::

            async def echo(ws):
                async for message in ws:
                    await ws.send_text(f"echo: {message}")

            server.ws("/chat")(echo)
        """
        def decorator(ws_handler):
            self._ws_handlers[path] = ws_handler
            return ws_handler
        return decorator

        return decorator

    def get(self, path: str):
        return self.route(path, methods=["GET"])

    def post(self, path: str):
        return self.route(path, methods=["POST"])

    def put(self, path: str):
        return self.route(path, methods=["PUT"])

    def patch(self, path: str):
        return self.route(path, methods=["PATCH"])

    def delete(self, path: str):
        return self.route(path, methods=["DELETE"])

    def options(self, path: str):
        return self.route(path, methods=["OPTIONS"])

    def head(self, path: str):
        return self.route(path, methods=["HEAD"])

    # -- lifecycle hooks (optional, convenient for middleware) --------------

    def before_request(self, handler: Callable[[Request], None]):
        """Register a hook that runs before every request.

        The hook receives the current :class:`Request` and may raise
        :class:`_RequestError` to short-circuit the request with an error
        response.
        """
        self._before_request_handlers.append(handler)
        return handler

    def after_request(self, handler: Callable[..., Any]):
        """Register a hook that runs after a route returns, before the response
        is sent.

        The hook receives ``(response_body, status, headers)`` and should
        return a triple with the same shape.
        """
        self._after_request_handlers.append(handler)
        return handler

    def on_startup(self, handler: Callable[[], None]):
        """Register a hook that runs once when the server starts accepting
        connections.

        Startup hooks run in registration order after the server socket is
        bound but before the first request is served.
        """
        self._startup_handlers.append(handler)
        return handler

    def on_shutdown(self, handler: Callable[[], None]):
        """Register a hook that runs once when the server stops accepting
        connections.

        Shutdown hooks run in registration order after ``serve_forever()``
        returns (for example on ``KeyboardInterrupt``) but before the server
        socket is closed.
        """
        self._shutdown_handlers.append(handler)
        return handler

    def error_handler(
        self, exc_type: type[BaseException]
    ) -> Callable[
        [Callable[[Request, BaseException], tuple[bytes, int, dict[str, str]]]],
        Callable[[Request, BaseException], tuple[bytes, int, dict[str, str]]],
    ]:
        """Register a custom error handler for *exc_type*.

        Usage::

            @server.error_handler(ValueError)
            def handle_value_error(request, exc):
                return b'{"error":"bad value"}', 400, {}

        When a route or hook raises an exception of the given type, the
        handler is called with the current request and the exception and must
        return ``(body_bytes, status, headers_dict)``.

        Handlers are matched most-specific-first (subclass before base class).
        """

        def decorator(
            handler: Callable[[Request, BaseException], tuple[bytes, int, dict[str, str]]],
        ) -> Callable[[Request, BaseException], tuple[bytes, int, dict[str, str]]]:
            self._error_handlers[exc_type] = handler
            return handler

        return decorator

    @property
    def registered_routes(self) -> list[tuple[str, list[str], str]]:
        """Return a list of ``(path, methods, handler_name)`` for all
        registered routes.

        This is used by the DevTools route inspector and the ``nexa routes``
        CLI command.
        """
        rows: list[tuple[str, list[str], str]] = []
        for path, route in self._static_routes.items():
            rows.append((path, sorted(route.methods), route.handler.__name__ if hasattr(route.handler, "__name__") else str(route.handler)))
        for route in self._param_routes:
            rows.append((route._original_path, sorted(route.methods), route.handler.__name__ if hasattr(route.handler, "__name__") else str(route.handler)))
        return rows

    @property
    def registered_middleware(self) -> list[tuple[str, int]]:
        """Return a list of ``(name, priority)`` for currently registered
        middleware, in the order they will be applied.

        This is used by the DevTools middleware inspector.
        """
        try:
            from .middleware import Middleware
            return [
                (m.name or "unnamed", m.priority)
                for m in Middleware._middlewares
            ]
        except Exception:
            return []

    def register_blueprint(self, blueprint: "Blueprint") -> None:  # noqa: F821
        """Register a :class:`Blueprint` on this server.

        All routes defined on the blueprint are registered with their paths
        prefixed by the blueprint's prefix. Duplicate route registration and
        repeated blueprint registration are detected and raise ``ValueError``.

        Example::

            api = Blueprint("api", prefix="/api")

            @api.get("/ping")
            def pong():
                return jsonify({"status": "ok"})

            app.register_blueprint(api)
        """
        if blueprint in self._blueprints:
            raise ValueError(
                f"Blueprint {blueprint.name!r} has already been registered."
            )
        self._blueprints.append(blueprint)
        for route_path, handler, methods in blueprint._routes:
            combined_path = self._combine_paths(blueprint.prefix, route_path)
            try:
                self.router.add(combined_path, handler, methods)
            except ValueError as exc:
                if "already registered" in str(exc):
                    raise ValueError(
                        f"Duplicate route {combined_path!r} from blueprint "
                        f"{blueprint.name!r}."
                    ) from exc
                raise

    def _combine_paths(self, prefix: str, path: str) -> str:
        """Combine a blueprint prefix and a route path without duplicate or
        missing slashes.
        """
        prefix = prefix.strip("/")
        path = path.strip("/")
        if not prefix and not path:
            return "/"
        if not prefix:
            return "/" + path
        if not path:
            return "/" + prefix
        return "/" + prefix + "/" + path

    def __call__(self, environ: dict[str, Any], start_response: Callable) -> list[bytes]:
        """Serve a WSGI request directly through this application instance."""
        return self.wsgi_app(environ, start_response)

    def wsgi_app(self, environ: dict[str, Any], start_response: Callable) -> list[bytes]:
        """Handle one WSGI request and return an iterable containing bytes."""
        req: Optional[Request] = None
        try:
            req = self._build_wsgi_request(environ)
            body, status, headers = self._process_request(req)
        except _RequestError as exc:
            body, status, headers = self._error_response(
                exc.status, exc.title, exc.detail
            )

        status_line = self._status_line(status)
        start_response(status_line, headers)
        return [b"" if req is not None and req.method == "HEAD" else body]

    def _build_wsgi_request(self, environ: dict[str, Any]) -> Request:
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "")
        query_string = environ.get("QUERY_STRING", "")
        if not isinstance(method, str) or not isinstance(path, str):
            raise _RequestError(400, "Bad Request", "Invalid request method or path.")
        if not isinstance(query_string, str):
            raise _RequestError(400, "Bad Request", "Invalid query string.")

        method = method.upper()
        headers: dict[str, str] = {}
        for key, value in environ.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            if key.startswith("HTTP_"):
                name = key[5:].replace("_", "-").title()
                headers[name] = value
        for key, name in (
            ("CONTENT_TYPE", "Content-Type"),
            ("CONTENT_LENGTH", "Content-Length"),
        ):
            value = environ.get(key)
            if value is not None and not isinstance(value, str):
                raise _RequestError(400, "Bad Request", f"Invalid {name} header.")
            if value:
                headers[name] = value

        body_bytes = self._read_wsgi_body(environ, headers.get("Content-Length"))
        server_name = environ.get("SERVER_NAME", "")
        server_port = environ.get("SERVER_PORT", "")
        url = f"{path}?{query_string}" if query_string else path
        if not url and server_name:
            url = f"{environ.get('wsgi.url_scheme', 'http')}://{server_name}"
            if server_port:
                url += f":{server_port}"
        remote_addr = environ.get("REMOTE_ADDR", "")

        return Request(
            method=method,
            path=path,
            url=url,
            query_string=query_string,
            headers=headers,
            body_bytes=body_bytes,
            remote_addr=remote_addr if isinstance(remote_addr, str) else "",
            max_body_size=self.max_body_size,
            server_name=server_name if isinstance(server_name, str) else "",
            server_port=server_port if isinstance(server_port, str) else "",
        )

    def _read_wsgi_body(
        self, environ: dict[str, Any], content_length: Optional[str]
    ) -> bytes:
        if content_length is None or content_length == "":
            length = None
        elif (
            not isinstance(content_length, str)
            or not content_length.isascii()
            or not content_length.isdigit()
        ):
            raise _RequestError(400, "Bad Request", "Invalid Content-Length header.")
        else:
            try:
                length = int(content_length)
            except ValueError as exc:
                raise _RequestError(
                    413,
                    "Content Too Large",
                    f"Request body exceeds the maximum allowed "
                    f"({self.max_body_size} bytes).",
                ) from exc
            if length > self.max_body_size:
                raise _RequestError(
                    413,
                    "Content Too Large",
                    f"Request body size ({length} bytes) exceeds the "
                    f"maximum allowed ({self.max_body_size} bytes).",
                )

        stream = environ.get("wsgi.input", io.BytesIO())
        if not hasattr(stream, "read"):
            raise _RequestError(400, "Bad Request", "Invalid WSGI request body stream.")

        try:
            if length is None:
                chunks = bytearray()
                while len(chunks) <= self.max_body_size:
                    chunk = stream.read(self.max_body_size + 1 - len(chunks))
                    if not isinstance(chunk, bytes):
                        raise TypeError("wsgi.input must return bytes")
                    if not chunk:
                        return bytes(chunks)
                    chunks.extend(chunk)
                raise _RequestError(
                    413,
                    "Content Too Large",
                    f"Request body size exceeds the maximum allowed "
                    f"({self.max_body_size} bytes).",
                )

            chunks = bytearray()
            while len(chunks) < length:
                chunk = stream.read(length - len(chunks))
                if not isinstance(chunk, bytes):
                    raise TypeError("wsgi.input must return bytes")
                if not chunk:
                    raise _RequestError(
                        400, "Bad Request", "Request body is shorter than Content-Length."
                    )
                chunks.extend(chunk)
            return bytes(chunks)
        except _RequestError:
            raise
        except Exception as exc:
            raise _RequestError(
                400, "Bad Request", f"Could not read request body: {exc}"
            ) from exc

    def _process_request(self, req: Request) -> tuple[bytes, int, list[tuple[str, str]]]:
        req_token = _current_request.set(req)
        server_token = _current_server.set(self)
        try:
            # DevTools hidden mount — only active when debug=True.
            if self.debug:
                _get_devtools()  # trigger lazy import side-effect
                dt = self._devtools
                if dt is not None and req.path.startswith("/__nexa__"):
                    body, status, headers = dt._mount.dispatch(req)
                    return self._prepare_response(body, headers.get("Content-Type", "text/html; charset=utf-8"), status, headers)

            for hook in self._before_request_handlers:
                try:
                    hook(req)
                except _RequestError as exc:
                    return self._error_response(exc.status, exc.title, exc.detail)
                except Exception:
                    if self.debug:
                        traceback.print_exc()
                    return self._error_response(
                        500,
                        "Internal Server Error",
                        "A before-request hook raised an error.",
                    )

            if req.method == "OPTIONS" and self.cors.is_origin_allowed(
                req.headers.get("Origin")
            ):
                return self._options_response(req)

            route, params = self.router.match(req.path)
            if route is None:
                any_route = self.router.route_for_path(req.path)
                if any_route is not None:
                    allowed = ", ".join(sorted(any_route.methods))
                    return self._error_response(
                        405,
                        "Method Not Allowed",
                        f"The method {req.method} is not allowed for this URL.",
                        {"Allow": allowed},
                    )
                return self._error_response(
                    404, "Not Found", f"No route registered for {req.path!r}."
                )

            if req.method not in route.methods:
                allowed = ", ".join(sorted(route.methods))
                return self._error_response(
                    405,
                    "Method Not Allowed",
                    f"The method {req.method} is not allowed for this URL.",
                    {"Allow": allowed},
                )

            try:
                response = route.handler(**params) if route.param_names else route.handler()
                body, content_type, status, headers = self._normalize_response(response)
            except _RequestError as exc:
                return self._error_response(exc.status, exc.title, exc.detail)
            except Exception as exc:
                handler = self._find_error_handler(type(exc))
                if handler is not None:
                    return handler(req, exc)
                if self.debug:
                    traceback.print_exc()
                return self._error_response(
                    500,
                    "Internal Server Error",
                    "An unexpected error occurred while handling the request.",
                )

            for hook in self._after_request_handlers:
                try:
                    result = hook(body, status, dict(headers))
                    if len(result) == 4:
                        body, content_type, status, headers = result
                    elif len(result) == 3:
                        body, status, headers = result
                        content_type = next(
                            (
                                value
                                for name, value in headers.items()
                                if name.lower() == "content-type"
                            ),
                            content_type,
                        )
                    else:
                        raise ValueError("after-request hooks must return a 3- or 4-item tuple")
                    if not isinstance(headers, dict):
                        raise TypeError("after-request hook headers must be a dict")
                    if isinstance(body, str):
                        body = body.encode("utf-8")
                    elif not isinstance(body, bytes):
                        body = str(body).encode("utf-8")
                except Exception:
                    if self.debug:
                        traceback.print_exc()
                    return self._error_response(
                        500,
                        "Internal Server Error",
                        "An after-request hook raised an error.",
                    )

            try:
                return self._prepare_response(body, content_type, status, headers)
            except Exception:
                if self.debug:
                    traceback.print_exc()
                return self._error_response(
                    500,
                    "Internal Server Error",
                    "Could not construct the response.",
                )
        finally:
            _unbind_loader()
            _current_server.reset(server_token)
            _current_request.reset(req_token)

    def _find_error_handler(self, exc_type: type[BaseException]) -> Optional[Callable[[Request, BaseException], tuple[bytes, int, dict[str, str]]]]:
        """Return the most-specific registered error handler for *exc_type*."""
        # Walk the MRO (excluding object) to find the most specific handler.
        for cls in exc_type.__mro__:
            if cls is object:
                break
            handler = self._error_handlers.get(cls)
            if handler is not None:
                return handler
        return None

    def _normalize_response(
        self, body: Any
    ) -> tuple[bytes, str, int, dict[str, str]]:
        extra_headers: dict[str, str] = {}
        if isinstance(body, JSONResponse):
            rendered = body.render()
            return (
                rendered.encode("utf-8"),
                "application/json; charset=utf-8",
                body.status,
                extra_headers,
            )
        if isinstance(body, (Element, Fragment)):
            return (
                body.render().encode("utf-8"),
                "text/html; charset=utf-8",
                200,
                extra_headers,
            )
        if isinstance(body, Response):
            response_body, content_type, status, headers = body.render()
            extra_headers.update(headers)
            return response_body, content_type, status, extra_headers
        if isinstance(body, bytes):
            return body, "text/html; charset=utf-8", 200, extra_headers
        if isinstance(body, str):
            return body.encode("utf-8"), "text/html; charset=utf-8", 200, extra_headers
        return str(body).encode("utf-8"), "text/html; charset=utf-8", 200, extra_headers

    def _options_response(self, req: Request) -> tuple[bytes, int, list[tuple[str, str]]]:
        origin = req.headers.get("Origin")
        echoed = self.cors.echo_origin(origin)
        headers = {
            "Access-Control-Allow-Origin": echoed or "*",
            "Access-Control-Allow-Methods": ", ".join(self.cors.allowed_methods),
            "Access-Control-Allow-Headers": ", ".join(self.cors.allowed_headers),
            "Access-Control-Max-Age": str(self.cors.max_age),
            "Access-Control-Expose-Headers": ", ".join(self.cors.expose_headers) or "*",
        }
        if self.cors.allow_credentials:
            headers["Access-Control-Allow-Credentials"] = "true"
        return self._prepare_response(b"", "text/plain; charset=utf-8", 204, headers)

    def _error_response(
        self,
        status: int,
        title: str,
        detail: str,
        headers: Optional[dict[str, str]] = None,
        *,
        traceback_info: Optional[str] = None,
    ) -> tuple[bytes, int, list[tuple[str, str]]]:
        payload: dict[str, Any] = {
            "error": title,
            "detail": detail,
        }
        if traceback_info is not None and self.debug:
            payload["traceback"] = traceback_info
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._prepare_response(
            body, "application/json; charset=utf-8", status, headers or {}
        )

    @staticmethod
    def _status_line(status: int) -> str:
        try:
            phrase = HTTPStatus(status).phrase
        except (ValueError, TypeError):
            phrase = "Unknown"
        return f"{status} {phrase}"

    @staticmethod
    def _prepare_response(
        body: bytes,
        content_type: str,
        status: int,
        extra_headers: dict[str, str],
    ) -> tuple[bytes, int, list[tuple[str, str]]]:
        status = int(status)
        if not 100 <= status <= 599:
            raise ValueError(f"Invalid HTTP status code {status}.")
        if not isinstance(body, bytes):
            body = str(body).encode("utf-8")

        headers: list[tuple[str, str]] = [
            ("Content-Type", str(content_type)),
            ("X-Content-Type-Options", "nosniff"),
        ]
        seen = {"content-type", "x-content-type-options"}
        for name, value in extra_headers.items():
            lower_name = name.lower()
            if lower_name in {"content-type", "content-length"}:
                continue
            if lower_name in seen:
                headers = [
                    (old_name, str(value) if old_name.lower() == lower_name else old_value)
                    for old_name, old_value in headers
                ]
            else:
                headers.append((name, str(value)))
                seen.add(lower_name)

        if status not in {204, 304} and not 100 <= status < 200:
            headers.append(("Content-Length", str(len(body))))
        else:
            body = b""
        return body, status, headers

    # -- running the server --------------------------------------------------

    def run(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = f"Nexa/{server.name}"

            def _send_response(
                self,
                body: bytes,
                content_type: str,
                status: int = 200,
                headers: Optional[dict[str, str]] = None,
            ) -> None:
                body, status, response_headers = server._prepare_response(
                    body, content_type, status, headers or {}
                )
                self._send_prepared_response(body, status, response_headers)

            def _send_prepared_response(
                self,
                body: bytes,
                status: int,
                headers: list[tuple[str, str]],
            ) -> None:
                self.send_response(status)
                for name, value in headers:
                    self.send_header(name, value)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _send_json_error(
                self, status: int, title: str, detail: str
            ) -> None:
                payload = json.dumps(
                    {"error": title, "detail": detail},
                    ensure_ascii=False,
                )
                self._send_response(
                    payload.encode("utf-8"),
                    "application/json; charset=utf-8",
                    status,
                )

            def _http_response_only(
                self,
                status: int,
                headers: dict[str, str],
            ) -> None:
                """Send a raw HTTP response with no body (used for 101 upgrades)."""
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()

            def _read_body(self, max_size: int) -> bytes:
                content_length = self.headers.get("Content-Length")
                if content_length is None:
                    return b""
                try:
                    if not content_length.isascii() or not content_length.isdigit():
                        raise ValueError
                    length = int(content_length)
                except ValueError:
                    raise _RequestError(
                        400,
                        "Bad Request",
                        "Invalid Content-Length header.",
                    )
                if length > max_size:
                    raise _RequestError(
                        413,
                        "Content Too Large",
                        f"Request body size ({length} bytes) exceeds the "
                        f"maximum allowed ({max_size} bytes).",
                    )
                if length == 0:
                    return b""
                body = self.rfile.read(length)
                if len(body) != length:
                    raise _RequestError(
                        400, "Bad Request", "Request body is shorter than Content-Length."
                    )
                return body

            def _build_request(self) -> Request:
                method = self.command
                parsed = urlparse(self.path)
                path = unquote(parsed.path)
                query_string = parsed.query
                url = self.path

                raw_headers: dict[str, str] = {}
                for key, value in self.headers.items():
                    raw_headers[key] = value

                try:
                    body_bytes = self._read_body(server.max_body_size)
                except _RequestError:
                    raise
                except Exception as exc:
                    if server.debug:
                        traceback.print_exc()
                    raise _RequestError(
                        400,
                        "Bad Request",
                        f"Could not read request body: {exc}",
                    ) from exc

                remote_addr = self.client_address[0] if self.client_address else "127.0.0.1"

                return Request(
                    method=method,
                    path=path,
                    url=url,
                    query_string=query_string,
                    headers=raw_headers,
                    body_bytes=body_bytes,
                    remote_addr=remote_addr,
                    max_body_size=server.max_body_size,
                    server_name=str(self.server.server_address[0]),
                    server_port=str(self.server.server_address[1]),
                )

            def _handle_request(self) -> None:
                try:
                    req = self._build_request()
                    body, status, headers = server._process_request(req)
                except _RequestError as exc:
                    body, status, headers = server._error_response(
                        exc.status, exc.title, exc.detail
                    )
                self._send_prepared_response(body, status, headers)

            def _try_websocket_upgrade(self) -> bool:
                """If this GET request is a WebSocket upgrade for a registered ws route, handle it."""
                if self.command != "GET":
                    return False
                upgrade = self.headers.get("Upgrade", "").lower()
                if upgrade != "websocket":
                    return False
                parsed = urlparse(self.path)
                path = unquote(parsed.path)
                ws_handler = server._ws_handlers.get(path)
                if ws_handler is None:
                    return False
                # Perform the upgrade; delegate to a daemon thread since the
                # handshake + frame loop must run concurrently with the HTTP
                # server's accept loop.
                ws_mod = _get_websocket()
                wss = ws_mod.WebSocketServer(server)
                try:
                    import threading
                    threading.Thread(
                        target=lambda: asyncio.run(
                            wss.handle(self, ws_handler)
                        ),
                        daemon=True,
                    ).start()
                except Exception:
                    if server.debug:
                        traceback.print_exc()
                return True

            # -- HTTP method dispatchers --------------------------------------

            def do_GET(self):
                if self._try_websocket_upgrade():
                    return
                self._handle_request()

            def do_HEAD(self):
                self._handle_request()

            def do_POST(self):
                self._handle_request()

            def do_PUT(self):
                self._handle_request()

            def do_PATCH(self):
                self._handle_request()

            def do_DELETE(self):
                self._handle_request()

            def do_OPTIONS(self):
                self._handle_request()

            def log_message(self, fmt, *args):
                print(f"[{server.name}] {fmt % args}")

        # Set up DevTools if debug mode is enabled.
        if self.debug:
            dt_mod = _get_devtools()
            self._devtools = dt_mod.DevTools(self)
            self._mount = dt_mod._DevToolsMount(self._devtools)
            # Subscribe DevTools to the default log ring buffer.
            _default_logger = _get_default_logger()
            _default_logger.enable_ring_buffer()
            _default_logger.subscribe_ring(self._devtools.enqueue_log)

        try:
            httpd = HTTPServer((self.host, self.port), Handler)
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE or getattr(exc, "winerror", None) == 10048:
                raise OSError(
                    f"Cannot start NXserver: {self.host}:{self.port} is already in use."
                ) from exc
            if (
                exc.errno == errno.EADDRNOTAVAIL
                or getattr(exc, "winerror", None) == 10049
            ):
                raise OSError(
                    f"Cannot bind NXserver to {self.host}:{self.port}: "
                    "the address is not assigned to a local interface."
                ) from exc
            raise

        bound_port = httpd.server_address[1]
        access_host = "127.0.0.1" if self.host == "0.0.0.0" else self.host
        print(
            f"{self.name} NXserver listening on {self.host}:{bound_port}; "
            f"access at http://{access_host}:{bound_port}"
        )

        # Configure connection-level limits and timeouts.
        # ThreadingHTTPServer reuses the listen socket across threads; set a
        # reasonable request timeout so hung clients do not hold worker threads
        # forever and exhaust the thread pool under load.
        httpd.timeout = 30.0

        # Run startup hooks once the socket is bound.
        for hook in self._startup_handlers:
            try:
                hook()
            except Exception:
                if self.debug:
                    traceback.print_exc()
                raise

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping Nexa server...")
        finally:
            # Run shutdown hooks before closing the socket.
            for hook in self._shutdown_handlers:
                try:
                    hook()
                except Exception:
                    if self.debug:
                        traceback.print_exc()
            httpd.server_close()


# Re-export jsonify so existing code that imports from this module still works.
def jsonify(data: Any, status: int = 200) -> JSONResponse:
    """Create a JSON response. This is an alias for ``__json.jsonify``."""
    return _jsonify(data, status=status)


class Nserver(NXserver):
    """Deprecated compatibility name for :class:`NXserver`."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        warnings.warn(
            "Nserver is deprecated; use NXserver instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(*args, **kwargs)
