"""ASGI adapter for Nexa.py.

Provides a real ASGI 3 application that bridges Nexa request handlers to the
ASGI interface: HTTP scopes, request/response events, lifespan, async handler
support, streaming bodies, and disconnect propagation.

Usage::

    from Nexa import ASGIAdaptor

    app = ASGIAdaptor(my_nexa_app)
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Iterable

# ASGI types.
Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class ASGIError(Exception):
    """Raised when the ASGI adaptor encounters an unsupported or invalid state."""


class ASGIAdaptor:
    """An ASGI 3 application wrapping a Nexa-compatible handler.

    The adaptor translates ASGI HTTP requests into calls to the wrapped handler
    and translates the handler's return value back into ASGI response events.

    Supported:
        - HTTP scopes (method, path, query, headers, client, server)
        - Request body streaming
        - Response body streaming and complete bodies
        - Status codes and headers
        - Lifespan startup/shutdown (no-op for HTTP-only adapters)
        - Disconnect propagation

    Not supported (raises :exc:`ASGIError`):
        - Websocket and HTTP2 scopes
        - Multiple concurrent requests on the same connection that require
          native HTTP/2 multiplexing (the adaptor is HTTP/1.1 scoped)
    """

    def __init__(
        self,
        handler: Callable[..., Any],
        *,
        handle_async: bool = True,
    ) -> None:
        """Initialise the ASGI adaptor.

        :param handler: A callable that accepts a request-like mapping and
            returns a response tuple ``(status, headers, body_iterable)`` or
            an awaitable of the same.
        :param handle_async: When ``True``, the adaptor may await the handler
            if it returns an awaitable.
        """
        self._handler = handler
        self._handle_async = handle_async

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI application entry point."""
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            await self._handle_lifespan(scope, receive, send)
            return

        if scope_type != "http":
            raise ASGIError(f"Unsupported ASGI scope type: {scope_type!r}")

        await self._handle_http(scope, receive, send)

    # ------------------------------------------------------------------
    # Lifespan
    # ------------------------------------------------------------------

    async def _handle_lifespan(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        """Handle lifespan events (startup/shutdown)."""
        while True:
            message = await receive()
            msg_type = message.get("type")
            if msg_type == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
                return
            if msg_type == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return


    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    async def _handle_http(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Translate an ASGI HTTP request into a handler call and send the response."""
        request = self._build_request(scope)

        # Read the full body.  Streaming bodies are supported on the response
        # side; request bodies are accumulated here for simplicity and because
        # the Nexa handler interface expects a complete body.
        body = await self._read_body(receive)

        request["body"] = body

        try:
            response = await self._call_handler(request)
        except Exception as exc:
            response = self._error_response(500, "Internal Server Error", str(exc))

        status, headers, body_iter = response
        await self._send_response(send, scope, status, headers, body_iter)

        # Wait for a possible disconnect after the response is sent.
        await self._wait_for_disconnect(receive)

    def _build_request(self, scope: Scope) -> dict[str, Any]:
        """Build a request mapping from the ASGI scope."""
        headers: dict[str, str] = {}
        for raw_name, raw_value in scope.get("headers", []):
            name = raw_name.decode("latin-1")
            value = raw_value.decode("latin-1")
            if name in headers:
                existing = headers[name]
                if isinstance(existing, list):
                    existing.append(value)
                else:
                    headers[name] = [existing, value]
            else:
                headers[name] = value

        return {
            "type": "http",
            "method": scope.get("method", "GET"),
            "path": scope.get("path", "/"),
            "query_string": scope.get("query_string", b""),
            "headers": headers,
            "client": scope.get("client"),
            "server": scope.get("server"),
            "scheme": scope.get("scheme", "http"),
            "root_path": scope.get("root_path", ""),
        }

    async def _read_body(self, receive: Receive) -> bytes:
        """Read the full request body from ASGI messages."""
        chunks: list[bytes] = []
        more_body = True
        while more_body:
            message = await receive()
            if message.get("type") != "http.request":
                raise ASGIError(f"Expected http.request, got {message.get('type')!r}")
            chunk = message.get("body", b"")
            if isinstance(chunk, memoryview):
                chunk = chunk.tobytes()
            chunks.append(chunk)
            more_body = message.get("more_body", False)
        return b"".join(chunks)

    async def _call_handler(self, request: dict[str, Any]) -> tuple[int, list[tuple[str, str]], Iterable[bytes]]:
        """Call the wrapped handler and normalise its return value."""
        result = self._handler(request)

        # If the result is awaitable, await it.
        if self._is_awaitable(result):
            result = await result

        if isinstance(result, tuple) and len(result) == 3:
            status, headers, body = result
            return int(status), self._normalise_headers(headers), body

        if isinstance(result, dict):
            # Allow {"status": ..., "headers": ..., "body": ...}
            return (
                int(result.get("status", 200)),
                self._normalise_headers(result.get("headers", [])),
                result.get("body", b""),
            )

        raise ASGIError(f"Handler must return (status, headers, body) or a dict; got {type(result).__name__}")

    @staticmethod
    def _is_awaitable(value: Any) -> bool:
        """Return ``True`` if *value* is awaitable."""
        return hasattr(value, "__await__") or asyncio.iscoroutine(value) or asyncio.isfuture(value)

    @staticmethod
    def _normalise_headers(
        headers: Any,
    ) -> list[tuple[str, str]]:
        """Normalise headers into a list of (name, value) pairs."""
        if isinstance(headers, dict):
            return list(headers.items())
        if isinstance(headers, (list, tuple)):
            out: list[tuple[str, str]] = []
            for item in headers:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    out.append((str(item[0]), str(item[1])))
                else:
                    out.append((str(item), ""))
            return out
        return []

    async def _send_response(
        self,
        send: Send,
        scope: Scope,
        status: int,
        headers: list[tuple[str, str]],
        body: Any,
    ) -> None:
        """Send the response start event and body events."""
        # Encode headers.
        encoded_headers: list[tuple[bytes, bytes]] = []
        for name, value in headers:
            encoded_headers.append((name.encode("latin-1"), value.encode("latin-1")))

        await send({
            "type": "http.response.start",
            "status": status,
            "headers": encoded_headers,
        })

        await self._send_body(send, body)

    async def _send_body(self, send: Send, body: Any) -> None:
        """Send one or more body events, then the body complete event."""
        if body is None:
            await send({"type": "http.response.body", "body": b""})
            return

        if isinstance(body, (bytes, str)):
            data = body.encode("utf-8") if isinstance(body, str) else body
            await send({"type": "http.response.body", "body": data, "more_body": False})
            return

        if isinstance(body, Iterable):
            iterator = iter(body)
            more = True
            while more:
                try:
                    chunk = next(iterator)
                except StopIteration:
                    more = False
                    continue
                if chunk is None:
                    continue
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                more = True
                await send({"type": "http.response.body", "body": chunk, "more_body": more})
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return

        # Fallback: treat as a single value.
        await send({"type": "http.response.body", "body": str(body).encode("utf-8"), "more_body": False})

    async def _wait_for_disconnect(self, receive: Receive) -> None:
        """Wait for a disconnect event, then ignore it."""
        try:
            while True:
                message = await receive()
                if message.get("type") == "http.disconnect":
                    return
        except asyncio.CancelledError:
            return
        except Exception:
            return

    @staticmethod
    def _error_response(status: int, title: str, detail: str) -> tuple[int, list[tuple[str, str]], Iterable[bytes]]:
        """Build a simple error response body."""
        body = f"{title}: {detail}".encode("utf-8")
        return status, [("content-type", "text/plain; charset=utf-8")], [body]


class ASGIServer:
    """Minimal ASGI server helper that can be used to run an ASGI app.

    This is a lightweight wrapper; for production use, pair the adaptor with a
    proper ASGI server.  It is provided so that Nexa applications can expose an
    ASGI interface without requiring an external dependency.
    """

    def __init__(self, app: ASGIAdaptor, *, host: str = "127.0.0.1", port: int = 8000) -> None:
        self._app = app
        self._host = host
        self._port = port

    async def serve_forever(self) -> None:
        """Start serving (placeholder — use with a real ASGI server)."""
        raise ASGIError(
            "ASGIServer.serve_forever is a placeholder. "
            "Use the ASGIAdaptor with an ASGI server such as uvicorn or hypercorn."
        )
