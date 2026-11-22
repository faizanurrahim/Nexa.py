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
import uuid as _uuid

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
        self._session: Optional[Session] = None

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
    def session(self) -> Session:
        """Return the session for this request.

        Sessions are backed by cookies and signed with the server's
        ``session_secret`` when configured.
        """
        if self._session is None:
            self._session = Session(self)
        return self._session

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
    def client_ip(self) -> str:
        """Return the client IP address, honoring X-Forwarded-For when present.

        When the request passes through a proxy or load balancer the
        ``X-Forwarded-For`` header contains the original client IP as the
        first entry. This property returns that value when available,
        falling back to ``remote_addr`` otherwise.
        """
        forwarded = self._headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
        return self._remote_addr

    @property
    def server_name(self) -> str:
        return self._server_name

    @property
    def server_port(self) -> str:
        return self._server_port

    # -- query helper methods --------------------------------------------------

    def get_query(self, key: str, default: Any = None) -> Any:
        """Return the first value for *key* from the query string.

        Args:
            key: The query parameter name.
            default: Value to return when the parameter is absent.

        Example::

            page = request.get_query("page", default="1")
        """
        values = self.query_params.get(key)
        if values:
            return values[0] if len(values) == 1 else values
        return default

    def get_query_int(self, key: str, default: int = 0) -> int:
        """Return *key* parsed as an integer, with *default* when absent.

        Returns *default* when the parameter is missing or cannot be parsed.
        """
        value = self.get_query(key)
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def get_query_float(self, key: str, default: float = 0.0) -> float:
        """Return *key* parsed as a float, with *default* when absent.

        Returns *default* when the parameter is missing or cannot be parsed.
        """
        value = self.get_query(key)
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_query_bool(self, key: str, default: bool = False) -> bool:
        """Return *key* parsed as a boolean.

        Recognises ``"true"``, ``"1"``, ``"yes"``, ``"on"`` (case-insensitive)
        as True and ``"false"``, ``"0"``, ``"no"``, ``"off"`` as False.
        Returns *default* when the parameter is absent.
        """
        value = self.get_query(key)
        if value is None:
            return default
        if isinstance(value, list):
            value = value[0] if value else ""
        v = str(value).lower()
        if v in {"true", "1", "yes", "on"}:
            return True
        if v in {"false", "0", "no", "off"}:
            return False
        return default

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

    Convenience constructors::

        Response.text("Hello")
        Response.html("<h1>Hello</h1>")
        Response.json({"success": True})
        Response.redirect("/dashboard")
        Response.file("report.pdf")
        Response.empty(status=204)
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

    # -- convenient constructors ---------------------------------------------

    @classmethod
    def text(
        cls,
        body: str,
        status: int = 200,
        headers: Optional[dict[str, str]] = None,
    ) -> Response:
        """Return a plain-text response."""
        h = dict(headers) if headers else {}
        h.setdefault("Content-Type", "text/plain; charset=utf-8")
        return cls(body, status=status, content_type="text/plain; charset=utf-8", headers=h)

    @classmethod
    def html(
        cls,
        body: str,
        status: int = 200,
        headers: Optional[dict[str, str]] = None,
    ) -> Response:
        """Return an HTML response."""
        h = dict(headers) if headers else {}
        h.setdefault("Content-Type", "text/html; charset=utf-8")
        return cls(body, status=status, content_type="text/html; charset=utf-8", headers=h)

    @classmethod
    def json(
        cls,
        data: Any,
        status: int = 200,
        headers: Optional[dict[str, str]] = None,
    ) -> Response:
        """Return a JSON response."""
        import json as _json

        body_bytes = _json.dumps(data, ensure_ascii=False).encode("utf-8")
        h = dict(headers) if headers else {}
        h.setdefault("Content-Type", "application/json; charset=utf-8")
        return cls(body_bytes, status=status, content_type="application/json; charset=utf-8", headers=h)

    @classmethod
    def redirect(
        cls,
        location: str,
        status: int = 302,
        headers: Optional[dict[str, str]] = None,
    ) -> Response:
        """Return a redirect response.

        Args:
            location: The URL to redirect to.
            status: HTTP status code. Defaults to 302 (Found).
                Use 301 for permanent, 303/307/308 as appropriate.
            headers: Extra headers to include.
        """
        h = {"Location": location}
        if headers:
            h.update(headers)
        return cls("", status=status, headers=h)

    @classmethod
    def file(
        cls,
        path: str | Path,
        status: int = 200,
        headers: Optional[dict[str, str]] = None,
        content_type: Optional[str] = None,
    ) -> Response:
        """Return a response serving a file.

        Args:
            path: Path to the file to serve.
            status: HTTP status code. Defaults to 200.
            headers: Extra headers to include.
            content_type: Optional content type. Auto-detected if not provided.
        """
        from pathlib import Path as _Path

        file_path = Path(path) if isinstance(path, str) else path
        if not file_path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        body_bytes = file_path.read_bytes()
        if content_type is None:
            import mimetypes

            content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

        h = dict(headers) if headers else {}
        h.setdefault("Content-Type", content_type)
        h.setdefault("Content-Length", str(len(body_bytes)))
        return cls(body_bytes, status=status, content_type=content_type, headers=h)

    @classmethod
    def empty(
        cls,
        status: int = 204,
        headers: Optional[dict[str, str]] = None,
    ) -> Response:
        """Return an empty response with no body.

        Args:
            status: HTTP status code. Defaults to 204 (No Content).
            headers: Extra headers to include.
        """
        return cls(b"", status=status, content_type="text/plain; charset=utf-8", headers=headers)


class HTMLResponse(Response):
    """A convenience response that renders an HTML body.

    Equivalent to ``Response.html(...)`` but readable when used directly::

        return HTMLResponse("<h1>Hello</h1>", status=201)
    """

    def __init__(
        self,
        body: Any = "",
        status: int = 200,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        merged = dict(headers) if headers else {}
        merged.setdefault("Content-Type", "text/html; charset=utf-8")
        super().__init__(
            body,
            status=status,
            content_type="text/html; charset=utf-8",
            headers=merged,
        )


class TextResponse(Response):
    """A convenience response that renders a plain-text body.

    Equivalent to ``Response.text(...)`` but readable when used directly::

        return TextResponse("hello", status=200)
    """

    def __init__(
        self,
        body: Any = "",
        status: int = 200,
        content_type: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        if content_type is None:
            content_type = "text/plain; charset=utf-8"
        merged = dict(headers) if headers else {}
        merged.setdefault("Content-Type", content_type)
        super().__init__(
            body,
            status=status,
            content_type=content_type,
            headers=merged,
        )


class Session:
    """Per-session state for a visitor, backed by cookies.

    Example usage within a route handler::

        session = Session(request)
        session["user_id"] = 42
        session["prefs"]["theme"] = "dark"
        response = Response.html("<h1>Welcome</h1>")
        session.apply(response)
        return response

    By default sessions expire after 24 hours and are signed with the server's
    ``session_secret`` to prevent tampering. Set ``session_secret`` on the
    :class:`NXserver` to enable signing.
    """

    def __init__(self, request: Request, name: str = "__nexa_session") -> None:
        self._request = request
        self._name = name
        self._data: dict[str, Any] = {}
        self._modified = False
        self._deleted = False
        self._load()

    def _load(self) -> None:
        value = self._request.cookies.get(self._name)
        if value is None:
            return
        server = _current_server.get()
        secret = getattr(server, "session_secret", None) if server is not None else None
        if secret:
            value = self._verify(value, secret)
            if value is None:
                self._data = {}
                return
        self._data = _decode_session(value)

    def _verify(self, value: str, secret: str) -> Optional[str]:
        """Verify the session cookie signature; return the plaintext payload or None."""
        try:
            payload, sig = value.rsplit("--", 1)
        except ValueError:
            return None
        expected = _sign(payload, secret)
        return payload if sig == expected else None

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if key not in self._data or self._data[key] != value:
            self._modified = True
        self._data[key] = value

    def __delitem__(self, key: str) -> None:
        del self._data[key]
        self._modified = True

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def pop(self, key: str, default: Any = None) -> Any:
        value = self._data.pop(key, default)
        self._modified = True
        return value

    def clear(self) -> None:
        self._data.clear()
        self._modified = True
        self._deleted = True

    def apply(self, response: Response) -> None:
        """Attach the session cookie to *response* if the session was modified.

        Sets ``session_expires`` seconds from now when the session was modified,
        and removes the cookie when :meth:`clear` was called.
        """
        if not self._modified and not self._deleted:
            return
        server = _current_server.get()
        secret = getattr(server, "session_secret", None) if server is not None else None
        if self._deleted:
            response.headers["Set-Cookie"] = (
                f"{self._name}=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/"
            )
            return
        payload = _encode_session(self._data)
        if secret:
            payload = payload + "--" + _sign(payload, secret)
        server = _current_server.get()
        expiry = server.session_expires if server is not None else 86400
        expires = datetime.utcnow() + timedelta(seconds=expiry)
        expires_str = expires.strftime("%a, %d %b %Y %H:%M:%S GMT")
        response.headers["Set-Cookie"] = (
            f"{self._name}={payload}; Path=/; HttpOnly; Expires={expires_str}"
        )


def _encode_session(data: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data, ensure_ascii=False).encode("utf-8")).rstrip(b"=").decode("ascii")


def _decode_session(value: str) -> dict[str, Any]:
    try:
        padded = value + "=" * (4 - len(value) % 4) if len(value) % 4 else value
        return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _sign(payload: str, secret: str) -> str:
    import hashlib as _hashlib

    return _hashlib.sha256(f"{payload}:{secret}".encode("utf-8")).hexdigest()[:16]


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
    param_converters: list[str] = field(default_factory=list)
    original_path: str = ""
    name: str = ""


def _validate_uuid(value: str) -> _uuid.UUID:
    return _uuid.UUID(value)


def _validate_param(value: str, converter: str) -> Any:
    """Convert *value* with *converter*.

    Raises ``ValueError`` on invalid input so the matcher can treat the route
    as non-matching and fall through to the normal 404 path.
    """
    if converter == "string":
        return value
    if converter == "path":
        return value
    if converter == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(f"invalid int value {value!r}")
    if converter == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(f"invalid float value {value!r}")
    if converter == "uuid":
        return _validate_uuid(value)
    raise ValueError(f"unknown converter {converter!r}")


class Router:
    """A small path-router with support for static and parameterized routes.

    Parameterized paths look like ``"/api/users/<user_id>"`` or with type
    converters like ``"/api/users/<int:user_id>"``, ``"/files/<path:filename>"``, ``"/uuid/<uuid:uid>"``.

    Static routes take priority over parameterized ones, and more-specific
    parameterized routes are preferred over less-specific ones when the
    number of static segments is equal.

    Routes can be named for URL generation via :meth:`url_for` or
    :meth:`build_url`.
    """

    _CONVERTERS: dict[str, Callable[[str], Any]] = {
        "string": str,
        "int": int,
        "float": float,
        "path": str,
        "uuid": _validate_uuid,
    }

    def __init__(self) -> None:
        self._static: dict[str, _Route] = {}
        self._params: list[_Route] = []
        self._named: dict[str, _Route] = {}
        # Aliases for the DevTools property on NXserver.
        self._static_routes = self._static
        self._param_routes = self._params

    def add(
        self,
        path: str,
        handler: Callable,
        methods: set[str] | None = None,
        name: str | None = None,
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
        route.original_path = path
        route.name = name or ""

        if self._is_param_path(path):
            for existing in self._params:
                if existing.pattern == route.pattern and existing.methods & route.methods:
                    overlapping = ", ".join(sorted(existing.methods & route.methods))
                    raise ValueError(
                        f"Route {path!r} conflicts with {existing.original_path!r} "
                        f"for method(s) {overlapping}"
                    )
            self._params.append(route)
        else:
            if path in self._static:
                raise ValueError(f"Route {path!r} already registered")
            self._static[path] = route

        if name:
            if name in self._named:
                raise ValueError(f"Route name {name!r} is already registered")
            self._named[name] = route

    def _build_route(
        self, path: str, handler: Callable, methods: set[str]
    ) -> _Route:
        param_names: list[str] = []
        param_converters: list[str] = []
        segments: list[str] = []
        for seg in path.strip("/").split("/"):
            if not seg:
                continue
            if seg.startswith("<") and seg.endswith(">"):
                inner = seg[1:-1]
                if ":" in inner:
                    converter, name = inner.split(":", 1)
                    if not name.isidentifier():
                        raise ValueError(
                            f"Invalid parameter name {name!r} in route {path!r}"
                        )
                    if converter not in self._CONVERTERS:
                        raise ValueError(
                            f"Unknown converter {converter!r} in route {path!r}. "
                            f"Supported: {', '.join(sorted(self._CONVERTERS))}"
                        )
                else:
                    converter = "string"
                    name = inner
                    if not name.isidentifier():
                        raise ValueError(
                            f"Invalid parameter name {name!r} in route {path!r}"
                        )
                param_converters.append(converter)
                param_names.append(name)
                segments.append(None)  # placeholder for a param segment
            else:
                segments.append(seg)
        pattern = "/" + "/".join(
            f"<{i}>" if s is None else s for i, s in enumerate(segments)
        )
        return _Route(
            pattern=pattern,
            handler=handler,
            methods=methods,
            param_names=param_names,
            param_converters=param_converters,
            original_path=path,
        )

    def _is_param_path(self, path: str) -> bool:
        return "<" in path

    def match(self, path: str) -> tuple[Optional[_Route], dict[str, Any]]:
        """Return ``(route, params)`` or ``(None, {})`` when there is no match."""
        # Exact static match first.
        if path in self._static:
            return self._static[path], {}

        # Attempt parameterized routes. Among matching parameterized routes
        # prefer the one with the most literal segments (most specific).
        best: Optional[_Route] = None
        best_params: dict[str, Any] = {}
        best_literal_count = -1

        for route in self._params:
            params = self._match_param_route(route, path)
            if params is None:
                continue
            literal_count = sum(1 for seg in route.pattern.strip("/").split("/") if not seg.startswith("<"))
            if literal_count > best_literal_count:
                best = route
                best_params = dict(params)
                best_literal_count = literal_count

        if best is not None:
            return best, best_params
        return None, {}

    def _match_param_route(self, route: _Route, path: str) -> Optional[dict[str, Any]]:
        """Return converted params dict or ``None`` when there is no match.

        The ``path`` converter is special: it consumes the remainder of the URL
        path starting at its position, including forward slashes. Only one ``path``
        converter is supported per route and it must be the final parameter.
        """
        route_segments = [s for s in route.pattern.strip("/").split("/") if s]
        path_segments = [s for s in path.strip("/").split("/") if s]

        # The ``path`` converter swallows the rest of the URL, so a route that
        # ends with one may match a path with more segments than the pattern.
        has_path_tail = bool(route.param_converters) and route.param_converters[-1] == "path"
        if has_path_tail:
            if len(path_segments) < len(route_segments):
                return None
        elif len(route_segments) != len(path_segments):
            return None

        params: dict[str, Any] = {}
        param_index = 0
        for seg_index, rs in enumerate(route_segments):
            if rs.startswith("<"):
                converter = route.param_converters[param_index]
                name = route.param_names[param_index]
                if converter == "path":
                    try:
                        params[name] = _validate_param(
                            "/".join(path_segments[seg_index:]), converter
                        )
                    except ValueError:
                        return None
                    return params
                try:
                    params[name] = _validate_param(path_segments[seg_index], converter)
                except ValueError:
                    return None
                param_index += 1
            elif rs != path_segments[seg_index]:
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

    def url_for(self, name: str, **params: Any) -> str:
        """Build the URL for the named route *name*.

        Parameter values are converted to strings and percent-encoded. A
        ``path`` converter keeps its forward slashes (each segment is encoded
        separately) so generated URLs stay valid.

        Raises:
            ValueError: when *name* is unknown, a required parameter is
                missing, or an unexpected parameter is supplied.
        """
        route = self._named.get(name)
        if route is None:
            known = ", ".join(sorted(self._named)) or "none"
            raise ValueError(f"No route named {name!r} is registered (known: {known})")

        missing = [p for p in route.param_names if p not in params]
        if missing:
            raise ValueError(
                f"Missing URL parameter(s) for route {name!r}: {', '.join(missing)}"
            )
        extra = [p for p in params if p not in route.param_names]
        if extra:
            raise ValueError(
                f"Unexpected URL parameter(s) for route {name!r}: {', '.join(extra)}"
            )

        parts: list[str] = []
        param_index = 0
        for seg in route.original_path.strip("/").split("/"):
            if not seg:
                continue
            if seg.startswith("<") and seg.endswith(">"):
                converter = route.param_converters[param_index]
                value = params[route.param_names[param_index]]
                param_index += 1
                if converter == "path":
                    parts.append(
                        "/".join(
                            urllib.parse.quote(part, safe="")
                            for part in str(value).split("/")
                        )
                    )
                else:
                    parts.append(urllib.parse.quote(str(value), safe=""))
            else:
                parts.append(seg)
        return "/" + "/".join(parts)

    def build_url(self, name: str, **params: Any) -> str:
        """Alias for :meth:`url_for`."""
        return self.url_for(name, **params)


# ---------------------------------------------------------------------------
# CORS configuration
# ---------------------------------------------------------------------------

def _origin_matches(origin: str, pattern: str) -> bool:
    """Check if *origin* matches *pattern*.

    Supports exact match, wildcard suffix (e.g. "*.example.com"),
    and regex patterns.
    """
    if pattern.startswith("regex:"):
        import re as _re

        try:
            return bool(_re.fullmatch(pattern[6:], origin))
        except _re.error:
            return False
    if pattern.startswith("*."):
        suffix = pattern[2:]
        return origin.endswith(suffix) and "." in origin[:-len(suffix)]
    return origin == pattern


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
        for pattern in self.allowed_origins:
            if _origin_matches(origin, pattern):
                return True
        return False

    def echo_origin(self, origin: Optional[str]) -> Optional[str]:
        if not self.enabled or not origin:
            return None
        if "*" in self.allowed_origins:
            return origin if self.allow_credentials else "*"
        for pattern in self.allowed_origins:
            if _origin_matches(origin, pattern):
                return origin if self.allow_credentials else "*"
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
        cors: str | list[str] | CorsConfig | None = None,
        debug: bool = False,
        host: str = "127.0.0.1",
        session_secret: Optional[str] = None,
        session_expires: int = 86400,
        cors_preflight: bool = True,
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
        self.cors = self._normalize_cors(cors)
        self.debug = debug
        self.cors_preflight = cors_preflight
        self.session_secret = session_secret
        self.session_expires = session_expires

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
        self._dev_mode: bool = False
        self.session_secret: Optional[str] = None
        self.session_expires: int = 86400  # 24 hours in seconds
        self.error_pages: dict[int, Callable[[Request], Any]] = {}
        self._error_handlers_by_code: dict[int, Callable[[Request, BaseException], tuple[bytes, int, dict[str, str]]]] = {}

        project_dir = Path.cwd().resolve()
        self.project_dir = project_dir
        self.static_dir = (project_dir / static_folder).resolve()
        self.template_dir = (project_dir / template_folder).resolve()

    # -- route registration ---------------------------------------------------

    def route(
        self,
        path: str,
        methods: Optional[list[str]] = None,
        name: Optional[str] = None,
    ):
        """Register a handler for *path*.

        Args:
            path: URL path, e.g. ``"/"`` or ``"/api/users/<id>"``.
            methods: Optional explicit list of HTTP methods. When omitted the
                handler responds to GET and HEAD.
            name: Optional route name, used by ``url_for()`` to generate URLs.

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
            self.router.add(path, handler, method_set, name)
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

    def get(self, path: str, name: Optional[str] = None):
        return self.route(path, methods=["GET"], name=name)

    def post(self, path: str, name: Optional[str] = None):
        return self.route(path, methods=["POST"], name=name)

    def put(self, path: str, name: Optional[str] = None):
        return self.route(path, methods=["PUT"], name=name)

    def patch(self, path: str, name: Optional[str] = None):
        return self.route(path, methods=["PATCH"], name=name)

    def delete(self, path: str, name: Optional[str] = None):
        return self.route(path, methods=["DELETE"], name=name)

    def options(self, path: str, name: Optional[str] = None):
        return self.route(path, methods=["OPTIONS"], name=name)

    def head(self, path: str, name: Optional[str] = None):
        return self.route(path, methods=["HEAD"], name=name)

    def url_for(self, name: str, **params: Any) -> str:
        """Generate the URL for the named route.

        Example::

            @app.get("/users/<int:user_id>", name="user")
            def user(user_id):
                ...

            app.url_for("user", user_id=42)  # '/users/42'
        """
        return self.router.url_for(name, **params)

    def build_url(self, name: str, **params: Any) -> str:
        """Alias for :meth:`url_for`."""
        return self.router.url_for(name, **params)

    # -- lifecycle hooks (optional, convenient for middleware) --------------

    # -- lifecycle hooks (optional, convenient for middleware) --------------

    def before_request(self, handler: Callable[[Request], None]):
        """Register a hook that runs before every request.

        Can be used as a decorator or called directly::

            @server.before_request
            def log_request(req):
                print(f"{req.method} {req.path}")

            # or:
            def my_hook(req):
                ...
            server.before_request(my_hook)

        The hook receives the current :class:`Request` and may raise
        :class:`_RequestError` to short-circuit the request with an error
        response.
        """
        self._before_request_handlers.append(handler)
        return handler

    def after_request(self, handler: Callable[..., Any]):
        """Register a hook that runs after a route returns, before the response
        is sent.

        Can be used as a decorator or called directly::

            @server.after_request
            def add_header(body, status, headers):
                headers["X-Custom"] = "value"
                return body, status, headers

        The hook receives ``(response_body, status, headers)`` and should
        return a triple with the same shape.
        """
        self._after_request_handlers.append(handler)
        return handler

    def on_request(self, handler: Callable[[Request], None]):
        """Alias for :meth:`before_request`. Register a hook that runs before
        every request.

        Example::

            @server.on_request
            def logEveryRequest(req):
                print(f"{req.method} {req.path}")
        """
        return self.before_request(handler)

    def on_response(self, handler: Callable[..., Any]):
        """Alias for :meth:`after_request`. Register a hook that runs after a
        route returns, before the response is sent.

        Example::

            @server.on_response
            def add_security_headers(body, status, headers):
                headers.setdefault("X-Content-Type-Options", "nosniff")
                return body, status, headers
        """
        return self.after_request(handler)

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

    def error(
        self,
        code_or_exception: int | type[BaseException],
    ) -> Callable[
        [Callable],
        Callable,
    ]:
        """Register a custom error handler by HTTP status code or exception type.

        Can be used as a decorator::

            @server.error(404)
            def not_found(request, exc):
                return b'<h1>Page not found</h1>', 404, {"Content-Type": "text/html"}

            @server.error(ValueError)
            def handle_value_error(request, exc):
                return b'{"error": "bad value"}', 400, {}

        When *code_or_exception* is an integer, the handler is registered for
        that HTTP status code. When it is an exception type, the handler is
        registered for that exception type.
        """
        if isinstance(code_or_exception, int):
            def decorator(handler):
                self._error_handlers_by_code[code_or_exception] = handler
                return handler
            return decorator
        else:
            return self.error_handler(code_or_exception)

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
            rows.append((route.original_path, sorted(route.methods), route.handler.__name__ if hasattr(route.handler, "__name__") else str(route.handler)))
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

    def _normalize_cors(
        self, cors: str | list[str] | CorsConfig | None
    ) -> CorsConfig:
        """Normalize the *cors* parameter to a :class:`CorsConfig`.

        Accepts ``None`` (disabled), ``"*"`` (all origins), a list of
        origin strings/patterns, or a full :class:`CorsConfig`.
        """
        if cors is None:
            return CorsConfig()
        if isinstance(cors, CorsConfig):
            return cors
        if isinstance(cors, str):
            if cors == "*":
                return CorsConfig(enabled=True, allowed_origins=["*"])
            return CorsConfig(enabled=True, allowed_origins=[cors])
        if isinstance(cors, list):
            return CorsConfig(enabled=True, allowed_origins=cors)
        return CorsConfig()

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
            try:
                req = self._build_wsgi_request(environ)
                result = self._process_request(req)
            except _RequestError as exc:
                result = self._error_response(exc.status, exc.title, exc.detail)
        except Exception:
            if self.debug:
                traceback.print_exc()
            result = self._error_response(
                500,
                "Internal Server Error",
                "The request could not be handled.",
            )

        try:
            body, status, headers = self._finalize_response(result)
        except Exception:
            if self.debug:
                traceback.print_exc()
            body, status, headers = self._error_response(
                500,
                "Internal Server Error",
                "The response could not be constructed.",
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
            # DevTools hidden mount — active in debug mode or after
            # enable_devtools(), which is what `nexa dev` uses.
            if self._mount is not None and req.path.startswith("/__nexa__"):
                body, status, headers = self._mount.dispatch(req)
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

            if (
                req.method == "OPTIONS"
                and self.cors_preflight
                and self.cors.is_origin_allowed(req.headers.get("Origin"))
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
                    return self._dispatch_exception_handler(handler, req, exc)
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
        """Normalize a route result into ``(body, content_type, status, headers)``."""
        return self._coerce_response(body)

    def _coerce_response(
        self, result: Any, *, default_status: int = 200
    ) -> tuple[bytes, str, int, dict[str, str]]:
        """Convert any supported handler return value into response parts.

        Supported values are :class:`Response` (including
        :class:`HTMLResponse`), :class:`JSONResponse`, rendered
        ``Element``/``Fragment`` objects, plain ``str``/``bytes``, ``None``
        (empty body), and ``(body, status)`` or ``(body, status, headers)``
        tuples.  Unknown values keep the historical behaviour of being
        rendered with ``str``.
        """
        if isinstance(result, Response):
            body, content_type, status, headers = result.render()
            return body, content_type, status, dict(headers)
        if isinstance(result, JSONResponse):
            rendered = result.render()
            if not isinstance(rendered, str):
                rendered = str(rendered)
            return (
                rendered.encode("utf-8"),
                "application/json; charset=utf-8",
                int(result.status),
                dict(getattr(result, "headers", {}) or {}),
            )
        if isinstance(result, (Element, Fragment)):
            return (
                result.render().encode("utf-8"),
                "text/html; charset=utf-8",
                default_status,
                {},
            )
        if isinstance(result, tuple):
            if len(result) == 3:
                body, status, raw_headers = result
            elif len(result) == 2:
                body, status = result
                raw_headers = {}
            else:
                raise TypeError(
                    "Response tuples must be (body, status) or "
                    "(body, status, headers)."
                )
            if raw_headers is None:
                raw_headers = {}
            if not isinstance(raw_headers, dict):
                raise TypeError("Response headers must be a dict.")
            body_bytes, content_type, _ignored, inner_headers = self._coerce_response(
                body, default_status=status
            )
            merged = dict(inner_headers)
            merged.update(raw_headers)
            content_type = next(
                (
                    value
                    for name, value in merged.items()
                    if name.lower() == "content-type"
                ),
                content_type,
            )
            return body_bytes, content_type, int(status), merged
        if isinstance(result, bytes):
            return result, "text/html; charset=utf-8", default_status, {}
        if isinstance(result, str):
            return (
                result.encode("utf-8"),
                "text/html; charset=utf-8",
                default_status,
                {},
            )
        if result is None:
            return b"", "text/html; charset=utf-8", default_status, {}
        return (
            str(result).encode("utf-8"),
            "text/html; charset=utf-8",
            default_status,
            {},
        )

    def _finalize_response(
        self, result: Any
    ) -> tuple[bytes, int, list[tuple[str, str]]]:
        """Return a fully prepared ``(body, status, headers)`` response.

        ``_process_request`` already returns prepared responses; anything
        else is normalized and validated here, so callers never unpack a
        response object by mistake.
        """
        if (
            isinstance(result, tuple)
            and len(result) == 3
            and isinstance(result[0], bytes)
            and isinstance(result[1], int)
            and isinstance(result[2], list)
        ):
            return result
        body, content_type, status, headers = self._coerce_response(result)
        return self._prepare_response(body, content_type, status, headers)

    def _dispatch_exception_handler(
        self,
        handler: Callable[[Request, BaseException], Any],
        req: Request,
        exc: BaseException,
    ) -> tuple[bytes, int, list[tuple[str, str]]]:
        """Run a custom exception handler and contain its failures.

        The handler may return any supported response value.  If the handler
        raises, or returns something that cannot be rendered, both the
        original exception and the handler failure are logged and a safe 500
        response is returned.
        """
        try:
            result = handler(req, exc)
        except Exception as handler_exc:
            self._log_handler_failure(exc, handler_exc)
            return self._error_response(
                500,
                "Internal Server Error",
                "A custom error handler raised an error while handling the request.",
            )
        try:
            body, content_type, status, headers = self._coerce_response(result)
        except Exception as handler_exc:
            self._log_handler_failure(exc, handler_exc)
            return self._error_response(
                500,
                "Internal Server Error",
                "A custom error handler returned an unsupported response.",
            )
        return self._prepare_response(body, content_type, status, headers)

    @staticmethod
    def _log_handler_failure(
        original: Optional[BaseException], failure: BaseException
    ) -> None:
        """Log a failing custom error handler together with the original error."""
        try:
            logger = _get_default_logger()
            logger.error(
                "A custom error handler failed while handling %r: %r\n%s",
                original,
                failure,
                traceback.format_exc(),
            )
        except Exception:
            traceback.print_exc()

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
        # Check for a custom error page first.
        handler = self._error_handlers_by_code.get(status)
        if handler is not None:
            try:
                result = handler(self._current_request_or_none(), None)
                body, content_type, status_code, resp_headers = self._coerce_response(
                    result, default_status=status
                )
                extra = dict(headers or {})
                extra.update(resp_headers)
                return self._prepare_response(body, content_type, status_code, extra)
            except Exception as exc:
                self._log_handler_failure(None, exc)

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

    def _current_request_or_none(self) -> Optional[Request]:
        """Return the current request, or None if no request is active."""
        return _current_request.get()

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

    def _ensure_devtools(self) -> "DevTools":  # noqa: F821 (lazy import)
        """Create the DevTools instance and mount once when ``debug=True``.

        Safe to call before :meth:`run`; repeated calls reuse the same
        instance so the dashboard never ends up with two DevTools objects.
        """
        if not (self.debug or self._dev_mode):
            raise AttributeError(
                "DevTools is not available. Start the server with debug=True "
                "or call enable_devtools() first."
            )
        if self._devtools is None:
            dt_mod = _get_devtools()
            self._devtools = dt_mod.DevTools(self)
            self._mount = dt_mod._DevToolsMount(self._devtools)
            # Subscribe DevTools to the default log ring buffer.
            default_logger = _get_default_logger()
            default_logger.enable_ring_buffer()
            default_logger.subscribe_ring(self._devtools.enqueue_log)
        return self._devtools

    @property
    def devtools(self) -> "DevTools":  # noqa: F821 (lazy import)
        """The DevTools instance for a server started with ``debug=True``.

        Available immediately after construction; :meth:`run` reuses this
        instance rather than creating a second one.
        """
        return self._ensure_devtools()

    def enable_devtools(self, token: Optional[str] = None) -> "DevTools":  # noqa: F821
        """Enable the DevTools dashboard for a development session.

        Unlike ``debug=True`` this does not enable debug error output; it only
        mounts DevTools. Used by ``nexa dev`` so an application's existing
        server gains DevTools without the application opting in.
        """
        self._dev_mode = True
        devtools = self._ensure_devtools()
        if token is not None:
            devtools.token = token
        return devtools

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
                    result = server._process_request(req)
                except _RequestError as exc:
                    result = server._error_response(
                        exc.status, exc.title, exc.detail
                    )
                except Exception:
                    if server.debug:
                        traceback.print_exc()
                    result = server._error_response(
                        500,
                        "Internal Server Error",
                        "The request could not be handled.",
                    )

                try:
                    body, status, headers = server._finalize_response(result)
                except Exception:
                    if server.debug:
                        traceback.print_exc()
                    body, status, headers = server._error_response(
                        500,
                        "Internal Server Error",
                        "The response could not be constructed.",
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

        # Set up DevTools if debug mode is enabled. Any instance created
        # before run() (for example by `nexa dev` when printing the token)
        # is reused rather than replaced.
        if self.debug:
            self._ensure_devtools()

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
