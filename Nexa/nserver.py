from __future__ import annotations

import io
import json
import mimetypes
import os
import traceback
import urllib.parse
from contextvars import ContextVar
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, unquote, urlparse

from .nx import Element, Fragment

from .__json import JSONResponse, jsonify as _jsonify

from .template import render_template as _render_template, rndr_template as _rndr_template, install_template_hooks, _bind_loader, _unbind_loader


# Module-level aliases so route handlers that import from nserver can use
# ``render_template`` without importing from Nexa.template directly.
render_template = _render_template
rndr_template = _rndr_template


# ---------------------------------------------------------------------------
# Request context — one per concurrent call, never shared globally
# ---------------------------------------------------------------------------

class Request:
    """Holds the parsed data for the HTTP request currently being handled.

    This object is created fresh for every request and is NOT shared between
    concurrent requests. Route handlers obtain the current request through
    ``nserver.request``, which is backed by a ``contextvars.ContextVar``.
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
    ) -> None:
        self._method = method
        self._path = path
        self._url = url
        self._query_string = query_string
        self._headers = headers
        self._body_bytes = body_bytes
        self._remote_addr = remote_addr
        self._max_body_size = max_body_size

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

_current_server: ContextVar[Optional[Nserver]] = ContextVar(
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
            "nserver.request is only available inside a route handler that is "
            "processing an HTTP request. There is no active request right now."
        )
    return req


# ---------------------------------------------------------------------------
# Current-request proxy object
# ---------------------------------------------------------------------------

class _RequestProxy:
    """A proxy that forwards attribute access to the current request.

    This allows ``from nserver import request`` and then ``request.method``,
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

        if self.content_type:
            content_type = self.content_type
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
        return _Route(pattern=pattern, handler=handler, methods=methods, param_names=param_names)

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
# Nserver — the main HTTP server class
# ---------------------------------------------------------------------------


class Nserver:
    """Nexa's built-in HTTP server.

    Example::

        from nserver import Nserver, jsonify

        server = Nserver("myapp", port=3000)
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
    ) -> None:
        self.name = name
        self.port = int(port)
        self.static_folder = static_folder
        self.template_folder = template_folder
        self.max_body_size = max_body_size
        self.cors = cors or CorsConfig()
        self.debug = debug

        self.router = Router()
        self._before_request_handlers: list[Callable[[Request], None]] = []
        self._after_request_handlers: list[Callable[[Any, int, dict[str, str]], Any]] = []
        self._blueprints: list[Any] = []

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

    def register_blueprint(self, blueprint: "Blueprint") -> None:
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
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                if headers:
                    for name, value in headers.items():
                        self.send_header(name, value)
                self.end_headers()
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

            def _read_body(self, max_size: int) -> bytes:
                content_length = self.headers.get("Content-Length")
                if content_length is None:
                    return b""
                try:
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
                return self.rfile.read(length)

            def _build_request(self) -> Request:
                method = self.command
                parsed = urlparse(self.path)
                path = unquote(parsed.path)
                query_string = parsed.query
                url = self.path

                raw_headers: dict[str, str] = {}
                for key, value in self.headers.items():
                    raw_headers[key] = value

                body_bytes = b""
                if method in {"POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
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
                )

            def _handle_request(self) -> None:
                req = self._build_request()

                # Store the request and server in contextvars so route handlers
                # can access them via ``nserver.request`` and template rendering
                # can find the correct server's template folder.
                req_token = _current_request.set(req)
                server_token = _current_server.set(server)
                try:
                    # Run before-request hooks.
                    for hook in server._before_request_handlers:
                        try:
                            hook(req)
                        except _RequestError as exc:
                            self._send_json_error(exc.status, exc.title, exc.detail)
                            return
                        except Exception:
                            if server.debug:
                                traceback.print_exc()
                            self._send_json_error(
                                500, "Internal Server Error",
                                "A before-request hook raised an error."
                            )
                            return

                    # CORS preflight?
                    if req.method == "OPTIONS" and server.cors.is_origin_allowed(
                        req.headers.get("Origin")
                    ):
                        self._handle_options(req)
                        return

                    # Find a matching route.
                    route, params = server.router.match(req.path)

                    if route is None:
                        # Check whether any route exists for this path (different method).
                        any_route = server.router.route_for_path(req.path)
                        if any_route is not None:
                            allowed = ", ".join(sorted(any_route.methods))
                            self._send_json_error(
                                405,
                                "Method Not Allowed",
                                f"The method {req.method} is not allowed for this URL.",
                            )
                            self.send_header("Allow", allowed)
                            self.end_headers()
                            return
                        self._send_json_error(
                            404,
                            "Not Found",
                            f"No route registered for {req.path!r}.",
                        )
                        return

                    # Method check.
                    if req.method not in route.methods:
                        allowed = ", ".join(sorted(route.methods))
                        self._send_json_error(
                            405,
                            "Method Not Allowed",
                            f"The method {req.method} is not allowed for this URL.",
                        )
                        # end_headers sends the Allow header on the same response.
                        # We must call end_headers after _send_json_error already
                        # called send_response + send_header + end_headers — so
                        # instead rebuild the response with the Allow header.
                        self._send_response(
                            json.dumps(
                                {"error": "Method Not Allowed",
                                 "detail": f"The method {req.method} is not allowed for this URL."},
                                ensure_ascii=False,
                            ).encode("utf-8"),
                            "application/json; charset=utf-8",
                            405,
                            {"Allow": allowed},
                        )
                        return

                    # Call the handler with extracted path parameters.
                    try:
                        if route.param_names:
                            response_body = route.handler(**params)
                        else:
                            response_body = route.handler()
                    except _RequestError as exc:
                        self._send_json_error(exc.status, exc.title, exc.detail)
                        return
                    except Exception:
                        if server.debug:
                            traceback.print_exc()
                        self._send_json_error(
                            500,
                            "Internal Server Error",
                            "An unexpected error occurred while handling the request.",
                        )
                        return

                    # Normalize the response body into (bytes, content_type, status, extra_headers).
                    body_bytes, content_type, status, extra_headers = self._normalize_response(
                        response_body
                    )

                    # After-request hooks.
                    for hook in server._after_request_handlers:
                        try:
                            body_bytes, content_type, status, extra_headers = hook(
                                body_bytes, status, dict(extra_headers)
                            )
                            if isinstance(body_bytes, str):
                                body_bytes = body_bytes.encode("utf-8")
                            if isinstance(body_bytes, bytes):
                                pass
                            else:
                                body_bytes = str(body_bytes).encode("utf-8")
                        except Exception:
                            if server.debug:
                                traceback.print_exc()
                            self._send_json_error(
                                500,
                                "Internal Server Error",
                                "An after-request hook raised an error.",
                            )
                            return

                    self._send_response(body_bytes, content_type, status, extra_headers)

                finally:
                    _current_server.reset(server_token)
                    _current_request.reset(req_token)

            def _normalize_response(
                self, body: Any
            ) -> tuple[bytes, str, int, dict[str, str]]:
                """Turn a handler return value into a response tuple."""
                extra_headers: dict[str, str] = {}

                # JSONResponse (from __json.jsonify or direct construction).
                if isinstance(body, JSONResponse):
                    try:
                        rendered = body.render()
                    except Exception as exc:
                        if server.debug:
                            traceback.print_exc()
                        rendered = json.dumps(
                            {"error": "Internal Server Error",
                             "detail": "Failed to serialize JSON response."},
                            ensure_ascii=False,
                        )
                    return (
                        rendered.encode("utf-8"),
                        "application/json; charset=utf-8",
                        body.status,
                        extra_headers,
                    )

                # Element / Fragment -> HTML.
                if isinstance(body, (Element, Fragment)):
                    return (
                        body.render().encode("utf-8"),
                        "text/html; charset=utf-8",
                        200,
                        extra_headers,
                    )

                # Response object.
                if isinstance(body, Response):
                    bc, ct, st, eh = body.render()
                    extra_headers.update(eh)
                    if isinstance(bc, bytes):
                        return bc, ct, st, extra_headers
                    if isinstance(bc, str):
                        return bc.encode("utf-8"), ct, st, extra_headers
                    return str(bc).encode("utf-8"), ct, st, extra_headers

                # Strings / bytes.
                if isinstance(body, bytes):
                    return body, "text/html; charset=utf-8", 200, extra_headers
                if isinstance(body, str):
                    return body.encode("utf-8"), "text/html; charset=utf-8", 200, extra_headers

                # Anything else -> string.
                return str(body).encode("utf-8"), "text/html; charset=utf-8", 200, extra_headers

            def _handle_options(self, req: Request) -> None:
                origin = req.headers.get("Origin")
                echoed = server.cors.echo_origin(origin)
                allowed_methods = ", ".join(server.cors.allowed_methods)
                allowed_headers = ", ".join(server.cors.allowed_headers)
                expose = ", ".join(server.cors.expose_headers) or "*"

                headers = {
                    "Access-Control-Allow-Origin": echoed or "*",
                    "Access-Control-Allow-Methods": allowed_methods,
                    "Access-Control-Allow-Headers": allowed_headers,
                    "Access-Control-Max-Age": str(server.cors.max_age),
                    "Access-Control-Expose-Headers": expose,
                }
                if server.cors.allow_credentials:
                    headers["Access-Control-Allow-Credentials"] = "true"

                body = b""
                self._send_response(body, "text/plain; charset=utf-8", 204, headers)

            # -- HTTP method dispatchers --------------------------------------

            def do_GET(self):
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

        httpd = HTTPServer(("127.0.0.1", self.port), Handler)

        print(
            f"{self.name} server running at "
            f"http://127.0.0.1:{self.port}"
        )

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping Nexa server...")
        finally:
            httpd.server_close()


# Re-export jsonify so existing code that imports from nserver still works.
def jsonify(data: Any, status: int = 200) -> JSONResponse:
    """Create a JSON response. This is an alias for ``__json.jsonify``."""
    return _jsonify(data, status=status)
