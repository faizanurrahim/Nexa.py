# Changelog

All notable changes to Nexa.py are documented in this file.

## [1.0.0] — 2026-11-22

### Added

- **Nova** — New standalone project/package manager CLI (`nova`) with `init`, `install`, `update`, `remove`, `list`, `run`, `exec`, `doctor`, and `clean` commands. Projects are initialized with a `.nova/` layout; Nexa runtime resources live under `.nova/nexa/`.
- **TextResponse** — Convenience response class for plain-text bodies, exported from `Nexa` and `Nexa.nserver`.
- **JSONResponse metadata** — `JSONResponse` and `jsonify()` now accept optional `headers`, preserving cookies and other metadata through the response pipeline.
- **Nexa.py 1.0.0** — Version bump and production/stable classification.

### Changed

- Version bumped to `1.0.0` in `pyproject.toml` and `Nexa.nexa`.

## [0.9.1] — 2026-11-22

### Added

- **`nexa dev <file>`** — The development command now loads a Python application file, discovers its existing `NXserver` instance, enables DevTools on that instance, prints the dashboard URL and a generated token, and starts the application. `--host`, `--port`, `--app NAME`, `--devtools-token`, `--reload` and `--no-reload` are supported. When the file defines several servers, `--app` selects one by variable name.
- **Application discovery** — A single `NXserver` instance is discovered under any variable name; when the file defines several, `--app NAME` selects one and the CLI lists the candidates instead of guessing. No instance produces a clear error. Conventional names (`app`, `application`, `server`, `nexa_app`, `app_server`) are recommended and listed in the error. Module execution uses a private module name, so `if __name__ == "__main__": app.run()` guards do not start a second server during discovery.
- **`NXserver.enable_devtools(token=None)`** — A dedicated development-mode initializer that mounts DevTools and the dashboard without turning on `debug=True` error output. The server still owns the single DevTools instance, and `app.run()` in production does not mount DevTools unless the application enables it.
- **Subprocess reloader** — `nexa dev` watches the application directory and restarts a `python -m Nexa.devworker` worker process. This replaces the nested-function `multiprocessing` target that failed on Windows with `PicklingError`. Reload ignores caches, virtualenvs, build output and non-Python files.
- **Optional `watchfiles` dependency** — Declared as the `dev` extra. When reload is requested without it, the CLI prints install instructions and exits with code 1; `--no-reload` works without it.
- **Documentation** — README and concepts now describe the development lifecycle, discovery rules, reload options, optional dependency, and the difference between `nexa run serve` and `nexa dev demo.py`.

### Changed

- `nexa dev` requires an application file argument; the previous behaviour of starting an empty server named `dev` was replaced by the workflow above.
- DevTools mounting is controlled by the presence of the DevTools mount rather than the `debug` flag, so `enable_devtools()` works independently of debug mode.
- Version bumped to `0.9.1` in `pyproject.toml` and `Nexa/nexa.py`.

### Fixed

- Windows `nexa dev --reload` no longer raises `PicklingError: Can't pickle local object 'dev.<locals>._run_server'`.
- The development server no longer creates a second `NXserver` or a second `DevTools` instance.
- DevTools authentication survives reload restarts because the worker receives the same token through `NEXA_DEVTOOLS_TOKEN`.

### Notes

- Browser DevTools sessions are in memory per server process, so a reload requires signing in again with the same printed token; `X-DevTools-Token` clients are unaffected.
- DevTools remains localhost-only and no token is placed in URLs.

## [0.9.0] — 2026-11-22

### Added

- **NXLang Base** — New `Nexa.nxlang` package providing the foundations of the NXLang language: a line-aware lexer, recursive-descent parser, AST, compiler front end, tree-walking runtime, module registry, execution environments, and the `ERR` error hierarchy. The primary implementation module is `Nexa/nxlang/nx.py` as specified.
- **NXLang module inclusion** — `include <module> as alias` resolves regular NXLang modules; `include <<module>> as alias` resolves Nexa-internal modules through `ModuleRegistry` only, never as Python imports. Missing modules raise `ImportERR` (regular) or `ModuleERR` (internal) listing the available modules.
- **NXLang error handling** — `do { ... } unless ERR as e { ... }` and `throw(ERR("message"))`. Handlers match by type including inheritance, the first matching handler wins, multiple handlers may follow one `do` block, and unmatched errors propagate. Error objects carry filename, line, and column. The hierarchy is `ERR` → `SyntaxERR`, `CompileERR`, `RuntimeERR`, `ImportERR`, `ModuleERR`, `EnvironmentERR`, `TypeERR`, `NameERR`, `InternalERR`.
- **`nexa exec` for NXLang** — `nexa exec main` resolves `main.nx` (or `main.nx` directly), executes it through the NXLang runtime, forwards positional arguments as `args`, reports errors with exit code 1, and preserves the legacy script runner for non-`.nx` targets.
- **DevTools 2.0 browser sessions** — The dashboard now has a sign-in page. Posting the DevTools token creates a cryptographically random session (`secrets.token_urlsafe`) stored server-side with an 8-hour expiry. Session cookies are `HttpOnly`, `SameSite=Strict`, scoped to `/__nexa__`, and marked `Secure` when the request arrives over HTTPS. Login always issues a fresh session identifier (fixation resistant); `POST /__nexa__/logout` invalidates the session and clears the cookie.
- **DevTools status overview** — The dashboard now shows server status (debug mode, bind address, WebSocket route count, recorded requests and errors), adds a viewport meta tag and a responsive layout, and links a sign-out action.
- **Typed routing** — Completed `string`, `int`, `float`, `uuid`, and `path` converters; `url_for()` / `build_url()` with per-segment percent-encoding, route naming, and explicit errors for unknown names, missing parameters, and unexpected parameters.

### Changed

- DevTools tokens are generated with `secrets.token_urlsafe` instead of `random.choices`.
- Unauthenticated HTML dashboard requests now receive the login page (HTTP 200) instead of raw JSON; JSON endpoints such as `/__nexa__/api` continue to return `403` for missing credentials.
- `X-DevTools-Token` header authentication is preserved for programmatic clients.
- DevTools refuses non-local clients even when the HTTP server binds to `0.0.0.0`.
- Version bumped to `0.9.0` in `pyproject.toml` and `Nexa/nexa.py`; `Nexa.nxlang` added to the packaged modules.

### Fixed

- DevTools dashboard navigation no longer fails with `invalid or missing X-DevTools-Token`; browsers authenticate through the session cookie.
- Router converters no longer raise on invalid input: invalid `int`, `float`, and `uuid` values now fall through to the normal 404 path.
- `<path:name>` captures multiple URL segments (`/items/a/b/c` → `{"name": "a/b/c"}`).
- `Router._CONVERTERS` is resolved consistently and `_Route.original_path` is used everywhere (route listing and DevTools).

### Notes

- NXLang Base is intentionally small: there are no user-defined functions, arithmetic, branching statements, standard library modules, or `py` environment yet. Those are planned for later NXLang releases.
- `/sw.js` is not referenced by the dashboard, so no service worker was added.
- NXLang errors use `do`/`unless` syntax; `try`, `catch`, and `except` are not part of NXLang.

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
