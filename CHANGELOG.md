# Changelog

All notable changes to Nexa.py are documented in this file.

## [0.7.0] — 2026-11-22

### Added

- **WebSocket support** — New `Nexa.websocket` module with a minimal stdlib-based WebSocket implementation. Register async WebSocket handlers with `NXserver.ws("/path")`; the server upgrades HTTP connections when the client sends a proper `Sec-WebSocket-Key` handshake. Handlers receive a `WebSocket` object supporting `async for message in ws`, `send_text()`, `send_bytes()`, and `close()`. Frames are properly masked/unmasked, ping/pong is handled, and close frames are supported.
- **Blade components** — New `Nexa.blade` module adding a component model on top of the NXscript compiler. `BladeNode` base class with a `template` attribute lets you define reusable components with typed parameters and children. `BladeCompiler` extends the base compiler with `<include src="..."/>` support for template composition. `install_blade_loader()` hooks Blade preprocessing into the server's template loader.
- **NXscript inheritance** — `extends` attribute on elements allows template inheritance: `<div extends="base.nx">...</div>` compiles to a `Template` call with the element's body as the `body` argument and remaining attributes passed through. Nested extends chains are supported.
- **Template caching** — `compile_file()` and the template loader now cache compiled source by file path, with `clear_compile_cache()` to invalidate. The cache is keyed by resolved absolute path so different working directories don't produce stale results.
- **Better compiler error messages** — Line numbers in `NexaSyntaxError` now correctly reference the original source line (1-indexed) instead of the post-split index. Unsupported attribute syntax produces a clear error showing the offending residue.
- **DevTools dashboard** — New `Nexa.devtools` module providing an in-memory debug dashboard. When `NXserver(debug=True)`, a hidden `__nexa__/` route prefix is mounted on localhost with a token-protected dashboard showing routes, middleware, config snapshot, request log, error log with sanitized tracebacks, and a live log tail. Token defaults to a random 16-character string and can be set via `server.debug_token`.
- **Lifecycle hooks** — `@server.on_startup` and `@server.on_shutdown` decorators register functions that run after the socket is bound and before the server socket is closed, respectively.
- **Custom error handlers** — `@server.error_handler(SomeException)` registers a handler that receives `(request, exception)` and returns a response tuple; the most-specific handler is selected via MRO walk.
- **CLI commands** — New `nexa dev` command starts the server in debug mode with auto-reload on file changes (using a watchdog observer). New `nexa routes` command prints all registered routes (static and parameterized) with their methods and handlers.
- **Request inspection for DevTools** — `NXserver.registered_routes` and `NXserver.registered_middleware` properties expose the current route and middleware tables for the DevTools dashboard and CLI.
- **Log ring buffer** — `Nexa.log` now supports an in-memory ring buffer (`enable_ring_buffer()`, `ring_buffer` property) and subscriber callbacks (`subscribe_ring()`/`unsubscribe_ring()`) so DevTools can tail recent log entries.
- **Improved error responses** — `_error_response` now accepts an optional `traceback_info` parameter that is included in the JSON response body only when `debug=True`, with paths outside the project directory sanitized.

### Changed

- `NXserver` constructor now accepts a `debug` parameter (default `False`). Debug mode enables the DevTools dashboard, debug tracebacks in error responses, and verbose startup/shutdown hook error printing.
- The `Router` class now stores the original path on `_Route` objects so DevTools can display the user-written path (with `<param>` segments) rather than the compiled pattern.
- `__init__.py` exports extended to include `websocket`, `devtools`, and `blade` module symbols.

### Fixed

- `nexa routes` command now displays both static and parameterized routes.
- DevTools endpoints are only mounted when `debug=True` and are bound to localhost; they are not exposed in production.
- Log ring buffer subscribers are notified for every log line when the buffer is enabled.

### Notes

- WebSocket support is minimal and built on stdlib; it handles the basic framing protocol but does not include extensions like permessage-deflate.
- The DevTools dashboard is a development aid; do not enable `debug=True` in production.
- Blade components are a lightweight component model; they do not include a full reactivity system.
- All existing tests pass without modification.

### Added

- **Threaded HTTP server** — `NXserver.run()` now uses `ThreadingHTTPServer` from the standard library, allowing concurrent request handling. A 30-second request timeout is applied so hung clients do not exhaust the thread pool.
- **ASGI adapter** — New `Nexa.asgi` module with `ASGIAdaptor` (ASGI 3 application) supporting HTTP scopes, request/response events, streaming bodies, lifespan events, async handler support, and disconnect propagation. Websocket and HTTP/2 scopes raise `ASGIError`.
- **WSGI compatibility preserved** — Existing WSGI callable interface on `NXserver` continues to work and benefits from the threaded transport.
- **Environment management** — New `Nexa.env` module with `Env` class providing `get`, `set`, `delete`, `exists`, `load`, `dump`, defaults, type coercion helpers, OS environment fallback, no-overwrite-by-default behavior, explicit override, graceful missing-file handling, and secret redaction in dumps. `NexaEnv` is a legacy alias.
- **Configuration system** — New `Nexa.config` module with `Config` class supporting TOML loading, dotted key access, nested value support, defaults, validation callbacks, environment variable overrides via `NXA_` prefix, and per-instance isolation with no global mutable state. `ConfigValidationError` raised on validation failure.
- **Middleware foundation** — New `Nexa.middleware` module with `Middleware` class providing deterministic priority ordering, sync and async middleware support, `call_next` pattern, and exception propagation. `@Middleware.register` decorator and `wrap_handler` convenience function included.
- **Static file serving** — New `Nexa.static` module with `StaticFiles` class supporting configurable directory, path traversal protection, symlink control, MIME type detection, content-length, HEAD support, 404 responses, cache headers (`Cache-Control`, `ETag`, `Last-Modified`), and conditional requests (`If-Modified-Since`, `If-None-Match`).
- **Logging** — New `Nexa.log` module with `NexaLog` class providing level filtering (TRACE/DEBUG/INFO/WARN/ERROR/FATAL), console and file output, structured (JSON) logging, request and exception helpers, and secret scrubbing. Module-level convenience functions (`info`, `debug`, `warn`, `error`, `fatal`, `request`, `exception`) use a default logger.
- **CLI diagnostics** — New `nexa doctor` command that verifies Python version, Nexa version, Typer availability, cache directory writability, and presence of optional config/environment files. New `nexa info` command showing runtime information and registered commands.
- **Version bump** — Version set to `0.6.0` in both `pyproject.toml` and `Nexa/nexa.py`.

### Changed

- `NXserver.run()` timeout set to 30 seconds.
- `get_env()` in the CLI now uses the new `Nexa.env` module.
- `__init__.py` exports extended to include `ASGIAdaptor`, `ASGIServer`, `StaticFiles`, `Env`, `NexaEnv`, `Config`, `ConfigValidationError`, and all logging helpers.

### Fixed

- Version consistency between `pyproject.toml` (was `0.5.2`) and `Nexa/nexa.py` (was `0.5.2-BETA`), both now `0.6.0`.
- `nexa info` command now lists all registered commands.

### Notes

- The threaded server is the first step toward full concurrency; a future release may add async I/O.
- ASGI support is real and spec-compliant; do not use the adaptor as a replacement for a production ASGI server.
- Existing `LIB/env.py` remains for backwards compatibility but is superseded by `Nexa/env.py`.
- All existing tests pass without modification.
