from __future__ import annotations

from typing import Any, Callable, Optional

_METHOD_NAMES = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


class Blueprint:
    """A Blueprint groups related routes under a common prefix.

    Blueprints use the same decorator-style API as :class:`Nserver`::

        api = Blueprint("api", prefix="/api")

        @api.get("/ping")
        def pong():
            return jsonify({"status": "ok"})

        @api.route("/users", methods=["GET", "POST"])
        def users():
            ...

    The blueprint is registered on the server with
    :meth:`Nserver.register_blueprint`.
    """

    def __init__(self, name: str, prefix: str = "") -> None:
        if not name.isidentifier():
            raise ValueError(f"Blueprint name {name!r} must be a valid Python identifier")
        self.name = name
        self.prefix = prefix.rstrip("/")
        self._routes: list[tuple[str, Callable, set[str]]] = []

    def _add_route(self, path: str, methods: Optional[set[str]] = None):
        """Return a decorator that registers a route."""
        if not path.startswith("/"):
            raise ValueError("Routes must start with '/'")

        if methods is None:
            method_set = {"GET", "HEAD"}
        else:
            method_set = {m.upper() for m in methods}
            for m in method_set:
                if m not in _METHOD_NAMES and m != "HEAD":
                    raise ValueError(f"Unsupported HTTP method {m!r}")

        if "HEAD" not in method_set:
            method_set.add("HEAD")

        def decorator(handler: Callable) -> Callable:
            self._routes.append((path, handler, method_set))
            return handler

        return decorator

    def route(self, path: str, methods: Optional[list[str]] = None):
        """Register a handler for *path* on this blueprint.

        Args:
            path: URL path relative to the blueprint prefix, e.g. ``"/ping"``.
            methods: Optional explicit list of HTTP methods. When omitted the
                handler responds to GET and HEAD.
        """
        method_set: Optional[set[str]] = None
        if methods is not None:
            method_set = {m.upper() for m in methods}
        return self._add_route(path, method_set)

    def get(self, path: str):
        return self._add_route(path, {"GET"})

    def post(self, path: str):
        return self._add_route(path, {"POST"})

    def put(self, path: str):
        return self._add_route(path, {"PUT"})

    def patch(self, path: str):
        return self._add_route(path, {"PATCH"})

    def delete(self, path: str):
        return self._add_route(path, {"DELETE"})

    def head(self, path: str):
        return self._add_route(path, {"HEAD"})

    def options(self, path: str):
        return self._add_route(path, {"OPTIONS"})
