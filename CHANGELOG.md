# Changelog

All notable changes to Nexa.py are documented in this file.

## [0.6.0] — 2026-11-22

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
