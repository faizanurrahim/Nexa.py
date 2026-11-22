"""Middleware system for Nexa.py.

Provides a clean, composable middleware foundation with deterministic ordering,
sync and async support, request/response inspection and modification, and
structured exception handling.

Usage::

    from Nexa import Middleware

    @Middleware.register
    def my_middleware(request, call_next):
        # Runs before the request is handled.
        response = call_next(request)
        # Runs after the response is produced.
        return response
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# Type aliases for the middleware pipeline.
Request = dict[str, Any]
Response = tuple[int, dict[str, Any], Any]  # (status, headers, body)
Handler = Callable[[Request], Any]  # Returns a response or awaitable.
MiddlewareFunc = Callable[[Request, Handler], Any]  # Returns a response or awaitable.


class MiddlewareError(Exception):
    """Raised when middleware pipeline construction or execution fails."""


@dataclass(order=True)
class _MiddlewareEntry:
    """A single middleware entry with its priority and function."""

    priority: int
    func: MiddlewareFunc = field(compare=False)
    name: str = field(compare=False, default="")


class Middleware:
    """A composable middleware registry.

    Middleware functions are called in priority order (lowest priority first).
    Each middleware receives the request and a ``call_next`` callable that
    invokes the next middleware or the final handler.

    Middleware can be synchronous or asynchronous.  The pipeline automatically
    detects awaitable returns and awaits them.
    """

    _registry: list[_MiddlewareEntry] = []
    _instance: Optional["Middleware"] = None

    def __init__(self) -> None:
        self._stack: list[_MiddlewareEntry] = []
        self._built: bool = False

    @classmethod
    def register(
        cls,
        func: Optional[MiddlewareFunc] = None,
        *,
        priority: int = 50,
        name: Optional[str] = None,
    ) -> Callable[[MiddlewareFunc], MiddlewareFunc]:
        """Register a middleware function globally.

        :param func: The middleware function to register.
        :param priority: Lower numbers run first.  Default 50.
        :param name: Optional name for debugging.
        """
        if func is None:
            # Called as @Middleware.register(...) with keyword args.
            def decorator(fn: MiddlewareFunc) -> MiddlewareFunc:
                cls._registry.append(_MiddlewareEntry(
                    priority=priority,
                    func=fn,
                    name=name or fn.__name__,
                ))
                return fn
            return decorator
        # Called as @Middleware.register without parentheses.
        cls._registry.append(_MiddlewareEntry(
            priority=priority,
            func=func,
            name=name or func.__name__,
        ))
        return func

    def add(self, func: MiddlewareFunc, *, priority: int = 50, name: Optional[str] = None) -> None:
        """Add a middleware to this instance.

        :param func: The middleware function.
        :param priority: Lower numbers run first.
        :param name: Optional name for debugging.
        """
        self._stack.append(_MiddlewareEntry(
            priority=priority,
            func=func,
            name=name or func.__name__,
        ))
        self._built = False

    def compose(self, handler: Handler) -> Handler:
        """Compose the middleware stack around *handler*.

        Returns a new handler that runs all registered middleware before
        delegating to *handler*.  Middleware are invoked in priority order.

        :param handler: The final request handler.
        :returns: A composed handler.
        """
        if not self._stack and not self._registry:
            return handler

        # Build the chain once.
        if not self._built:
            self._build_chain(handler)

        return self._chain

    def _build_chain(self, handler: Handler) -> None:
        """Build the middleware chain from the registered middleware."""
        all_middleware = sorted(
            list(self._stack) + list(self.__class__._registry),
            key=lambda m: m.priority,
        )

        if not all_middleware:
            self._chain = handler
            return

        # Build the chain from the inside out.
        inner: Handler = handler
        for entry in reversed(all_middleware):
            outer_func = entry.func
            outer_name = entry.name

            sync_inner = inner

            def make_async_bridge(fn: MiddlewareFunc, next_handler: Handler) -> Handler:
                async def call_next(request: Request) -> Any:
                    result = next_handler(request)
                    if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                        return await result
                    return result

                async def async_wrapper(request: Request) -> Any:
                    return await fn(request, call_next)
                return async_wrapper

            def make_sync_wrapper(fn: MiddlewareFunc, next_handler: Handler) -> Handler:
                def wrapper(request: Request) -> Any:
                    result = fn(request, next_handler)
                    if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                        return result
                    return result
                return wrapper

            # Determine if the middleware is async.
            import inspect as _inspect
            if _inspect.iscoroutinefunction(fn := outer_func):
                inner = make_async_bridge(fn, sync_inner)
            else:
                inner = make_sync_wrapper(fn, sync_inner)

        self._chain = inner  # type: ignore[assignment]
        self._built = True

    def clear(self) -> None:
        """Clear all middleware from this instance."""
        self._stack.clear()
        self._built = False

    @classmethod
    def clear_all(cls) -> None:
        """Clear all globally registered middleware."""
        cls._registry.clear()


def wrap_handler(
    handler: Handler,
    *,
    middlewares: Optional[list[MiddlewareFunc]] = None,
) -> Handler:
    """Wrap a handler with a list of middleware functions.

    Convenience function for one-off middleware composition without a
    :class:`Middleware` instance.

    :param handler: The final handler.
    :param middlewares: List of middleware functions (lowest priority first).
    :returns: A composed handler.
    """
    if not middlewares:
        return handler

    mware = Middleware()
    for i, fn in enumerate(middlewares):
        mware.add(fn, priority=i)
    return mware.compose(handler)
