"""Event-based browser/Python communication over an NXserver instance."""

from __future__ import annotations

from typing import Any, Callable
from weakref import WeakKeyDictionary

from ..nxserver import NXserver, jsonify, request


class Core:
    """Register browser-callable Python events on the existing NXserver.

    Browser clients POST ``{"event": "name", "data": {...}}`` to the
    app-specific ``core_event_endpoint`` installed by :meth:`init_app`.
    """

    _event_handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
    _apps: WeakKeyDictionary[NXserver, str] = WeakKeyDictionary()

    @classmethod
    def event(cls, name: str):
        """Register a Python handler callable from a browser event request."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Core event names must be non-empty strings.")
        name = name.strip()

        def decorator(handler: Callable[[dict[str, Any]], Any]):
            if name in cls._event_handlers:
                raise ValueError(f"Core event {name!r} is already registered.")
            cls._event_handlers[name] = handler
            return handler

        return decorator

    @classmethod
    def init_app(cls, app: NXserver) -> NXserver:
        """Attach Core's event endpoint to *app* without starting another server."""
        if not isinstance(app, NXserver):
            raise TypeError("Core.init_app() requires an NXserver instance.")
        if app in cls._apps:
            return app

        endpoint = "/__nexa/core/events"
        suffix = 1
        while app.router.route_for_path(endpoint) is not None:
            endpoint = f"/__nexa/core/events-{suffix}"
            suffix += 1

        @app.post(endpoint)
        def dispatch_event():
            payload = request.json
            if not isinstance(payload, dict):
                return jsonify(
                    {"error": "Request body must be a JSON object."}, status=400
                )

            event_name = payload.get("event")
            if not isinstance(event_name, str) or not event_name:
                return jsonify(
                    {"error": "A non-empty 'event' name is required."}, status=400
                )

            handler = cls._event_handlers.get(event_name)
            if handler is None:
                return jsonify(
                    {"error": f"Unknown Core event {event_name!r}."}, status=404
                )

            data = payload.get("data", {})
            if not isinstance(data, dict):
                return jsonify(
                    {"error": "Core event 'data' must be a JSON object."}, status=400
                )

            return jsonify(handler(data))

        app.core_event_endpoint = endpoint
        cls._apps[app] = endpoint
        return app
