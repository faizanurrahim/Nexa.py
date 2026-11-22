# Nexa.py – A Python Web Framework

Nexa.py is a Python web framework designed to make web application development easier.

## Initial Setup

### 1. Clone the repository

```bash
git clone https://github.com/faizanurrahim/Nexa.py.git NexaPY
```

### 2. Navigate to the project directory

```bash
cd NexaPY
```

### 3. Install Nexa.py

```bash
pip install -e .
```

### 4. Verify the installation

```bash
nexa --help
```

If the command displays the Nexa.py help menu, the installation was successful!
OR
```python
try:
    from Nexa import NXserver
    print("Nexa.py installed")
except Exception as exc: print(exc)
```

---

## Quick Start

### Start with the Basics

Create a file named `app.py`:

```python
from Nexa import NXserver

# Create your application
app = NXserver("My First App")

# Define your first route
app.route("/")(lambda: "<h1>Hello, World!</h1>")

if __name__ == "__main__":
    app.run()
```

### Run the Application

```bash
python app.py
```

NXserver binds to `127.0.0.1:3000` by default, keeping the application local to your machine. Set `host="0.0.0.0"` only when you intend to listen on every IPv4 interface.

To select a host and port explicitly:

```python
app = NXserver("My App", host="127.0.0.1", port=3000)
```

### Use a WSGI server

`app.run()` starts Nexa's built-in development server. To use a WSGI-compatible
server, define the application object in an importable module and let the WSGI
server import it. An `NXserver` instance is itself a WSGI application:

```python
from Nexa import NXserver

app = NXserver("MyApplication")

@app.get("/")
def home():
    return "Hello from Nexa!"

if __name__ == "__main__":
    app.run()
```

For example, after installing Waitress (`pip install waitress`), run this from
the directory containing `app.py`:

```bash
waitress-serve --listen=127.0.0.1:8080 app:app
```

The final `app:app` is Waitress's normal `module:variable` syntax: import the
`app` module and serve its `app` object. The `if __name__ == "__main__"` guard
keeps the built-in server from starting when the module is imported.

---

## Templating

Nexa.py supports template rendering through `render_template()`.

### 1. Create the application

Create a file named `app.py`:

```python
from Nexa import NXserver, render_template

# Create your application
app = NXserver("My First App")

# Define your first route
app.route("/")(lambda: render_template("index.nxs", Name="Nexa.py"))
```

### 2. Create your template

Create a folder named `templates` and inside it create `index.nxs`:

**Project structure:**

```text
NexaPY/
│
├── app.py
└── templates/
    └── index.nxs
```

**templates/index.nxs**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>My First Template</title>
</head>
<body>
    <h1>Hi {{Name}}</h1>
</body>
</html>
```

### 3. Run the Application

```bash
python app.py
```

Your browser should display:

```html
Hi Nexa.py
```
## More Concepts

Explore more Nexa.py features and examples:

[Read Concepts Documentation](concepts.md)

---

## Nexa.py 0.9.1

Version 0.9.1 redesigns the development workflow around your application's own
`NXserver` instance.

### Development server

```bash
nexa dev demo.py
```

`nexa dev` loads the application file, finds its `NXserver`, enables DevTools on
that instance (you do not need `debug=True` or any startup code), prints the
dashboard URL and token, and starts the server:

```text
Nexa.py Development Server

Application: demo.py
Server: http://127.0.0.1:3000
DevTools: http://127.0.0.1:3000/__nexa__/

DevTools token: <generated-token>

Starting development server...
```

Options:

- `--host`, `--port` — override the address configured in the application.
- `--app NAME` — choose the server variable when the file defines several.
- `--devtools-token TOKEN` — use a fixed token instead of a generated one.
- `--reload` / `--no-reload` — automatic reload is **on** by default.

### Application discovery

1. An explicit `--app NAME` always wins.
2. Otherwise the only `NXserver` instance in the file is used, whatever it is called.
3. If the file defines more than one, `--app NAME` is required; the CLI lists
   the candidates and exits.
4. No instance produces a clear error.

Conventional names (`app`, `application`, `server`, `nexa_app`, `app_server`)
are recommended, but the CLI never guesses between multiple instances.

`if __name__ == "__main__":` guards do not run during discovery, so the server
is not started twice.

### Reload

Reload starts the application in a `python -m Nexa.devworker` subprocess and
restarts it when Python files change. This works on Windows (no `multiprocessing`
pickling of nested functions), ignores caches, virtualenvs, build output and
non-Python files, and passes the same DevTools token to each restart.

`watchfiles` is optional — install it with `python -m pip install watchfiles`.
Without it, reload prints instructions and exits with code 1; `--no-reload`
still works.

### `nexa run serve` vs `nexa dev demo.py`

`nexa run serve` executes a Nexa script or target. `nexa dev demo.py` is the
development workflow for a plain Python application file: it discovers the
application's server and manages its DevTools lifecycle.

## Nexa.py 0.9.0

Version 0.9.0 stabilises typed routing and DevTools, and introduces
**NXLang Base** — the foundation of Nexa.py's language subsystem.

### DevTools 2.0

Open `http://127.0.0.1:3000/__nexa__/` while running `nexa dev`. The dashboard
now has a sign-in page: paste the printed DevTools token once and the browser
receives an `HttpOnly`, `SameSite=Strict` session cookie (8-hour expiry, `Secure`
over HTTPS). Sessions are rotated on every login, `POST /__nexa__/logout`
invalidates them, and DevTools refuses non-local clients. Programmatic clients
can keep sending the `X-DevTools-Token` header.

### Typed routing

```python
@app.get("/users/<int:user_id>", name="user")
def user(user_id):
    return jsonify({"id": user_id})

@app.get("/files/<path:filename>")
def files(filename):
    return jsonify({"filename": filename})

app.url_for("user", user_id=42)  # '/users/42'
```

Supported converters: `string`, `int`, `float`, `uuid`, `path`. Invalid values
produce a normal 404, and URL generation percent-encodes parameters.

### NXLang Base

```nx
include <base_compiler> as bc
include <<_request_handler>> as rh

do {
    throw(ERR("Something went wrong"))
}
unless ERR as e {
    print(e)
}
```

Run it with:

```bash
nexa exec main
```

**Implemented in 0.9.0:** lexer, parser, AST, compiler front end, native `nx`
runtime, `include <module>` / `include <<internal_module>>` resolution, the
`do { } unless ERR as e { }` error-handling model with inheritance matching,
the `ERR` error hierarchy, and `nexa exec`.

**Planned, not implemented yet:** expressions beyond literals and calls,
user-defined functions, control flow, standard library modules, and the `py`
environment. `nexa run`, `nexa dev`, `nexa routes`, `nexa doctor`, and
`nexa info` are unchanged.

## Nexa.py 0.7.0

Version 0.7.0 adds WebSocket support, Blade component templates, NXscript
inheritance and includes, template caching, DevTools dashboard, lifecycle
hooks, custom error handlers, and new CLI commands (`nexa dev`, `nexa routes`).

### WebSocket Support

The `Nexa.websocket` module provides a minimal stdlib-based WebSocket
implementation. Register async WebSocket handlers with `NXserver.ws("/path")`
and use `async for message in ws` to read messages.

```python
from Nexa import NXserver

app = NXserver("ws-demo", port=3000)

async def echo(ws):
    async for message in ws:
        await ws.send_text(f"echo: {message}")

app.ws("/chat")(echo)
app.run()
```

### Blade Components

The `Nexa.blade` module adds a component model on top of the NXscript
compiler. Define reusable components by subclassing `BladeNode` and
providing a `template` string.

```python
from Nexa import NXserver
from Nexa.blade import BladeNode, BladeCompiler, install_blade_loader

app = NXserver("app")

class Card(BladeNode):
    template = """
    <div class="card">
        <h2>{title}</h2>
        {children}
    </div>
    """
    def __init__(self, title, *children, **attrs):
        super().__init__(**attrs)
        self.title = title
        self.children = children

compiler = BladeCompiler()
install_blade_loader(app, compiler)

@app.route("/")
def home(request):
    return Card("Hello", P("Welcome"))
```

### NXscript Inheritance and Includes

Elements can extend base templates with the `extends` attribute:

```html
<div extends="base.nx">
    <p>Content here</p>
</div>
```

Templates can include other templates with `<include src="..."/>`.

### DevTools Dashboard

When `debug=True`, a hidden dashboard is available at `http://127.0.0.1:PORT/__nexa__/`.
It shows routes, middleware, config, request log, error log, and a live log tail.
Access requires the `X-DevTools-Token` header.

```python
app = NXserver("myapp", debug=True)
app.debug_token = "dev"  # optional
```

### Lifecycle Hooks

```python
@app.on_startup
def setup():
    print("Server starting...")

@app.on_shutdown
def cleanup():
    print("Server stopping...")
```

### Custom Error Handlers

```python
@app.error_handler(ValueError)
def handle_value_error(request, exc):
    return json(error=str(exc)), 400, {"Content-Type": "application/json"}
```

### CLI Commands

```bash
# Start dev server with auto-reload
nexa dev

# List all registered routes
nexa routes
```

### Log Tail

The `Nexa.log` module now supports an in-memory ring buffer for DevTools log tailing.

---

## Nexa.py 0.6.0

Version 0.6.0 adds a threaded HTTP server, ASGI support, environment and
configuration management, middleware, static file serving, centralized
logging, and CLI diagnostics.

### Threaded Server

`NXserver.run()` now handles concurrent requests using a threaded transport
from the standard library. A 30-second request timeout prevents hung clients
from exhausting worker threads.

### ASGI Support

The `ASGIAdaptor` class (from `Nexa.asgi`) wraps a Nexa handler as a
compliant ASGI 3 application. It supports HTTP scopes, request/response
events, streaming bodies, lifespan events, async handlers, and disconnect
propagation. Websocket and HTTP/2 scopes are not supported and raise
`ASGIError`.

```python
from Nexa import NXserver, ASGIAdaptor

app = NXserver("MyApp")

@app.get("/")
def home():
    return "Hello, ASGI!"

# Use with any ASGI server:
# asgi_app = ASGIAdaptor(app)
```

### Environment Management

The `Env` class (from `Nexa.env`) provides project-scoped environment
management with defaults, type helpers, persistence, OS environment fallback,
and secret redaction.

```python
from Nexa import Env

env = Env("myapp")
env.set("DEBUG", "true", type=bool)
assert env.get("DEBUG") is True
```

### Configuration

The `Config` class (from `Nexa.config`) reads TOML files with dotted keys,
defaults, validation, and environment variable overrides.

```python
from Nexa import Config

cfg = Config()
cfg.load("nexa.toml")
host = cfg.get("server.host", default="127.0.0.1")
```

### Middleware

The `Middleware` class (from `Nexa.middleware`) provides a composable
middleware pipeline with deterministic ordering, sync/async support, and the
`call_next` pattern.

```python
from Nexa import Middleware

@Middleware.register(priority=10)
def my_middleware(request, call_next):
    # Runs before the handler.
    response = call_next(request)
    # Runs after the handler.
    return response
```

### Static Files

The `StaticFiles` class (from `Nexa.static`) serves files safely with path
traversal protection, MIME types, cache headers, HEAD support, and
conditional requests.

```python
from Nexa import StaticFiles

static = StaticFiles(directory="public")
response = static.handle_request("GET", "/css/style.css")
```

### Logging

The `Nexa.log` module provides centralized logging with levels, console/file
output, structured (JSON) logging, request/exception helpers, and secret
scrubbing.

```python
from Nexa import info, error, request

info("Server started")
error("Something went wrong: %s", exc)
request("GET /health 200 3ms")
```

### CLI Diagnostics

```bash
nexa doctor   # Verify installation and environment.
nexa info     # Show runtime information.
```

### Version

```bash
nexa --version
# Nexa.py 0.6.0
```

