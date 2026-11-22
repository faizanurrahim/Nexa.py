"""DevTools — a lightweight debug dashboard for Nexa.py.

The dashboard is **disabled by default** and is only mounted when the
``NXserver`` is started with ``debug=True``.  All debug endpoints are bound
to ``127.0.0.1`` and require a ``X-DevTools-Token`` header whose value
matches ``server.debug_token``.

Usage::

    from Nexa import NXserver

    app = NXserver("myapp", debug=True)
    app.debug_token = "dev"  # optional; defaults to a random token on first access

    @app.route("/")
    def home(request):
        return "<h1>Hello</h1>"

    app.run()
"""

from __future__ import annotations

import html
import random
import string
import time
import traceback
from collections import deque
from typing import Any, Callable, Optional

from .log import get_logger
from .nxserver import NXserver, Request

_logger = get_logger("nexa.devtools")


class DevToolsRequestLogEntry:
    """A single recorded HTTP request for the DevTools request log."""

    def __init__(
        self,
        method: str,
        path: str,
        status: int,
        duration_ms: float,
        timestamp: float,
    ) -> None:
        self.method = method
        self.path = path
        self.status = status
        self.duration_ms = duration_ms
        self.timestamp = timestamp


class DevToolsErrorEntry:
    """A single recorded error for the DevTools error log."""

    def __init__(
        self,
        timestamp: float,
        request_method: str,
        request_path: str,
        error_type: str,
        message: str,
        traceback_html: str,
    ) -> None:
        self.timestamp = timestamp
        self.request_method = request_method
        self.request_path = request_path
        self.error_type = error_type
        self.message = message
        self.traceback_html = traceback_html


def _default_debug_token() -> str:
    """Return a random 16-character token for devtools auth."""
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choices(alphabet, k=16))


def _sanitize_traceback(tb: str, project_dir: Optional[str]) -> str:
    """Strip absolute paths outside the project directory from a traceback.

    Never include request bodies or other secrets in the output.
    """
    if project_dir is None:
        return tb
    out_lines: list[str] = []
    for line in tb.splitlines():
        if line.startswith("  File "):
            # Replace absolute paths outside the project dir with a relative hint.
            for part in line.split('"'):
                if part.startswith("/") and project_dir not in part:
                    line = line.replace(part, f'"{project_dir}/..."', 1)
                    break
        out_lines.append(line)
    return "\n".join(out_lines)


class DevTools:
    """In-memory debug dashboard for an ``NXserver`` instance.

    This object is created by :meth:`NXserver._ensure_devtools` and should
    not be instantiated directly.  Access it via ``server.devtools`` when
    ``debug=True``.
    """

    def __init__(self, server: NXserver) -> None:
        self._server = server
        self._request_log: deque[DevToolsRequestLogEntry] = deque(maxlen=200)
        self._error_log: deque[DevToolsErrorEntry] = deque(maxlen=100)
        self._token: str | None = None
        self._log_tail: deque[str] = deque(maxlen=500)

    # -- token ----------------------------------------------------------------

    @property
    def token(self) -> str:
        """The token required to access the debug endpoints."""
        if self._token is None:
            self._token = _default_debug_token()
        return self._token

    @token.setter
    def token(self, value: str) -> None:
        self._token = value

    # -- log tail -------------------------------------------------------------

    def enqueue_log(self, level: str, message: str) -> None:
        """Record a log line for the dashboard tail view.

        Called by the :mod:`Nexa.log` ring-buffer integration.
        """
        ts = time.time()
        entry = f"[{time.strftime('%H:%M:%S', time.localtime(ts))}] [{level}] {message}"
        self._log_tail.append(entry)

    # -- request log ----------------------------------------------------------

    def record_request(
        self,
        method: str,
        path: str,
        status: int,
        duration_ms: float,
    ) -> None:
        """Record a completed request in the request log."""
        entry = DevToolsRequestLogEntry(
            method=method,
            path=path,
            status=status,
            duration_ms=duration_ms,
            timestamp=time.time(),
        )
        self._request_log.append(entry)

    # -- error log ------------------------------------------------------------

    def record_error(
        self,
        request: Request,
        exc: BaseException,
        tb: Optional[str] = None,
    ) -> None:
        """Record an unhandled error in the error log."""
        tb_text = tb if tb is not None else "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        # Sanitize paths: only keep those inside the project dir.
        project_dir = None
        try:
            project_dir = self._server.project_dir.as_posix()
        except Exception:
            pass
        sanitized = _sanitize_traceback(tb_text, project_dir)
        tb_html = html.escape(sanitized).replace("\n", "<br>")

        entry = DevToolsErrorEntry(
            timestamp=time.time(),
            request_method=request.method,
            request_path=request.path,
            error_type=type(exc).__name__,
            message=str(exc),
            traceback_html=tb_html,
        )
        self._error_log.append(entry)
        _logger.warn(
            "DevTools recorded error [%s] %s: %s",
            type(exc).__name__,
            request.path,
            str(exc),
        )

    # -- dashboard pages ------------------------------------------------------

    def _protect(self, request: Request) -> Optional[tuple[str, int]]:
        """Return an error response if the request is not authenticated."""
        token = request.headers.get("X-DevTools-Token", "")
        if token != self.token:
            return (
                b'{"error":"forbidden","detail":"invalid or missing X-DevTools-Token"}',
                403,
                {"Content-Type": "application/json; charset=utf-8"},
            )
        return None

    def _routes_html(self, request: Request) -> tuple[bytes, int, dict[str, str]]:
        if err := self._protect(request):
            return err
        routes: list[dict[str, Any]] = []

        # Static routes.
        for path, route in self._server.router._static_routes.items():
            routes.append({
                "path": path,
                "methods": sorted(route.methods),
                "handler": self._format_handler(route.handler),
                "type": "static",
            })

        # Parameterized routes.
        for route in self._server.router._param_routes:
            routes.append({
                "path": route._original_path,
                "methods": sorted(route.methods),
                "handler": self._format_handler(route.handler),
                "type": "param",
                "params": route.param_names,
            })

        # Middleware.
        middleware: list[dict[str, Any]] = []
        for mw in self._server.registered_middleware:
            middleware.append({
                "name": getattr(mw, "__name__", str(mw)),
                "priority": getattr(mw, "_priority", 0),
            })

        body = _render_dashboard(
            request_path=request.path,
            routes=routes,
            middleware=middleware,
            config=self._config_snapshot(),
            log_tail=list(self._log_tail),
            request_log=list(self._request_log),
            error_log=list(self._error_log),
            token=self.token,
            server_name=self._server.name,
        )
        return (
            body.encode("utf-8"),
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )

    def _config_snapshot(self) -> dict[str, Any]:
        """Return a snapshot of the server configuration (public fields only)."""
        srv = self._server
        return {
            "name": srv.name,
            "host": srv.host,
            "port": srv.port,
            "debug": srv.debug,
            "static_folder": srv.static_folder,
            "template_folder": srv.template_folder,
            "max_body_size": srv.max_body_size,
            "project_dir": srv.project_dir.as_posix() if srv.project_dir else None,
        }

    @staticmethod
    def _format_handler(handler: Callable) -> str:
        name = getattr(handler, "__name__", str(handler))
        qualname = getattr(handler, "__qualname__", name)
        return f"<span class='handler'>{html.escape(qualname)}</span>"

    def _json_route(self, request: Request) -> tuple[bytes, int, dict[str, str]]:
        if err := self._protect(request):
            return err
        data: dict[str, Any] = {
            "server": self._config_snapshot(),
            "routes": [],
            "middleware": [],
        }
        for path, route in self._server.router._static_routes.items():
            data["routes"].append({
                "path": path,
                "methods": sorted(route.methods),
                "type": "static",
            })
        for route in self._server.router._param_routes:
            data["routes"].append({
                "path": route._original_path,
                "methods": sorted(route.methods),
                "params": route.param_names,
                "type": "param",
            })
        for mw in self._server.registered_middleware:
            data["middleware"].append({
                "name": getattr(mw, "__name__", str(mw)),
                "priority": getattr(mw, "_priority", 0),
            })
        import json as _json
        body = _json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        return (
            body,
            200,
            {"Content-Type": "application/json; charset=utf-8"},
        )

    def _log_tail_json(self, request: Request) -> tuple[bytes, int, dict[str, str]]:
        if err := self._protect(request):
            return err
        import json as _json
        body = _json.dumps(
            {"logs": list(self._log_tail)},
            ensure_ascii=False,
        ).encode("utf-8")
        return (
            body,
            200,
            {"Content-Type": "application/json; charset=utf-8"},
        )

    def _clear_log(self, request: Request) -> tuple[bytes, int, dict[str, str]]:
        if err := self._protect(request):
            return err
        self._log_tail.clear()
        self._request_log.clear()
        self._error_log.clear()
        import json as _json
        body = _json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8")
        return (
            body,
            200,
            {"Content-Type": "application/json; charset=utf-8"},
        )


def _render_dashboard(
    *,
    request_path: str,
    routes: list[dict[str, Any]],
    middleware: list[dict[str, Any]],
    config: dict[str, Any],
    log_tail: list[str],
    request_log: list[DevToolsRequestLogEntry],
    error_log: list[DevToolsErrorEntry],
    token: str,
    server_name: str,
) -> str:
    """Render the DevTools dashboard as an HTML page."""
    rows = ""
    for r in routes:
        methods = " ".join(r["methods"])
        params = ""
        if r.get("params"):
            params = f" <code>{', '.join(r['params'])}</code>"
        rows += (
            f"<tr>"
            f"<td class='path'>{html.escape(r['path'])}{params}</td>"
            f"<td>{html.escape(methods)}</td>"
            f"<td>{r['handler']}</td>"
            f"<td>{r['type']}</td>"
            f"</tr>"
        )

    mw_rows = ""
    for m in middleware:
        mw_rows += (
            f"<tr>"
            f"<td>{m['name']}</td>"
            f"<td>{m['priority']}</td>"
            f"</tr>"
        )

    log_lines = ""
    for line in log_tail[-100:]:
        escaped = html.escape(line)
        log_lines += f"<div class='log-line'>{escaped}</div>"

    req_rows = ""
    for r in request_log[-50:]:
        cls = "ok" if r.status < 400 else ("err" if r.status >= 500 else "warn")
        req_rows += (
            f"<tr class='{cls}'>"
            f"<td>{r.method}</td>"
            f"<td>{html.escape(r.path)}</td>"
            f"<td>{r.status}</td>"
            f"<td>{r.duration_ms:.1f}ms</td>"
            f"<td>{time.strftime('%H:%M:%S', time.localtime(r.timestamp))}</td>"
            f"</tr>"
        )

    err_rows = ""
    for e in error_log[-20:]:
        err_rows += (
            f"<tr>"
            f"<td>{time.strftime('%H:%M:%S', time.localtime(e.timestamp))}</td>"
            f"<td>{html.escape(e.request_method)} {html.escape(e.request_path)}</td>"
            f"<td><code class='err-type'>{html.escape(e.error_type)}</code></td>"
            f"<td>{html.escape(e.message)}</td>"
            f"<td><pre class='traceback'>{e.traceback_html}</pre></td>"
            f"</tr>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Nexa DevTools — {html.escape(server_name)}</title>
<style>
  :root {{
    --bg: #0e1116;
    --panel: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --muted: #8b949e;
    --ok: #3fb950;
    --warn: #d29922;
    --err: #f85149;
    --accent: #58a6ff;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font: 13px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  }}
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 24px 20px 60px; }}
  h1 {{ font-size: 18px; margin: 0 0 4px; }}
  .subtitle {{ color: var(--muted); margin: 0 0 20px; font-size: 12px; }}
  .token-bar {{
    display: flex; gap: 8px; align-items: center;
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 6px; padding: 8px 12px; margin-bottom: 18px;
  }}
  .token-bar code {{ color: var(--accent); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  .copy-btn {{
    margin-left: auto; background: transparent; border: 1px solid var(--border);
    color: var(--text); padding: 2px 10px; border-radius: 4px; cursor: pointer;
    font-size: 12px;
  }}
  .copy-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }}
  .card {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
    padding: 14px;
  }}
  .card h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: .05em;
    color: var(--muted); margin: 0 0 10px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th, td {{ text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--border); }}
  th {{ color: var(--muted); font-weight: 600; }}
  td.path {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--accent); }}
  .handler {{ color: #d2a8ff; }}
  tr.ok td:first-child {{ border-left: 3px solid var(--ok); padding-left: 5px; }}
  tr.warn td:first-child {{ border-left: 3px solid var(--warn); padding-left: 5px; }}
  tr.err td:first-child {{ border-left: 3px solid var(--err); padding-left: 5px; }}
  .err-type {{ color: var(--err); }}
  pre.traceback {{ margin: 0; font-size: 11px; background: #0d1117;
    padding: 6px 8px; border-radius: 4px; color: #c9d1d9;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; overflow-x: auto; max-height: 120px;
  }}
  .log-line {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 11px; padding: 1px 0; color: var(--muted);
    border-bottom: 1px solid #ffffff08; }}
  .full {{ grid-column: 1 / -1; }}
  .footer {{ margin-top: 24px; color: var(--muted); font-size: 11px; }}
  .git {{ color: var(--muted); font-size: 11px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Nexa DevTools</h1>
  <p class="subtitle">Debug dashboard for <code>{html.escape(server_name)}</code> ·
    <a href="/__nexa__/api">JSON API</a> ·
    <a href="/__nexa__/log">Log tail</a> ·
    <a href="/__nexa__/clear">Clear logs</a>
  </p>

  <div class="token-bar">
    <span>DevTools token:</span>
    <code>{html.escape(token)}</code>
    <button class="copy-btn" onclick="navigator.clipboard.writeText(`{html.escape(token)}`).then(()=>this.textContent='copied')">copy</button>
  </div>

  <div class="grid">
    <div class="card">
      <h2>Routes ({len(routes)})</h2>
      <table>
        <thead><tr><th>Path</th><th>Methods</th><th>Handler</th><th>Type</th></tr></thead>
        <tbody>{rows or "<tr><td colspan='4' class='muted'>No routes registered</td></tr>"}</tbody>
      </table>
    </div>

    <div class="card">
      <h2>Middleware ({len(middleware)})</h2>
      <table>
        <thead><tr><th>Name</th><th>Priority</th></tr></thead>
        <tbody>{mw_rows or "<tr><td colspan='2' class='muted'>No middleware registered</td></tr>"}</tbody>
      </table>
    </div>

    <div class="card full">
      <h2>Config</h2>
      <table>
        <tbody>
          {''.join(f'<tr><td>{k}</td><td>{html.escape(str(v))}</td></tr>' for k, v in config.items())}
        </tbody>
      </table>
    </div>

    <div class="card">
      <h2>Recent Requests ({len(request_log)})</h2>
      <table>
        <thead><tr><th>Method</th><th>Path</th><th>Status</th><th>Time</th><th>When</th></tr></thead>
        <tbody>{req_rows or "<tr><td colspan='5' class='muted'>No requests yet</td></tr>"}</tbody>
      </table>
    </div>

    <div class="card">
      <h2>Errors ({len(error_log)})</h2>
      <table>
        <thead><tr><th>When</th><th>Request</th><th>Type</th><th>Message</th><th>Traceback</th></tr></thead>
        <tbody>{err_rows or "<tr><td colspan='5' class='muted'>No errors recorded</td></tr>"}</tbody>
      </table>
    </div>

    <div class="card full">
      <h2>Log Tail ({len(log_tail)} entries)</h2>
      {log_lines or "<div class='log-line' style='color:var(--muted)'>No log entries yet</div>"}
    </div>
  </div>

  <p class="footer git">Powered by Nexa.py DevTools · debug mode</p>
</div>
</body>
</html>
"""


class _DevToolsMount:
    """A lightweight WSGI-like callable that dispatches DevTools sub-routes.

    Mounted at ``__nexa__/`` when ``debug=True``.  Each path like
    ``__nexa__/`` or ``__nexa__/api`` is routed to the matching
    ``DevTools`` method.
    """

    def __init__(self, devtools: DevTools) -> None:
        self._devtools = devtools
        self._routes: dict[str, Callable[[Request], tuple[bytes, int, dict[str, str]]]] = {
            "": devtools._routes_html,
            "/": devtools._routes_html,
            "/api": devtools._json_route,
            "/log": devtools._log_tail_json,
            "/clear": devtools._clear_log,
        }

    def __call__(self, request: Request) -> tuple[bytes, int, dict[str, str]]:
        return self.dispatch(request)

    def dispatch(self, request: Request) -> tuple[bytes, int, dict[str, str]]:
        """Dispatch a request to the matching DevTools handler."""
        from urllib.parse import unquote, urlparse
        parsed = urlparse(request.path)
        path = unquote(parsed.path)

        # Strip the "__nexa__" prefix.
        prefix = "/__nexa__"
        if path == prefix or path == prefix + "/":
            subpath = ""
        elif path.startswith(prefix + "/"):
            subpath = path[len(prefix):]
        else:
            return (
                b'{"error":"not found"}',
                404,
                {"Content-Type": "application/json; charset=utf-8"},
            )

        handler = self._routes.get(subpath)
        if handler is None:
            return (
                b'{"error":"not found"}',
                404,
                {"Content-Type": "application/json; charset=utf-8"},
            )
        return handler(request)
