# Nexa.py Basic Concepts

# Concept 1: API Creation

Nexa.py provides the `jsonify()` function for creating JSON responses. Combined with Nexa's routing system, it allows developers to build APIs and handle HTTP requests efficiently.

## Example 1: Creating a Basic API (GET)

In this example, we'll create a simple GET endpoint that returns a JSON response.

### Step 1: Create the application

Create a Python file named `app.py`:

```python
# Import NXserver and jsonify
from Nexa import jsonify, NXserver

# Initialize the application
app = NXserver("My First App")

# Register a GET endpoint
app.route("/api/v1/working")(
    lambda: jsonify({"API": "Working"})
)

# Run the application
app.run()
```

### Step 2: Access the API

Start the application and open the following URL in your browser:

`http://localhost:3000/api/v1/working`

**Expected response:**

```json
{
    "API": "Working"
}
```

## Example 2: Receiving JSON Data (POST)

Nexa.py provides a `request` object for accessing incoming HTTP request data.

You can use `request.json` to retrieve and process JSON data sent through a POST request.

### Step 1: Create a POST endpoint

```python
from Nexa import NXserver, jsonify
from Nexa.nxserver import request

# Initialize the application
app = NXserver("NexaApp", debug=True)

# Register a POST endpoint
@app.post("/api/users")
def create_user():
    # Retrieve incoming JSON data
    data = request.json

    # Extract user information
    username = data.get("username")
    email = data.get("email")

    # Return a JSON response
    return jsonify({
        "message": "User created!",
        "username": username,
        "email": email
    })

# Run the application
app.run()
```

### Step 2: Send a POST request

You can use cURL to send JSON data to your endpoint:

```bash
curl -X POST http://127.0.0.1:3000/api/users \
-H "Content-Type: application/json" \
-d '{"username":"faizan","email":"faizan@example.com"}'
```

**Expected response:**

```json
{
    "message": "User created!",
    "username": "faizan",
    "email": "faizan@example.com"
}
```

### API Creation Summary

| Feature | Nexa.py implementation |
|---|---|
| JSON responses | `jsonify()` |
| GET endpoints | `app.get()` / `app.route()` |
| POST endpoints | `app.post()` |
| Access request JSON | `request.json` |
| Request object | `Nexa.nxserver.request` |

---

# Concept 2: Templating Using NXscript

Nexa.py includes a built-in templating engine called **NXscript**.

The `render_template()` function allows developers to render HTML and NXscript templates dynamically.

By default, templates are stored inside the application's `templates/` directory.

## Example 1: Rendering a Basic HTML Template

In this example, we'll create a simple webpage using a standard HTML template.

### Step 1: Create the application

Create a Python file named `app.py`:

```python
from Nexa import NXserver, render_template

# Initialize the application
app = NXserver("MyApp")

# Register the homepage
app.get("/")(
    lambda: render_template("index.html")
)

# Run the application
app.run()
```

### Step 2: Create the HTML template

Create the following project structure:

```text
MyApp/
├── app.py
└── templates/
    └── index.html
```

Inside `templates/index.html`, add the following HTML:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>My Nexa App | Hello World!</title>
</head>
<body>
    <h1>Hello World!</h1>
</body>
</html>
```

### Step 3: Run the application

```bash
python app.py
```

### Step 4: Open the application

Visit:

`http://127.0.0.1:3000/`

**Expected output:**

A webpage displaying:

# Hello World!

## Example 2: Rendering a Dynamic NXscript Template

Unlike a regular HTML template, NXscript allows you to inject Python variables into your templates.

In this example, we'll pass a dynamic name from a URL parameter to an NXscript template.

### Step 1: Create the application

Create `app.py`:

```python
from Nexa import NXserver, render_template

# Initialize the application
app = NXserver("MyApp")

# Register a dynamic route
app.get("/<name>")(
    lambda name: render_template(
        "index.nxs",
        Name=name
    )
)

# Run the application
app.run()
```

### Step 2: Create the NXscript template

Create the following project structure:

```text
MyApp/
├── app.py
└── templates/
    └── index.nxs
```

Inside `templates/index.nxs`, add:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>My Nexa App | Hello World!</title>
</head>
<body>
    <h1>Hello {{Name}}</h1>
</body>
</html>
```

### Step 3: Run the application

```bash
python app.py
```

### Step 4: Test the dynamic route

Open the following URL:

`http://127.0.0.1:3000/Faizan`

**Expected output:**

# Hello Faizan

You can also try other names:

| URL | Expected output |
|---|---|
| `/Faizan` | Hello Faizan |
| `/Shrikari` | Hello Shrikari |
| `/Akshaya` | Hello Akshaya |

### Understanding NXscript Variables

Let's understand how the dynamic variable works:

**Python:**

```python
render_template("index.nxs", Name=name)
```

Here, `Name=name` passes the Python variable `name` into the NXscript template.

**NXscript:**

```html
<h1>Hello {{Name}}</h1>
```

The `{{Name}}` syntax tells NXscript to resolve the template variable using the value passed from Python.

This allows developers to generate dynamic HTML pages without manually constructing HTML responses.
# Concept 3: Database Management Using NXsql

Nexa.py provides **NXsql**, a database schema compiler and SQLite runner that simplifies database table creation and SQL execution.

NXsql allows you to define database tables using Python classes and objects instead of manually writing every `CREATE TABLE` statement.

It also provides tools for compiling schemas into SQL, executing queries, managing constraints, and checking whether tables exist.

## 1. Importing NXsql

Import the required components from `Nexa.nxsql`:

```python
from Nexa.nxsql import (
    curxor,
    Table,
    Column,
    check,
    CURRENT_TIMESTAMP
)
```

- `curxor`: Main NXsql API for compiling and executing SQL.
- `Table`: Used to define database tables.
- `Column`: Used to define table columns and their properties.
- `check()`: Defines a column-level CHECK constraint.
- `CURRENT_TIMESTAMP`: Provides the current timestamp as a SQL default expression.

## 2. Creating Your First Database Table

NXsql provides `Table.new()` to define a database table.

### Example: Creating a Users Table

```python
from Nexa.nxsql import curxor, Table, Column

# Define the database schema
users = Table.new(
    name="users",

    id=Column(
        "Int",
        primary_key=True,
        auto_increment=True
    ),

    username=Column(
        "Str",
        non_nullable=True,
        unique=True
    ),

    email=Column(
        "Str",
        non_nullable=True,
        unique=True
    )
)

# Compile and execute the schema
curxor.execute(
    file="main.db",
    schema=users
)
```

**What happens here?**

1. `Table.new()` defines a table named `users`.
2. `Column()` defines the columns and their properties.
3. `curxor.execute()` compiles the schema and executes it against `main.db`.
4. The database file is created if it does not already exist.

The `id` column is configured as an auto-incrementing primary key, while `username` and `email` are unique and cannot be NULL.

## 3. Understanding Column Types

NXsql supports the following column types:

| NXsql Type | SQLite Type |
|---|---|
| `Int` / `Integer` | INTEGER |
| `Str` / `String` / `Text` | TEXT |
| `Float` | REAL |
| `Bool` / `Boolean` | INTEGER |
| `Blob` | BLOB |
| `Date` / `Datetime` | TEXT |
| `Decimal` | NUMERIC |

Example:

```python
age = Column("Int")
username = Column("Str")
price = Column("Float")
is_active = Column("Bool")
```

## 4. Adding Column Constraints

NXsql supports several column properties to define database constraints.

### Primary Key

```python
id=Column("Int", primary_key=True)
```

### Auto Increment

```python
id=Column(
    "Int",
    primary_key=True,
    auto_increment=True
)
```

`auto_increment=True` requires an integer primary key.

### NOT NULL

```python
username=Column("Str", non_nullable=True)
```

Prevents the column from accepting NULL values.

### UNIQUE

```python
email=Column("Str", unique=True)
```

Prevents duplicate values in the column.

### DEFAULT

```python
status=Column("Str", default="active")
```

Sets a default value when no value is supplied.

### CHECK

NXsql provides `check()` to define restricted CHECK expressions.

```python
from Nexa.nxsql import check

age=Column(
    "Int",
    check=check(">= 13")
)
```

Other supported examples:

```python
check("< 100")
check("IN (1, 2, 3)")
check("LIKE 'abc%'")
```

The CHECK expression supports a restricted syntax rather than arbitrary SQL.

### CURRENT_TIMESTAMP

You can use `CURRENT_TIMESTAMP` as a default expression:

```python
from Nexa.nxsql import CURRENT_TIMESTAMP

created_at=Column(
    "Datetime",
    default=CURRENT_TIMESTAMP
)
```

## 5. Creating Foreign Keys

NXsql supports foreign-key references through `references()`.

```python
from Nexa.nxsql import Table, Column, references, curxor

users = Table.new(
    name="users",
    id=Column("Int", primary_key=True, auto_increment=True),
    username=Column("Str", unique=True)
)

posts = Table.new(
    name="posts",
    id=Column("Int", primary_key=True, auto_increment=True),
    user_id=Column(
        "Int",
        references=references(
            "users",
            "id",
            on_delete="CASCADE"
        )
    ),
    title=Column("Str", non_nullable=True)
)

# Execute both schemas
curxor.execute(
    file="main.db",
    scripts=curxor.compile_many([users, posts])
)
```

The `references()` function supports:

- `table`: Referenced table.
- `column`: Referenced column (defaults to `"id"`).
- `on_delete`: Action when the referenced row is deleted.
- `on_update`: Action when the referenced value is updated.

Supported foreign-key actions:

- `CASCADE`
- `RESTRICT`
- `SET NULL`
- `SET DEFAULT`
- `NO ACTION`

## 6. Compiling Schemas into SQL

NXsql provides `curxor.compile()` to convert a table schema into ordinary SQL text.

```python
sql = curxor.compile(users)

print(sql)
```

The output is a SQL `CREATE TABLE` statement.

**Important:** `compile()` does not execute SQL. It only generates SQL text.

You can also compile multiple schemas:

```python
sql_scripts = curxor.compile_many([
    users,
    posts
])

print(sql_scripts)
```

This returns a list of compiled SQL statements.

## 7. Executing SQL Queries

NXsql provides `curxor.execute()` to execute SQL against an SQLite database.

### Executing a Schema

```python
curxor.execute(
    file="main.db",
    schema=users
)
```

### Executing a SQL Query

```python
curxor.execute(
    file="main.db",
    sql="CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY)"
)
```

### Executing Multiple SQL Statements

```python
curxor.execute(
    file="main.db",
    scripts=[
        "CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY)",
        "CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY)"
    ]
)
```

You must provide exactly one of `sql`, `schema`, or `scripts` in an `execute()` call.

## 8. Using SQL Parameters

NXsql supports SQLite bound parameters through the `params` argument.

```python
curxor.execute(
    file="main.db",
    sql="INSERT INTO users (username, email) VALUES (?, ?)",
    params=("faizan", "faizan@example.com")
)
```

You can also use named parameters:

```python
curxor.execute(
    file="main.db",
    sql="INSERT INTO users (username, email) VALUES (:username, :email)",
    params={
        "username": "faizan",
        "email": "faizan@example.com"
    }
)
```

**Security note:** Use bound parameters for user-provided values instead of building SQL queries through string interpolation.

## 9. Fetching Query Results

`curxor.execute()` returns the result of SQLite's `cursor.execute()` when executing a single statement.

You can fetch records using normal SQLite cursor methods:

```python
result = curxor.execute(
    file="main.db",
    sql="SELECT * FROM users"
)

users = result.fetchall()

for user in users:
    print(user)
```

You can also use:

```python
result.fetchone()
result.fetchmany(5)
```

These methods work because NXsql returns ordinary SQLite cursor results.

## 10. Checking Whether a Table Exists

NXsql provides `curxor.table_exists()` to check whether a table exists in a database.

```python
exists = curxor.table_exists(
    file="main.db",
    name="users"
)

print(exists)
```

Returns:

- `True` if the table exists.
- `False` if the table does not exist.

## Summary

| Feature | NXsql API |
|---|---|
| Define a table | `Table.new()` |
| Define a column | `Column()` |
| Define CHECK constraints | `check()` |
| Define foreign keys | `references()` |
| Compile a schema | `curxor.compile()` |
| Compile multiple schemas | `curxor.compile_many()` |
| Execute SQL | `curxor.execute()` |
| Check table existence | `curxor.table_exists()` |
| Use timestamp defaults | `CURRENT_TIMESTAMP` |

**NXsql makes database schema creation and SQL execution easier while retaining compatibility with SQLite.**
# Concept 4: NXscript (.nxs) — Nexa's Native Template and Scripting Language

NXscript is Nexa.py's built-in template and scripting language, designed to make dynamic HTML rendering easier.

It allows developers to combine HTML with dynamic Python-backed expressions, loops, conditionals, and template inheritance.

NXscript templates use the `.nxs` file extension.

## 1. Understanding NXscript Syntax

NXscript currently supports several template constructs:

| Feature | Syntax |
|---|---|
| Variables | `{{ variable }}` |
| For loops | `{% for item in items %}` |
| Conditionals | `{% if condition %}` |
| Else-if | `{% elif condition %}` |
| Else | `{% else %}` |
| Template inheritance | `{% extends "base.nxs" %}` |
| Template blocks | `{% block name %}` |

Let's explore each feature.

## 2. Rendering Variables

NXscript allows you to pass Python variables into your templates using `render_template()`.

### Step 1: Create the application

Create `app.py`:

```python
from Nexa import NXserver, render_template

app = NXserver("NXscript App")

@app.get("/")
def home():
    return render_template(
        "index.nxs",
        Name="Faizan"
    )

app.run()
```

### Step 2: Create the template

Create `templates/index.nxs`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <title>NXscript Variables</title>
</head>
<body>
    <h1>Hello {{ Name }}!</h1>
</body>
</html>
```

### Expected output

```html
<h1>Hello Faizan!</h1>
```

The `{{ Name }}` expression is replaced with the value passed from Python.

## 3. Using For Loops

NXscript supports loops that allow you to dynamically generate HTML elements from Python iterables.

### Example: Displaying a List of Users

**app.py**

```python
from Nexa import NXserver, render_template

app = NXserver("NXscript App")

@app.get("/")
def home():
    users = ["Faizan", "Shrikari", "Akshaya"]

    return render_template(
        "index.nxs",
        users=users
    )

app.run()
```

**templates/index.nxs**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <title>User List</title>
</head>
<body>

    <h1>Our Users</h1>

    <ul>
        {% for user in users %}
            <li>{{ user }}</li>
        {% end for %}
    </ul>

</body>
</html>
```

### Expected output

- Faizan
- Shrikari
- Akshaya

NXscript iterates over the supplied collection and renders the loop body for every item.

### Loop Information

NXscript also provides additional loop variables:

| Variable | Description |
|---|---|
| `loop_index` | Current iteration index, starting at 0 |
| `loop_first` | `True` if this is the first iteration |
| `loop_last` | `True` if this is the last iteration |
| `loop_length` | Total number of items |

Example:

```html
{% for user in users %}
    <p>
        {{ loop_index }}: {{ user }}
    </p>
{% end for %}
```

## 4. Using Conditional Statements

NXscript supports conditional rendering using `if`, `elif`, and `else`.

### Example: Checking User Access

**app.py**

```python
from Nexa import NXserver, render_template

app = NXserver("NXscript App")

@app.get("/")
def home():
    return render_template(
        "index.nxs",
        is_admin=True
    )

app.run()
```

**templates/index.nxs**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <title>Conditional Rendering</title>
</head>
<body>

    {% if is_admin %}
        <h1>Welcome, Administrator!</h1>
    {% elif is_admin == False %}
        <h1>Welcome, User!</h1>
    {% else %}
        <h1>Access Denied!</h1>
    {% end if %}

</body>
</html>
```

NXscript evaluates the conditions and renders the matching branch.

You can also use nested conditions inside other template blocks.

## 5. Template Inheritance

NXscript supports template inheritance, allowing you to create a common layout and reuse it across multiple pages.

This is useful when building applications with shared navigation bars, headers, footers, and page layouts.

### Step 1: Create the base template

Create `templates/base.nxs`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>My Nexa Application</title>
</head>
<body>

    <header>
        <h1>My Application</h1>
    </header>

    <main>
        {% block body %}
            <p>Default page content.</p>
        {% endblock %}
    </main>

    <footer>
        <p>Powered by Nexa.py</p>
    </footer>

</body>
</html>
```

### Step 2: Create a child template

Create `templates/index.nxs`:

```html
{% extends "base.nxs" %}

{% block body %}
    <h2>Welcome to NXscript!</h2>
    <p>This content replaces the base template's body block.</p>
{% endblock %}
```

### Step 3: Render the child template

```python
from Nexa import NXserver, render_template

app = NXserver("NXscript App")

@app.get("/")
def home():
    return render_template("index.nxs")

app.run()
```

NXscript loads the parent template and replaces its matching named blocks with the content provided by the child template.

## 6. Expressions Inside Templates

NXscript supports evaluating expressions inside `{{ }}`.

For example:

```html
<h1>{{ "Hello " + Name }}</h1>

<p>{{ 10 + 20 }}</p>

<p>{{ len(users) }}</p>
```

The evaluator provides a restricted set of built-in functions, including:

- `str()`
- `int()`
- `float()`
- `bool()`
- `len()`
- `range()`
- `list()`
- `dict()`
- `enumerate()`
- `zip()`
- `min()`
- `max()`
- `sum()`
- `sorted()`

It also supports common Python expressions and operations.

## 7. Browser-Synchronized Variables (Experimental)

NXscript includes a variable declaration system designed for browser-synchronized state.

The declaration syntax is:

```text
{@variable_name Type}
    ...
{% end var %}
```

The implementation includes session state management through `SessionState`.

It provides methods such as:

- `set()` — Set a variable.
- `get()` — Retrieve a variable.
- `get_type()` — Retrieve its declared type.
- `to_dict()` — Export variables.
- `from_dict()` — Update variables from browser-provided data.

Supported type conversions currently include:

- `int`
- `float`
- `bool`
- `list`

**Note:** Browser synchronization is an experimental part of NXscript. The current rendering implementation does not yet demonstrate a complete browser-to-server synchronization workflow.

## 8. HTML Output and Form Integration

NXscript also contains formatting support for objects that expose methods such as:

- `as_p()`
- `as_table()`
- `as_ul()`
- `hidden_tag()`
- `render()`

This allows compatible form objects and fields to be rendered directly through template variables.

Example:

```html
<form method="POST">
    {{ form.as_p() }}
    <button type="submit">Submit</button>
</form>
```

The actual output depends on the object passed to the template.

## 9. Error Handling

NXscript provides template-related exceptions through Nexa's template system:

- `TemplateError`
- `TemplateSyntaxError`
- `TemplateRenderError`
- `TemplateNotFound`

These help identify issues such as missing templates, invalid expressions, and unclosed template blocks.

## 10. Project Structure

A typical NXscript application can use the following structure:

```text
MyApp/
│
├── app.py
│
└── templates/
    ├── base.nxs
    ├── index.nxs
    └── users.nxs
```

## Summary

| Feature | NXscript Syntax / API |
|---|---|
| Render a template | `render_template()` |
| Display variables | `{{ variable }}` |
| Iterate over data | `{% for ... %}` |
| Conditional rendering | `{% if ... %}` |
| Alternative conditions | `{% elif ... %}` |
| Default branch | `{% else %}` |
| Extend a template | `{% extends "base.nxs" %}` |
| Define a block | `{% block name %}` |
| End a block | `{% endblock %}` |
| Browser-synchronized declarations | `{@name Type}` |

**NXscript brings dynamic template rendering, control structures, and reusable layouts into Nexa.py, allowing developers to build dynamic web pages using Python and HTML together.**
