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

