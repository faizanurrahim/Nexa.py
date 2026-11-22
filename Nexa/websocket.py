"""WebSocket support for Nexa.py.

Provides a minimal WebSocket implementation built on stdlib ``http.server``.
WebSocket routes are registered with :meth:`NXserver.ws` and upgrade the HTTP
connection when the client sends a proper WebSocket handshake.

Usage::

    from Nexa import NXserver

    server = NXserver("ws-demo", port=3000)

    async def echo(ws):
        async for message in ws:
            await ws.send_text(f"echo: {message}")

    server.ws("/chat")(echo)
    server.run()
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import struct
from typing import Any, AsyncIterator, Callable

from .nxserver import NXserver

# WebSocket frame opcodes.
OPCODE_CONTINUATION = 0
OPCODE_TEXT = 1
OPCODE_BINARY = 2
OPCODE_CLOSE = 8
OPCODE_PING = 9
OPCODE_PONG = 10

_SENTINEL_CLOSE = object()


def _frame(opcode: int, payload: bytes) -> bytes:
    """Build a WebSocket frame (server-to-client; no masking required)."""
    buf = bytearray()
    buf.append(0x80 | opcode)  # FIN + opcode
    length = len(payload)
    if length < 126:
        buf.append(length)
    elif length < 65536:
        buf.append(126)
        buf.extend(struct.pack(">H", length))
    else:
        buf.append(127)
        buf.extend(struct.pack(">Q", length))
    buf.extend(payload)
    return bytes(buf)


def _compute_accept_key(client_key: str) -> str:
    """Compute the Sec-WebSocket-Accept value for a given client key."""
    GUID = "258EAFA5-E914-47DA-95CA-5AB9FC6DF2D5"
    combined = (client_key + GUID).encode("utf-8")
    digest = hashlib.sha1(combined).digest()
    return base64.b64encode(digest).decode("ascii")


class WebSocket:
    """A WebSocket connection handed to a ``ws`` handler.

    Provides ``async for message in ws`` to iterate over incoming messages,
    plus ``send_text``, ``send_bytes``, and ``close``.
    """

    def __init__(self, server: "WebSocketServer", request_handler: Any) -> None:
        self._server = server
        self._request_handler = request_handler
        self._closed = False
        self.path = request_handler.path
        self.query_string = getattr(request_handler, "query_string", "")
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._receive_task: asyncio.Task | None = None

    async def _start_receive(self) -> None:
        """Start the background receive loop that feeds the message queue."""
        self._receive_task = asyncio.create_task(
            _receive_and_dispatch(self._server, self._request_handler, self)
        )

    async def send_text(self, data: str) -> None:
        """Send a text frame to the peer."""
        if self._closed:
            return
        frame = _frame(OPCODE_TEXT, data.encode("utf-8"))
        await self._server._write(self._request_handler, frame)

    async def send_bytes(self, data: bytes) -> None:
        """Send a binary frame to the peer."""
        if self._closed:
            return
        frame = _frame(OPCODE_BINARY, data)
        await self._server._write(self._request_handler, frame)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        """Close the connection with an optional status code and reason."""
        if self._closed:
            return
        self._closed = True
        payload = struct.pack(">H", code) + reason.encode("utf-8")
        frame = _frame(OPCODE_CLOSE, payload)
        await self._server._write(self._request_handler, frame)
        if self._receive_task is not None:
            self._receive_task.cancel()

    async def __aenter__(self) -> "WebSocket":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    def __aiter__(self) -> AsyncIterator[str | bytes]:
        return self

    async def __anext__(self) -> str | bytes:
        if self._closed:
            raise StopAsyncIteration
        msg = await self._message_queue.get()
        if msg is _SENTINEL_CLOSE:
            raise StopAsyncIteration
        return msg


class WebSocketServer:
    """Manages WebSocket upgrade and frame I/O on a per-connection basis.

    Created by :meth:`NXserver.ws` when a matching route receives an upgrade
    request.  Handlers are async callables that receive a :class:`WebSocket`.
    """

    def __init__(self, server: NXserver) -> None:
        self._server = server

    async def _write(self, handler: Any, data: bytes) -> None:
        """Write raw bytes to the handler's wfile."""
        try:
            handler.wfile.write(data)
            handler.wfile.flush()
        except (ConnectionResetError, BrokenPipeError):
            pass

    async def handle(self, handler: Any, ws_handler: Callable[[WebSocket], Any]) -> None:
        """Perform the WebSocket handshake and run the handler."""
        key = handler.headers.get("Sec-WebSocket-Key")
        if not key:
            handler.send_error(400, "Missing Sec-WebSocket-Key")
            return
        accept = _compute_accept_key(key)
        handler._http_response_only(
            101,
            {
                "Upgrade": "websocket",
                "Connection": "Upgrade",
                "Sec-WebSocket-Accept": accept,
            },
        )
        try:
            handler.wfile.flush()
        except Exception:
            return

        ws = WebSocket(self, handler)
        try:
            await ws._start_receive()
            result = ws_handler(ws)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            pass
        finally:
            await ws.close()


async def _async_read(rfile: Any, n: int) -> bytes:
    """Read up to *n* bytes from *rfile*, yielding to the event loop."""
    data = bytearray()
    while len(data) < n:
        try:
            # Prefer a non-blocking read via select on the underlying socket.
            sock = None
            if hasattr(rfile, "raw") and hasattr(rfile.raw, "_sock"):
                sock = rfile.raw._sock
            if sock is not None:
                import select
                r, _, _ = select.select([sock], [], [], 0.1)
                if r:
                    chunk = rfile.read(n - len(data))
                    if not chunk:
                        break
                    data.extend(chunk)
                else:
                    await asyncio.sleep(0)
            else:
                loop = asyncio.get_event_loop()
                chunk = await loop.run_in_executor(None, rfile.read, n - len(data))
                if not chunk:
                    break
                data.extend(chunk)
        except (ConnectionResetError, BrokenPipeError):
            break
    return bytes(data)


async def _receive_and_dispatch(
    ws_server: WebSocketServer,
    handler: Any,
    ws: WebSocket,
) -> None:
    """Read frames from the connection and enqueue messages for the handler."""
    buf = b""
    try:
        while not ws._closed:
            # Read frame header (at least 2 bytes).
            while len(buf) < 2:
                chunk = await _async_read(handler.rfile, 2 - len(buf))
                if not chunk:
                    ws._message_queue.put_nowait(_SENTINEL_CLOSE)
                    return
                buf += chunk

            first = buf[0]
            opcode = first & 0x0F
            masked = (first & 0x80) != 0
            second = buf[1]
            length = second & 0x7F

            if length == 126:
                while len(buf) < 4:
                    chunk = await _async_read(handler.rfile, 4 - len(buf))
                    if not chunk:
                        ws._message_queue.put_nowait(_SENTINEL_CLOSE)
                        return
                    buf += chunk
                length = struct.unpack(">H", buf[2:4])[0]
            elif length == 127:
                while len(buf) < 10:
                    chunk = await _async_read(handler.rfile, 10 - len(buf))
                    if not chunk:
                        ws._message_queue.put_nowait(_SENTINEL_CLOSE)
                        return
                    buf += chunk
                length = struct.unpack(">Q", buf[2:10])[0]

            mask_key = None
            payload_start = 2
            if masked:
                while len(buf) < 6:
                    chunk = await _async_read(handler.rfile, 6 - len(buf))
                    if not chunk:
                        ws._message_queue.put_nowait(_SENTINEL_CLOSE)
                        return
                    buf += chunk
                mask_key = buf[2:6]
                payload_start = 6

            while len(buf) < payload_start + length:
                remaining = payload_start + length - len(buf)
                chunk = await _async_read(handler.rfile, remaining)
                if not chunk:
                    ws._message_queue.put_nowait(_SENTINEL_CLOSE)
                    return
                buf += chunk

            payload = buf[payload_start : payload_start + length]
            buf = b""

            if masked and mask_key:
                payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

            if opcode == OPCODE_CLOSE:
                await ws.close()
                ws._message_queue.put_nowait(_SENTINEL_CLOSE)
                return
            elif opcode == OPCODE_PING:
                pong_frame = _frame(OPCODE_PONG, payload)
                await ws_server._write(handler, pong_frame)
                continue
            elif opcode == OPCODE_PONG:
                continue
            elif opcode in (OPCODE_TEXT, OPCODE_BINARY):
                if opcode == OPCODE_TEXT:
                    ws._message_queue.put_nowait(payload.decode("utf-8", errors="replace"))
                else:
                    ws._message_queue.put_nowait(payload)
            else:
                return
    except (ConnectionResetError, BrokenPipeError):
        ws._message_queue.put_nowait(_SENTINEL_CLOSE)
