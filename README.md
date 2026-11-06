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

---

## Quick Start

### Start with the Basics

Create a file named `app.py`:

```python
from nexa import Nserver

# Create your application
app = Nserver("My First App")

# Define your first route
app.route("/")(lambda: "<h1>Hello, World!</h1>")

# Run the application
app.run()
```

### Run the Application

```bash
nexa run app.py
```

Your application should now serve your first HTML response at its configured local address and port.

---

## Templating

Nexa.py supports template rendering through `render_template()`.

### 1. Create the application

Create a file named `app.py`:

```python
from nexa import Nserver, render_template

# Create your application
app = Nserver("My First App")

# Define your first route
app.route("/")(lambda: render_template("index.html", Name="Nexa.py"))
```

### 2. Create your template

Create a folder named `templates` and inside it create `index.html`:

**Project structure:**

```text
NexaPY/
│
├── app.py
└── templates/
    └── index.html
```

**templates/index.html**

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
nexa run app.py
```

Your browser should display:

```html
Hi Nexa.py
```
