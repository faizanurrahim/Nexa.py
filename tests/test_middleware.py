"""Tests for Nexa.middleware module."""

import asyncio

import pytest

from Nexa.middleware import Middleware, wrap_handler


def handler(request):
    return 200, {"content-type": "text/plain"}, f"ok-{request.get('path', '')}"


class TestMiddlewareBasics:
    """Basic middleware composition."""

    def test_no_middleware_returns_handler(self):
        mware = Middleware()
        composed = mware.compose(handler)
        status, headers, body = composed({"path": "/"})
        assert status == 200
        assert body == "ok-/"

    def test_single_middleware_runs(self):
        mware = Middleware()

        def one(request, call_next):
            return 201, {}, "from_one"

        mware.add(one, priority=10)
        composed = mware.compose(handler)
        status, headers, body = composed({"path": "/"})
        assert status == 201
        assert body == "from_one"

    def test_middleware_can_call_next(self):
        mware = Middleware()

        def modify(request, call_next):
            status, headers, body = call_next(request)
            return status, headers, body + "-modified"

        mware.add(modify, priority=10)
        composed = mware.compose(handler)
        status, headers, body = composed({"path": "/test"})
        assert body == "ok-/test-modified"

    def test_middleware_order_is_deterministic(self):
        mware = Middleware()
        order_log = []

        def third(request, call_next):
            order_log.append("third-before")
            result = call_next(request)
            order_log.append("third-after")
            return result

        def first(request, call_next):
            order_log.append("first-before")
            result = call_next(request)
            order_log.append("first-after")
            return result

        def second(request, call_next):
            order_log.append("second-before")
            result = call_next(request)
            order_log.append("second-after")
            return result

        mware.add(first, priority=10)
        mware.add(second, priority=20)
        mware.add(third, priority=30)
        composed = mware.compose(handler)
        composed({"path": "/"})
        assert order_log == [
            "first-before", "second-before", "third-before",
            "third-after", "second-after", "first-after",
        ]


class TestMiddlewareAsync:
    """Async middleware support."""

    def test_async_middleware_works(self):
        mware = Middleware()

        async def async_middleware(request, call_next):
            result = await call_next(request)
            return result

        mware.add(async_middleware, priority=10)
        composed = mware.compose(handler)
        result = asyncio.run(composed({"path": "/"}))
        status, headers, body = result
        assert status == 200

    def test_mixed_sync_async_order(self):
        mware = Middleware()
        log = []

        def sync_pre(request, call_next):
            log.append("sync_pre")
            return call_next(request)

        async def async_mid(request, call_next):
            log.append("async_mid")
            return await call_next(request)

        def sync_post(request, call_next):
            log.append("sync_post")
            return call_next(request)

        mware.add(sync_pre, priority=10)
        mware.add(async_mid, priority=20)
        mware.add(sync_post, priority=30)
        composed = mware.compose(handler)
        asyncio.run(composed({"path": "/"}))
        assert log == ["sync_pre", "async_mid", "sync_post"]


class TestMiddlewareExceptionHandling:
    """Exception propagation through middleware."""

    def test_exception_from_handler_propagates(self):
        mware = Middleware()

        def fail_handler(request):
            raise ValueError("boom")

        mware.add(lambda req, call_next: call_next(req), priority=10)
        composed = mware.compose(fail_handler)
        with pytest.raises(ValueError, match="boom"):
            composed({})

    def test_middleware_catches_exception(self):
        mware = Middleware()

        def error_handler(request):
            raise RuntimeError("fail")

        def catch(request, call_next):
            try:
                return call_next(request)
            except RuntimeError:
                return 500, {}, "caught"

        mware.add(catch, priority=10)
        composed = mware.compose(error_handler)
        status, headers, body = composed({})
        assert status == 500
        assert body == "caught"


class TestMiddlewareRegister:
    """Global @Middleware.register decorator."""

    def test_register_decorator(self):
        @Middleware.register(priority=5, name="test_middleware")
        def test_mw(request, call_next):
            return 202, {}, "registered"

        mware = Middleware()
        composed = mware.compose(handler)
        status, headers, body = composed({})
        assert status == 202
        assert body == "registered"

        # Cleanup.
        Middleware.clear_all()

    def test_register_decorator_async(self):
        @Middleware.register(priority=5, name="test_async_middleware")
        async def test_mw(request, call_next):
            result = await call_next(request)
            return result

        mware = Middleware()
        composed = mware.compose(handler)
        result = asyncio.run(composed({}))
        assert result == (200, {"content-type": "text/plain"}, "ok-")

        # Cleanup.
        Middleware.clear_all()


class TestWrapHandler:
    """Convenience wrap_handler function."""

    def test_wrap_handler_with_list(self):
        def add_header(request, call_next):
            status, headers, body = call_next(request)
            headers["x-added"] = "yes"
            return status, headers, body

        composed = wrap_handler(handler, middlewares=[add_header])
        status, headers, body = composed({})
        assert headers["x-added"] == "yes"
        assert body == "ok-"

    def test_wrap_handler_none_returns_handler(self):
        composed = wrap_handler(handler, middlewares=None)
        assert composed is handler
