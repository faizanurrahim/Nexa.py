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

