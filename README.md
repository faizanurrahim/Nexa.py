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

Use `nexa exec main` to execute a script through Nexa's existing script runner. Package installation is handled separately by NOVA (`nova install package`).
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

# Run the application
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

## Core events

Nexa Core registers browser-callable Python events on the same NXserver; it does not start a second HTTP server.

```python
from Nexa import Core, NXserver

app = NXserver("My App")
Core.init_app(app)

@Core.event("hello")
def hello(data):
    return {"message": "Hello " + data.get("name", "Guest")}

app.run()
```

Post `{"event": "hello", "data": {"name": "Nexa"}}` as JSON to `app.core_event_endpoint`. `Nserver` remains available as a deprecated compatibility name during migration.

## Project boundaries

- **NXserver** handles HTTP requests and responses.
- **Nexa Core** registers browser/Python event routes on NXserver.
- **NXLang** is a separate scripting-language concern; the Nexa CLI provides script execution.
- **NOVA** owns package management and is not bundled into the Nexa HTTP server.
