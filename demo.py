"""
Nexa.py 0.9.1 demo — lifecycle hooks, error handlers, DevTools, WebSocket, Blade.

Run with::

    python demo.py

Then visit:

* http://127.0.0.1:3000/              — the home page
* http://127.0.0.1:3000/api/value     — a JSON API that can raise errors
* http://127.0.0.1:3000/api/error     — triggers a custom error handler
* http://127.0.0.1:3000/ws            — WebSocket echo (use a WebSocket client)
* http://127.0.0.1:3000/__nexa__/     — DevTools dashboard (token in server output)
"""

from __future__ import annotations

from pathlib import Path

from Nexa import NXserver
from Nexa.blade import BladeCompiler, BladeNode, install_blade_loader

# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

app = NXserver("demo", debug=True, port=3000)

# Set up the Blade compiler and install it as the template loader.
blade_compiler = BladeCompiler(base_path=Path.cwd())
install_blade_loader(app, blade_compiler)
app._blade_compiler = blade_compiler  # for demo route access

print("DevTools dashboard will be available at: http://127.0.0.1:3000/__nexa__/")


# ---------------------------------------------------------------------------
# Lifecycle hooks
# ---------------------------------------------------------------------------

@app.on_startup
def on_startup() -> None:
    print("[demo] Startup hook fired — server is ready to accept connections.")


@app.on_shutdown
def on_shutdown() -> None:
    print("[demo] Shutdown hook fired — cleaning up before exit.")


# ---------------------------------------------------------------------------
# Blade component
# ---------------------------------------------------------------------------

class Card(BladeNode):
    """A simple Blade component that wraps content in a styled card."""

    template = """
    <div class="card">
        <h2>{title}</h2>
        {children}
    </div>
    """

    def __init__(self, title: str, *children: str, **attrs: object) -> None:
        super().__init__(**attrs)
        self.title = title
        self.children = list(children)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def home(request) -> str:
    """Home page using a Blade component."""
    return Card(
        "Welcome to Nexa.py 0.9.1",
        "This page is rendered with a Blade component.",
        "Try the <a href='/api/value'>JSON API</a> or the "
        "<a href='/api/error'>custom error handler</a>.",
    ).render(app._blade_compiler if hasattr(app, "_blade_compiler") else BladeCompiler())


@app.get("/api/value")
def api_value(request) -> dict:
    """A simple JSON API endpoint."""
    return {"message": "Hello from the API", "status": "ok"}


@app.get("/api/error")
def api_error(request) -> None:
    """Endpoint that triggers the custom ValueError handler."""
    raise ValueError("This is a controlled error for demonstration.")


@app.get("/api/validate")
def api_validate(request) -> dict:
    """Endpoint that validates a query parameter."""
    from Nexa import request as current_request
    q = current_request.query
    name = q.get("name", [""])[0]
    if not name.strip():
        raise ValueError("Query parameter 'name' is required.")
    return {"greeting": f"Hello, {name}!"}


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

async def ws_echo(ws) -> None:
    """Echo back every text message the client sends."""
    async for message in ws:
        await ws.send_text(f"echo: {message}")


app.ws("/ws")(ws_echo)


# ---------------------------------------------------------------------------
# Custom error handler
# ---------------------------------------------------------------------------

@app.error_handler(ValueError)
def handle_value_error(request, exc: ValueError):
    """Return a JSON error response for ValueError."""
    from Nexa.__json import jsonify
    return jsonify({"error": "bad request", "detail": str(exc)}, status=400)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\nStarting Nexa.py demo server on http://127.0.0.1:3000\n")
    print("Press Ctrl+C to stop.\n")
    try:
        app.run()
    except KeyboardInterrupt:
        print("\nServer stopped by user.")
