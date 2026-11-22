"""Tests for Nexa.asgi module."""

import asyncio
from types import SimpleNamespace

import pytest

import Nexa

from Nexa.asgi import ASGIAdaptor, ASGIError


class TestASGIError:
    """ASGIError is raised for unsupported scopes."""

    def test_unsupported_scope_raises(self):
        adaptor = ASGIAdaptor(lambda scope, receive, send: None)

        async def run():
            scope = {"type": "websocket"}

            async def receive():
                return {"type": "websocket.connect"}

            async def send(event):
                pass

            with pytest.raises(ASGIError, match="Unsupported ASGI scope"):
                await adaptor(scope, receive, send)

        asyncio.run(run())

    def test_unsupported_http2_scope_raises(self):
        adaptor = ASGIAdaptor(lambda scope, receive, send: None)

        async def run():
            scope = {"type": "http2"}

            async def receive():
                return {"type": "http2.request"}

            async def send(event):
                pass

            with pytest.raises(ASGIError, match="Unsupported ASGI scope"):
                await adaptor(scope, receive, send)

        asyncio.run(run())


class TestASGIAsyncAppIntegration:
    """ASGIAdaptor works as an ASGI 3 app with an async handler."""

    def test_http_scope_with_async_handler(self):
        async def async_handler(request):
            return 200, [("content-type", "text/plain")], "async ok"

        adaptor = ASGIAdaptor(async_handler)

        async def run():
            scope = {
                "type": "http",
                "method": "GET",
                "path": "/async",
                "query_string": b"",
                "headers": [],
                "root_path": "",
            }
            sent: list = []
            receive_call_count = [0]

            async def receive():
                receive_call_count[0] += 1
                if receive_call_count[0] == 1:
                    return {"type": "http.request", "body": b"", "more_body": False}
                return {"type": "http.disconnect"}

            async def send(event):
                sent.append(event)

            await adaptor(scope, receive, send)

            # Should have sent a response start and body.
            assert any(e.get("type") == "http.response.start" for e in sent)
            assert any(e.get("type") == "http.response.body" for e in sent)
            body_event = next(e for e in sent if e.get("type") == "http.response.body")
            assert b"async ok" in body_event.get("body", b"")
            assert body_event.get("more_body") is False

        asyncio.run(run())


class TestASGIHttpScope:
    """HTTP scope handling."""

    def test_http_get_sends_response(self):
        def hello_handler(request):
            return 200, [("content-type", "text/plain")], "hello world"

        adaptor = ASGIAdaptor(hello_handler)

        async def run():
            scope = {
                "type": "http",
                "method": "GET",
                "path": "/hello",
                "query_string": b"",
                "headers": [],
                "root_path": "",
            }
            sent: list = []
            receive_call_count = [0]

            async def receive():
                receive_call_count[0] += 1
                if receive_call_count[0] == 1:
                    return {"type": "http.request", "body": b"", "more_body": False}
                return {"type": "http.disconnect"}

            async def send(event):
                sent.append(event)

            await adaptor(scope, receive, send)
            assert any(e.get("type") == "http.response.start" for e in sent)
            body_events = [e for e in sent if e.get("type") == "http.response.body"]
            assert body_events
            assert b"hello world" in body_events[-1].get("body", b"")
            assert body_events[-1].get("more_body") is False

        asyncio.run(run())


class TestASGIBodyStreaming:
    """Body streaming for larger requests."""

    def test_body_streaming_with_receive(self):
        def echo_handler(request):
            return 200, [("content-type", "text/plain")], "echoed"

        adaptor = ASGIAdaptor(echo_handler)

        async def run():
            scope = {
                "type": "http",
                "method": "POST",
                "path": "/echo",
                "query_string": b"",
                "headers": [],
                "root_path": "",
            }
            sent: list = []

            receive_calls = [
                {"type": "http.request", "body": b"chunk1", "more_body": True},
                {"type": "http.request", "body": b"chunk2", "more_body": False},
                {"type": "http.disconnect"},
            ]
            receive_iter = iter(receive_calls)

            async def receive():
                return next(receive_iter)

            async def send(event):
                sent.append(event)

            await adaptor(scope, receive, send)
            assert any(e.get("type") == "http.response.start" for e in sent)
            body_events = [e for e in sent if e.get("type") == "http.response.body"]
            assert body_events
            assert b"echoed" in body_events[-1].get("body", b"")

        asyncio.run(run())

    def test_single_chunk_body(self):
        def single_handler(request):
            return 200, [("content-type", "text/plain")], "got it"

        adaptor = ASGIAdaptor(single_handler)

        async def run():
            scope = {
                "type": "http",
                "method": "POST",
                "path": "/single",
                "query_string": b"",
                "headers": [],
                "root_path": "",
            }
            sent: list = []
            call_count = [0]

            async def receive():
                call_count[0] += 1
                if call_count[0] == 1:
                    return {"type": "http.request", "body": b"payload", "more_body": False}
                raise ConnectionResetError("disconnect")

            async def send(event):
                sent.append(event)

            await adaptor(scope, receive, send)
            body_events = [e for e in sent if e.get("type") == "http.response.body"]
            assert body_events
            assert b"got it" in body_events[-1].get("body", b"")

        asyncio.run(run())


class TestASGILifespan:
    """Lifespan events."""

    def test_lifespan_startup_sends_complete(self):
        async def noop_handler(scope, receive, send):
            pass

        adaptor = ASGIAdaptor(noop_handler)

        async def run():
            scope = {"type": "lifespan", "asgi": {"version": "3.0"}}
            sent: list = []

            async def receive():
                return {"type": "lifespan.startup"}

            async def send(event):
                sent.append(event)

            await adaptor(scope, receive, send)
            assert sent == [{"type": "lifespan.startup.complete"}]

        asyncio.run(run())

    def test_lifespan_shutdown_sends_complete(self):
        async def noop_handler(scope, receive, send):
            pass

        adaptor = ASGIAdaptor(noop_handler)

        async def run():
            scope = {"type": "lifespan", "asgi": {"version": "3.0"}}
            sent: list = []

            async def receive():
                return {"type": "lifespan.shutdown"}

            async def send(event):
                sent.append(event)

            await adaptor(scope, receive, send)
            assert sent == [{"type": "lifespan.shutdown.complete"}]

        asyncio.run(run())


class TestASGIDisconnect:
    """Disconnect propagation."""

    def test_disconnect_after_response_is_ignored(self):
        """After the response is sent, a client disconnect should not crash."""
        nexa = Nexa.NXserver("Disconnect Test")

        @nexa.get("/hello")
        def hello():
            return "hello"

        adaptor = ASGIAdaptor(nexa)

        async def run():
            scope = {
                "type": "http",
                "method": "GET",
                "path": "/hello",
                "query_string": b"",
                "headers": [],
                "root_path": "",
            }
            sent: list = []

            async def receive():
                # First message is the request body (empty).
                # Then simulate a disconnect.
                receive.receive_count = getattr(receive, "receive_count", 0) + 1
                if receive.receive_count == 1:
                    return {"type": "http.request", "body": b"", "more_body": False}
                return {"type": "http.disconnect"}

            async def send(event):
                sent.append(event)

            await adaptor(scope, receive, send)
            # Response should have been sent.
            assert any(e.get("type") == "http.response.start" for e in sent)
            assert any(e.get("type") == "http.response.body" for e in sent)
            # Disconnect should have been received and ignored.
            body_events = [e for e in sent if e.get("type") == "http.response.body"]
            assert body_events
            assert body_events[-1].get("more_body") is False

        asyncio.run(run())
