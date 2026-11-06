# Nexa Framework: Implement NXscript and Nforms

You are working on my existing Python web framework, **Nexa**. Your task is to implement and integrate two major systems:

1. **NXscript** — Nexa's own template and scripting language.
2. **Nforms** — Nexa's own class-based form-handling system.

These must be native Nexa components, not wrappers around Django, Flask, Jinja2, or WTForms.

## 1. Important development rules

Before writing code:

- Inspect the entire existing Nexa project.
- Understand its architecture, request handling, response system, routing, template loader, and current `render_template()` implementation.
- Inspect the existing NXscript parser and syntax.
- Reuse existing functionality wherever possible.
- Do not unnecessarily rewrite working modules.
- Do not introduce unnecessary dependencies.
- Preserve backward compatibility.
- Follow the existing naming conventions and folder structure.
- Do not create duplicate implementations of existing functionality.

Do not assume that an existing feature works just because it exists. Test it.

---

# PART A — NXscript

## 2. NXscript architecture

NXscript is Nexa's own template/scripting language.

It must support Python integration, template variables, loops, conditional statements, variable declarations, and browser interaction.

It must have its own parser and rendering engine.

Do not replace NXscript with Jinja2.

## 3. Template variables

Support Python variables passed through `render_template()`.

Python:

```python
return render_template(
    "index.html",
    name="Faizan",
    age=16,
    numbers=range(1, 10)
)
```

NXscript:

```html
<h1>Hello {{name}}</h1>
<p>Age: {{age}}</p>
```

Support strings, integers, floats, booleans, lists, tuples, dictionaries, ranges, and other safe iterable objects.

## 4. Loops

Implement the following syntax:

```html
{%for i in {{numbers}} %}
    <p>{{i}}</p>
{%end for%}
```

Requirements:

- Support iterating over Python-provided iterables.
- Support nested loops.
- Support loop variables.
- Handle empty iterables.
- Prevent infinite loops where possible.
- Provide meaningful template errors.

## 5. Conditional statements

Implement:

```html
{%if age >= 18%}
    <p>Adult</p>
{%elif age >= 13%}
    <p>Teenager</p>
{%else%}
    <p>Child</p>
{%end if%}
```

Support:
- `if`
- `elif`
- `else`
- `end if`
- Comparisons
- Boolean expressions
- Nested conditions

Use a safe expression evaluator. Do not expose unrestricted Python `eval()`.

## 6. Template inheritance

Implement:

```html
{%extends "base.html"%}

{%block body%}
    <h1>Hello {{name}}</h1>
{%end block%}
```

Base template:

```html
<html>
    <head>
        <title>{{title}}</title>
    </head>

    <body>
        {%block body%}
        {%end block%}
    </body>
</html>
```

Requirements:
- Template inheritance.
- Multiple blocks.
- Block overriding.
- Nested inheritance if feasible.
- Proper missing-template errors.
- Circular inheritance protection.

## 7. NXscript variables and browser synchronization

Implement NXscript variable declarations.

Example:

```html
{@username Input}
    <input type="text" id="username">
{end var}
```

This declares a Python-backed variable named `username`.

Python:

```python
@app.get("/")
async def index():
    return await render_template(
        "index.html",
        username="Guest"
    )
```

Expected behaviour:

1. Python initializes the variable.
2. NXscript binds it to the declared input.
3. The browser receives the initial value.
4. The user changes the input.
5. The browser sends the updated value to Nexa.
6. Nexa updates the corresponding state.
7. Python can retrieve the updated value.
8. The browser can receive updated values when Python changes the state.

Implement a dedicated state-management mechanism.

Requirements:
- Session-scoped variables by default.
- Never share one user's state with another user's session.
- Validate incoming browser updates.
- Protect against unauthorized modifications.
- Avoid arbitrary Python execution through browser input.
- Support multiple variable types.
- Avoid unnecessary requests.
- Consider WebSockets for real-time synchronization, but provide a reasonable HTTP fallback.

Do not claim that browser synchronization works until it is implemented and tested.

---

# PART B — Nforms

## 8. Nforms architecture

Implement a native class-based form system inspired by Django Forms and WTForms.

It must be accessible through:

```python
from Nexa import Nforms
```

The following API is the desired public interface:

```python
from Nexa import Nforms

class RegisterForm(Nforms.Form):

    username = Nforms.CharField(
        max_length=50
    )

    email = Nforms.EmailField()

    password = Nforms.CharField(
        widget=Nforms.PasswordInput
    )

    age = Nforms.IntegerField(
        min_value=13
    )
```

This API is a design requirement. Implement the underlying classes and field collection system to support it.

## 9. Form fields

Implement at least:

- `CharField`
- `EmailField`
- `IntegerField`
- `FloatField`
- `BooleanField`
- `DateField`
- `DateTimeField`
- `ChoiceField`
- `MultipleChoiceField`
- `PasswordField`

Each field should support appropriate options, such as:

- `required`
- `default`
- `initial`
- `min_length`
- `max_length`
- `min_value`
- `max_value`
- `choices`
- `widget`
- `validators`
- `label`
- `help_text`

Only expose options that make sense for each field.

## 10. Widgets

Separate fields from widgets.

Implement:

- `TextInput`
- `EmailInput`
- `PasswordInput`
- `NumberInput`
- `CheckboxInput`
- `DateInput`
- `Select`
- `Textarea`
- `HiddenInput`

Example:

```python
password = Nforms.CharField(
    widget=Nforms.PasswordInput
)
```

Widgets must generate safe HTML.

Escape user-provided values and attributes to prevent HTML injection.

## 11. Form class

Implement:

```python
class RegisterForm(Nforms.Form):
    username = Nforms.CharField()
    email = Nforms.EmailField()
```

The base `Form` must:

- Collect declared fields from the class.
- Preserve field declaration order.
- Support inherited form classes.
- Bind submitted request data.
- Keep initial and submitted values separate.
- Validate submitted data.
- Convert values into their correct Python types.
- Collect field-specific errors.
- Expose cleaned data.

Expected interface:

```python
form = RegisterForm()

form.fields
form.is_valid()
form.cleaned_data
form.errors
form.username
```

Support form instances initialized with submitted data.

For example:

```python
form = RegisterForm(data=request.form)
```

If the existing Nexa request object uses a different interface, adapt the implementation to it rather than changing the entire request system.

## 12. Validation

Implement:

- Required-field validation.
- Email validation.
- Minimum and maximum lengths.
- Minimum and maximum numerical values.
- Choice validation.
- Type conversion.
- Custom validators.
- Multiple validation errors per form.

Example:

```python
class RegisterForm(Nforms.Form):

    username = Nforms.CharField(
        required=True,
        min_length=3,
        max_length=50
    )

    age = Nforms.IntegerField(
        min_value=13,
        max_value=120
    )
```

Support custom validation methods:

```python
class RegisterForm(Nforms.Form):

    username = Nforms.CharField()

    def clean_username(self, value):
        if value.lower() == "admin":
            raise Nforms.ValidationError(
                "This username is reserved."
            )

        return value
```

---

# PART C — NXscript + Nforms integration

## 13. Rendering forms inside NXscript

Forms must integrate with the NXscript renderer.

Python:

```python
from Nexa import Nforms, render_template

class RegisterForm(Nforms.Form):

    username = Nforms.CharField(max_length=50)
    email = Nforms.EmailField()
    password = Nforms.CharField(
        widget=Nforms.PasswordInput
    )

@app.get("/register")
async def register():
    form = RegisterForm()

    return await render_template(
        "register.html",
        form=form
    )
```

NXscript:

```html
<form method="POST">

    {{form.hidden_tag()}}

    {{form.username.label}}
    {{form.username}}

    {{form.email.label}}
    {{form.email}}

    {{form.password.label}}
    {{form.password}}

    <button type="submit">Register</button>

</form>
```

Also support a convenient form-rendering method, such as:

```html
{{form.as_p()}}
```

And:

```html
{{form.as_table()}}
```

These must use the native Nforms renderer.

## 14. Request handling

Support GET and POST form submissions.

Example:

```python
@app.get("/register")
async def register():
    return await render_template(
        "register.html",
        form=RegisterForm()
    )


@app.post("/register")
async def register_post(request):
    form = RegisterForm(data=request.form)

    if form.is_valid():
        username = form.cleaned_data["username"]
        email = form.cleaned_data["email"]

        return "Registration successful"

    return await render_template(
        "register.html",
        form=form
    )
```

Adapt this example to Nexa's actual request and response APIs.

Implement CSRF protection if Nexa does not already provide it.

---

# PART D — Integration and compatibility

## 15. Public imports

The final framework should expose:

```python
from Nexa import Nserver
from Nexa import render_template
from Nexa import Nforms
```

The user should be able to access all fields and widgets through `Nforms`.

Keep the existing Nexa import conventions intact.

## 16. Asynchronous support

Nexa supports asynchronous routes.

Ensure:

- Async routes work.
- Async template rendering works where supported.
- Form validation does not unnecessarily block the event loop.
- Async state synchronization is handled correctly.
- Do not call `asyncio.run()` inside an already running event loop.
- Do not make every operation asynchronous without a reason.

Use Nexa's existing server execution model.

---

# PART E — Security and testing

## 17. Security

Implement:

- Safe template expression evaluation.
- HTML escaping.
- Path traversal protection.
- CSRF protection for forms.
- Session isolation.
- Input validation.
- Safe handling of user-submitted values.
- Protection against arbitrary Python execution.
- Safe widget rendering.

Do not trust browser-provided values.

## 18. Testing

Create tests for both systems.

NXscript tests:
- Variable rendering.
- Nested loops.
- Conditionals.
- Template inheritance.
- Missing variables.
- Invalid syntax.
- Template errors.
- Browser variable updates.
- Session isolation.

Nforms tests:
- Field collection.
- Inherited fields.
- Valid submissions.
- Invalid submissions.
- Type conversion.
- Custom validators.
- Widget rendering.
- HTML escaping.
- CSRF validation.
- NXscript integration.

Run the tests and fix failures.

---

# PART F — Final deliverables

When finished:

1. Show the exact files created and modified.
2. Explain the architecture.
3. Provide complete working examples.
4. Provide the exact import statements.
5. Explain how to use NXscript.
6. Explain how to use Nforms.
7. Demonstrate a working registration form.
8. Report which tests passed and which failed.
9. Identify any features that remain incomplete.

## CRITICAL RULES

- Do not implement fake functionality.
- Do not create placeholder methods that silently return success.
- Do not replace NXscript with Jinja2.
- Do not replace Nforms with Django or WTForms.
- Do not break existing Nexa functionality.
- Do not invent APIs that conflict with existing Nexa architecture.
- Do not silently change my syntax.
- Inspect before modifying.
- Implement incrementally and test after each major component.

The goal is to make NXscript and Nforms first-class native components of the Nexa ecosystem.