"""
Nforms — Nexa's native class-based form-handling system.

Inspired by Django Forms and WTForms, but fully native to Nexa.

Supports:
- Field types: CharField, EmailField, IntegerField, FloatField, etc.
- Widgets: TextInput, EmailInput, PasswordInput, Select, etc.
- Validation: required, min/max length, min/max value, email format, choices
- Custom validators
- CSRF protection
- Form rendering in NXscript templates
"""

from __future__ import annotations

import re
from html import escape
from typing import Any, Callable, Optional, Union


# ---------------------------------------------------------------------------
# ValidationError
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    """Raised when a field fails validation."""

    def __init__(self, message: str = "", code: str = None):
        self.message = message
        self.code = code or "invalid"
        super().__init__(message)


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

class Validator:
    """Base class for validators."""

    def __call__(self, value: Any) -> Any:
        """Validate and return the value (or raise ValidationError)."""
        return value


class RequiredValidator(Validator):
    """Validate that a field is not empty."""

    def __init__(self, message: str = None):
        self.message = message or "This field is required."

    def __call__(self, value: Any) -> Any:
        if value is None:
            raise ValidationError(self.message)
        if isinstance(value, str) and not value.strip():
            raise ValidationError(self.message)
        if isinstance(value, (list, dict, tuple)) and len(value) == 0:
            raise ValidationError(self.message)
        return value


class MinLengthValidator(Validator):
    """Validate minimum string length."""

    def __init__(self, min_length: int, message: str = None):
        self.min_length = min_length
        self.message = message or f"Ensure this value has at least {min_length} characters."

    def __call__(self, value: Any) -> Any:
        if value is None:
            return value
        value = str(value)
        if len(value) < self.min_length:
            raise ValidationError(self.message)
        return value


class MaxLengthValidator(Validator):
    """Validate maximum string length."""

    def __init__(self, max_length: int, message: str = None):
        self.max_length = max_length
        self.message = message or f"Ensure this value has at most {max_length} characters."

    def __call__(self, value: Any) -> Any:
        if value is None:
            return value
        value = str(value)
        if len(value) > self.max_length:
            raise ValidationError(self.message)
        return value


class MinValueValidator(Validator):
    """Validate minimum numeric value."""

    def __init__(self, min_value: Union[int, float], message: str = None):
        self.min_value = min_value
        self.message = message or f"Ensure this value is at least {min_value}."

    def __call__(self, value: Any) -> Any:
        if value is None:
            return value
        try:
            num_value = float(value)
        except (ValueError, TypeError):
            raise ValidationError("Enter a valid number.")
        if num_value < self.min_value:
            raise ValidationError(self.message)
        return value


class MaxValueValidator(Validator):
    """Validate maximum numeric value."""

    def __init__(self, max_value: Union[int, float], message: str = None):
        self.max_value = max_value
        self.message = message or f"Ensure this value is at most {max_value}."

    def __call__(self, value: Any) -> Any:
        if value is None:
            return value
        try:
            num_value = float(value)
        except (ValueError, TypeError):
            raise ValidationError("Enter a valid number.")
        if num_value > self.max_value:
            raise ValidationError(self.message)
        return value


class EmailValidator(Validator):
    """Validate email format."""

    EMAIL_REGEX = re.compile(
        r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    )

    def __init__(self, message: str = None):
        self.message = message or "Enter a valid email address."

    def __call__(self, value: Any) -> Any:
        if value is None:
            return value
        value = str(value).strip()
        if not self.EMAIL_REGEX.match(value):
            raise ValidationError(self.message)
        return value


class ChoiceValidator(Validator):
    """Validate that value is in the allowed choices."""

    def __init__(self, choices: list, message: str = None):
        self.choices = choices
        self.message = message or "Select a valid choice."

    def __call__(self, value: Any) -> Any:
        if value is None:
            return value
        if value not in self.choices:
            raise ValidationError(self.message)
        return value


class RegexValidator(Validator):
    """Validate against a regex pattern."""

    def __init__(self, regex: str, message: str = None, flags: int = 0):
        self.regex = re.compile(regex, flags)
        self.message = message or "Invalid format."

    def __call__(self, value: Any) -> Any:
        if value is None:
            return value
        value = str(value)
        if not self.regex.match(value):
            raise ValidationError(self.message)
        return value


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class Widget:
    """Base widget class."""

    def __init__(self, attrs: dict = None):
        self.attrs = attrs or {}

    def render(self, name: str, value: Any = None, errors: list = None) -> str:
        """Render the widget as HTML."""
        raise NotImplementedError


class InputWidget(Widget):
    """Base class for input widgets."""

    input_type: str = "text"

    def render(self, name: str, value: Any = None, errors: list = None) -> str:
        attrs = self._build_attrs(name, value, errors)
        escaped_attrs = " ".join(
            f'{key}="{escape(str(val), quote=True)}"'
            for key, val in attrs.items()
        )
        return f'<input type="{self.input_type}" name="{escape(name, quote=True)}" {escaped_attrs}>'

    def _build_attrs(self, name: str, value: Any, errors: list) -> dict:
        attrs = dict(self.attrs)
        # Don't add name if it's already in attrs
        if "name" not in attrs:
            attrs["name"] = name
        if value is not None and value != "":
            # Don't escape here - will be escaped in render()
            attrs["value"] = str(value)
        if errors:
            current_class = attrs.get("class", "")
            if current_class:
                attrs["class"] = current_class + " is-invalid"
            else:
                attrs["class"] = "is-invalid"
        return attrs


class TextInput(InputWidget):
    """Text input widget."""

    input_type = "text"


class EmailInput(InputWidget):
    """Email input widget."""

    input_type = "email"


class PasswordInput(InputWidget):
    """Password input widget (no value shown)."""

    input_type = "password"

    def _build_attrs(self, name: str, value: Any, errors: list) -> dict:
        attrs = dict(self.attrs)
        attrs["name"] = name
        # Never show password value
        if errors:
            attrs["class"] = attrs.get("class", "") + " is-invalid"
        return attrs


class NumberInput(InputWidget):
    """Number input widget."""

    input_type = "number"


class CheckboxInput(Widget):
    """Checkbox input widget."""

    def render(self, name: str, value: Any = None, errors: list = None) -> str:
        checked = ""
        if value:
            checked = ' checked="checked"'
        attrs = self.attrs.copy()
        attrs["name"] = name
        attrs["type"] = "checkbox"
        if errors:
            attrs["class"] = attrs.get("class", "") + " is-invalid"
        escaped_attrs = " ".join(
            f'{key}="{escape(str(val), quote=True)}"'
            for key, val in attrs.items()
        )
        return f'<input type="checkbox" name="{escape(name, quote=True)}" {escaped_attrs}{checked}>'


class Textarea(Widget):
    """Textarea widget."""

    def __init__(self, attrs: dict = None, rows: int = 4):
        super().__init__(attrs)
        self.rows = rows

    def render(self, name: str, value: Any = None, errors: list = None) -> str:
        attrs = dict(self.attrs)
        # Don't add name if it's already in attrs
        if "name" not in attrs:
            attrs["name"] = name
        attrs["rows"] = str(self.rows)
        if errors:
            current_class = attrs.get("class", "")
            if current_class:
                attrs["class"] = current_class + " is-invalid"
            else:
                attrs["class"] = "is-invalid"
        escaped_attrs = " ".join(
            f'{key}="{escape(str(val), quote=True)}"'
            for key, val in attrs.items()
        )
        escaped_value = escape_html(str(value) if value else "")
        return f'<textarea name="{escape(name, quote=True)}" {escaped_attrs}>{escaped_value}</textarea>'


class Select(Widget):
    """Select dropdown widget."""

    def __init__(self, attrs: dict = None, choices: list = None):
        super().__init__(attrs)
        self.choices = choices or []

    def render(self, name: str, value: Any = None, errors: list = None) -> str:
        attrs = dict(self.attrs)
        # Don't add name if it's already in attrs
        if "name" not in attrs:
            attrs["name"] = name
        if errors:
            current_class = attrs.get("class", "")
            if current_class:
                attrs["class"] = current_class + " is-invalid"
            else:
                attrs["class"] = "is-invalid"
        escaped_attrs = " ".join(
            f'{key}="{escape(str(val), quote=True)}"'
            for key, val in attrs.items()
        )

        options = []
        for choice_value, choice_label in self.choices:
            selected = ""
            if str(value) == str(choice_value):
                selected = ' selected="selected"'
            options.append(
                f'<option value="{escape(str(choice_value), quote=True)}"{selected}>'
                f'{escape_html(choice_label)}</option>'
            )

        return (
            f'<select name="{escape(name, quote=True)}" {escaped_attrs}>'
            f'{"".join(options)}'
            f"</select>"
        )


class HiddenInput(InputWidget):
    """Hidden input widget."""

    input_type = "hidden"

    def render(self, name: str, value: Any = None, errors: list = None) -> str:
        attrs = self._build_attrs(name, value, errors)
        escaped_attrs = " ".join(
            f'{key}="{escape(str(val), quote=True)}"'
            for key, val in attrs.items()
        )
        return f'<input type="hidden" name="{escape(name, quote=True)}" {escaped_attrs}>'


# ---------------------------------------------------------------------------
# HTML escaping helper
# ---------------------------------------------------------------------------

def escape_html(text: Any) -> str:
    """Escape text for safe HTML output."""
    if text is None:
        return ""
    return escape(str(text), quote=True)


# ---------------------------------------------------------------------------
# Field classes
# ---------------------------------------------------------------------------

class Field:
    """Base field class."""

    widget = TextInput

    def __init__(
        self,
        required: bool = True,
        default: Any = None,
        initial: Any = None,
        label: str = None,
        help_text: str = None,
        validators: list = None,
        widget: Widget = None,
        **kwargs
    ):
        self.required = required
        self.default = default
        self.initial = initial
        self.label = label or ""
        self.help_text = help_text or ""
        self.validators = validators or []
        self.widget = widget or self.widget()
        self.errors: list[str] = []
        self.cleaned_value: Any = None

    def clean(self, value: Any) -> Any:
        """Clean and validate the value."""
        self.errors = []

        # Check required
        if self.required:
            for validator in self.validators:
                if isinstance(validator, RequiredValidator):
                    try:
                        value = validator(value)
                    except ValidationError as exc:
                        self.errors.append(exc.message)
                        return None

        # Skip further validation if value is None/empty and not required
        if value is None or (isinstance(value, str) and not value.strip()):
            if self.required:
                self.errors.append("This field is required.")
            return None

        # Run custom validators
        for validator in self.validators:
            try:
                value = validator(value)
            except ValidationError as exc:
                self.errors.append(exc.message)

        return value

    def render(self, name: str, value: Any = None) -> str:
        """Render the field's widget."""
        return self.widget.render(name, value, self.errors)

    def render_label(self, name: str) -> str:
        """Render the field's label."""
        if not self.label:
            return ""
        return f'<label for="{escape(name, quote=True)}">{escape_html(self.label)}</label>'

    def render_with_errors(self, name: str, value: Any = None) -> str:
        """Render the field with its errors."""
        html = self.render_label(name)
        html += self.render(name, value)
        if self.errors:
            html += '<div class="errors">' + "".join(
                f'<span class="error">{escape_html(err)}</span>'
                for err in self.errors
            ) + "</div>"
        if self.help_text:
            html += f'<small class="help-text">{escape_html(self.help_text)}</small>'
        return html


class CharField(Field):
    """Character field."""

    widget = TextInput

    def __init__(
        self,
        max_length: int = None,
        min_length: int = None,
        **kwargs
    ):
        validators = list(kwargs.pop("validators", []))
        if min_length is not None:
            validators.append(MinLengthValidator(min_length))
        if max_length is not None:
            validators.append(MaxLengthValidator(max_length))
        super().__init__(validators=validators, **kwargs)

    def clean(self, value: Any) -> Any:
        value = super().clean(value)
        if value is not None:
            value = str(value)
        return value


class EmailField(CharField):
    """Email field with format validation."""

    widget = EmailInput

    def __init__(self, **kwargs):
        validators = list(kwargs.pop("validators", []))
        validators.append(EmailValidator())
        super().__init__(validators=validators, **kwargs)


class IntegerField(Field):
    """Integer field with numeric validation."""

    widget = NumberInput

    def __init__(
        self,
        min_value: int = None,
        max_value: int = None,
        **kwargs
    ):
        validators = list(kwargs.pop("validators", []))
        if min_value is not None:
            validators.append(MinValueValidator(min_value))
        if max_value is not None:
            validators.append(MaxValueValidator(max_value))
        super().__init__(validators=validators, **kwargs)

    def clean(self, value: Any) -> Any:
        value = super().clean(value)
        if value is not None:
            try:
                value = int(value)
            except (ValueError, TypeError):
                self.errors.append("Enter a valid integer.")
                return None
        return value


class FloatField(Field):
    """Float field with numeric validation."""

    widget = NumberInput

    def __init__(
        self,
        min_value: float = None,
        max_value: float = None,
        **kwargs
    ):
        validators = list(kwargs.pop("validators", []))
        if min_value is not None:
            validators.append(MinValueValidator(min_value))
        if max_value is not None:
            validators.append(MaxValueValidator(max_value))
        super().__init__(validators=validators, **kwargs)

    def clean(self, value: Any) -> Any:
        value = super().clean(value)
        if value is not None:
            try:
                value = float(value)
            except (ValueError, TypeError):
                self.errors.append("Enter a valid number.")
                return None
        return value


class BooleanField(Field):
    """Boolean field."""

    widget = CheckboxInput

    def __init__(self, **kwargs):
        kwargs["required"] = False
        super().__init__(**kwargs)

    def clean(self, value: Any) -> Any:
        if value in (True, "true", "1", 1, "yes"):
            return True
        return False


class DateField(Field):
    """Date field (YYYY-MM-DD format)."""

    widget = TextInput

    DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    def __init__(self, **kwargs):
        validators = list(kwargs.pop("validators", []))
        validators.append(RegexValidator(r"^\d{4}-\d{2}-\d{2}$", "Enter a valid date (YYYY-MM-DD)."))
        super().__init__(validators=validators, **kwargs)

    def clean(self, value: Any) -> Any:
        value = super().clean(value)
        if value is not None:
            value = str(value)
            if not self.DATE_REGEX.match(value):
                self.errors.append("Enter a valid date (YYYY-MM-DD).")
                return None
        return value


class DateTimeField(Field):
    """DateTime field (YYYY-MM-DD HH:MM:SS format)."""

    widget = TextInput

    DATETIME_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}$")

    def __init__(self, **kwargs):
        validators = list(kwargs.pop("validators", []))
        validators.append(
            RegexValidator(
                r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}$",
                "Enter a valid date and time (YYYY-MM-DD HH:MM:SS)."
            )
        )
        super().__init__(validators=validators, **kwargs)

    def clean(self, value: Any) -> Any:
        value = super().clean(value)
        if value is not None:
            value = str(value)
            if not self.DATETIME_REGEX.match(value):
                self.errors.append("Enter a valid date and time (YYYY-MM-DD HH:MM:SS).")
                return None
        return value


class ChoiceField(Field):
    """Choice field with dropdown."""

    widget = Select

    def __init__(
        self,
        choices: list = None,
        **kwargs
    ):
        if choices is None:
            choices = []
        self.choices = choices
        widget = kwargs.pop("widget", Select(choices=choices))
        kwargs["widget"] = widget
        validators = list(kwargs.pop("validators", []))
        validators.append(ChoiceValidator(choices))
        super().__init__(validators=validators, **kwargs)

    def clean(self, value: Any) -> Any:
        value = super().clean(value)
        if value is not None:
            # Return the actual choice value, not the label
            for choice_value, choice_label in self.choices:
                if str(value) == str(choice_value):
                    return choice_value
        return value


class MultipleChoiceField(ChoiceField):
    """Multiple choice field (checkboxes or multi-select)."""

    def __init__(self, choices: list = None, **kwargs):
        super().__init__(choices=choices, **kwargs)

    def clean(self, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            # Comma-separated values
            values = [v.strip() for v in value.split(",") if v.strip()]
        elif isinstance(value, (list, tuple)):
            values = list(value)
        else:
            values = [str(value)]

        cleaned = []
        for v in values:
            if v not in self.choices:
                self.errors.append(f"Select a valid choice. {v} is not a valid choice.")
            else:
                for choice_value, choice_label in self.choices:
                    if str(v) == str(choice_value):
                        cleaned.append(choice_value)
                        break

        return cleaned if cleaned else None


class PasswordField(CharField):
    """Password field."""

    widget = PasswordInput


# ---------------------------------------------------------------------------
# CSRF Protection
# ---------------------------------------------------------------------------

class CSRFToken:
    """Generate and validate CSRF tokens."""

    _tokens: dict[str, str] = {}
    _token_counter = 0

    @classmethod
    def generate(cls, session_id: str) -> str:
        """Generate a CSRF token for a session."""
        cls._token_counter += 1
        token = f"csrf_{session_id}_{cls._token_counter}_{id(cls)}"
        cls._tokens[session_id] = token
        return token

    @classmethod
    def validate(cls, session_id: str, token: str) -> bool:
        """Validate a CSRF token."""
        expected = cls._tokens.get(session_id)
        if expected is None:
            return False
        return token == expected

    @classmethod
    def clear(cls, session_id: str) -> None:
        """Clear tokens for a session."""
        cls._tokens.pop(session_id, None)


# ---------------------------------------------------------------------------
# Form class
# ---------------------------------------------------------------------------

class Form:
    """
    Base form class.

    Subclass this and declare fields as class attributes:

        class RegisterForm(Form):
            username = CharField(max_length=50)
            email = EmailField()
    """

    _field_class_cache: dict = {}

    def __init__(self, data: dict = None, files: dict = None, initial: dict = None):
        """
        Initialize the form.

        Args:
            data: Submitted form data (e.g., request.form).
            files: Submitted files (e.g., request.files).
            initial: Initial values for unbound form.
        """
        self.data = data or {}
        self.files = files or {}
        self.initial = initial or {}
        self._fields: list[str] = []
        self._field_instances: dict[str, Field] = {}
        self._errors: dict[str, list[str]] = {}
        self._cleaned_data: dict[str, Any] = {}
        self._is_bound = data is not None

        self._collect_fields()

    def _collect_fields(self):
        """Collect declared fields from the class hierarchy."""
        # Walk the MRO to collect fields in declaration order
        seen = set()
        for klass in reversed(self.__class__.__mro__):
            for name, value in klass.__dict__.items():
                if name.startswith("_") or name in seen:
                    continue
                if isinstance(value, Field):
                    seen.add(name)
                    self._fields.append(name)

        # Create field instances
        for name in self._fields:
            field_cls = type(self)._get_field_declaration(name)
            if field_cls is None:
                continue

            # Copy the field to avoid sharing between instances
            field = field_cls.__class__(
                required=field_cls.required,
                default=field_cls.default,
                initial=field_cls.initial,
                label=field_cls.label,
                help_text=field_cls.help_text,
                validators=list(field_cls.validators),
                widget=field_cls.widget,
            )

            # Set initial value
            if name in self.initial:
                field.initial = self.initial[name]
            elif field_cls.initial is not None:
                field.initial = field_cls.initial

            self._field_instances[name] = field

    @classmethod
    def _get_field_declaration(cls, name: str) -> Optional[Field]:
        """Get the field declaration for a name from the class hierarchy."""
        for klass in cls.__mro__:
            if name in klass.__dict__:
                field = klass.__dict__[name]
                if isinstance(field, Field):
                    return field
        return None

    @property
    def fields(self) -> list[str]:
        """Return field names in declaration order."""
        return list(self._fields)

    def __getattr__(self, name: str) -> Optional[Field]:
        """Access field instances as attributes."""
        if name in self._field_instances:
            return self._field_instances[name]
        raise AttributeError(f"'{type(self).__name__}' has no field '{name}'")

    def is_valid(self) -> bool:
        """Validate the form and return True if valid."""
        if not self._is_bound:
            # Unbound forms have no data to validate, so they're not valid
            self._errors = {}
            self._cleaned_data = {}
            return False

        self._errors = {}
        self._cleaned_data = {}

        for name in self._fields:
            field = self._field_instances[name]
            value = self.data.get(name)

            # Use initial value if no data provided
            if value is None and field.initial is not None:
                value = field.initial

            # Clean the field value
            cleaned = field.clean(value)
            
            if field.errors:
                self._errors[name] = list(field.errors)
            else:
                # Call custom clean_<fieldname> method if it exists
                clean_method = getattr(self, f'clean_{name}', None)
                if clean_method is not None and callable(clean_method):
                    try:
                        cleaned = clean_method(cleaned)
                    except ValidationError as exc:
                        if name not in self._errors:
                            self._errors[name] = []
                        self._errors[name].append(exc.message)
                        continue
                
                self._cleaned_data[name] = cleaned

        return len(self._errors) == 0

    @property
    def errors(self) -> dict[str, list[str]]:
        """Return form errors."""
        if not self._is_bound:
            self.is_valid()
        return dict(self._errors)

    @property
    def cleaned_data(self) -> dict[str, Any]:
        """Return cleaned/validated data."""
        if not self._is_bound:
            self.is_valid()
        return dict(self._cleaned_data)

    def get_error(self, field_name: str) -> Optional[str]:
        """Get the first error for a field."""
        errors = self._errors.get(field_name, [])
        return errors[0] if errors else None

    def as_p(self) -> str:
        """Render the form as paragraphs."""
        html = []
        for name in self._fields:
            field = self._field_instances[name]
            # Get the value from cleaned_data or initial or data
            value = self._cleaned_data.get(name)
            if value is None:
                value = self.data.get(name)
            if value is None:
                value = field.initial
            html.append(f'<p>{field.render_with_errors(name, value)}</p>')
        if self._errors and any(self._errors.values()):
            html.append('<div class="form-errors">')
            html.append('<h3>Form errors</h3>')
            for field_name, errors in self._errors.items():
                for error in errors:
                    html.append(f'<p class="error">{escape_html(error)}</p>')
            html.append('</div>')
        return "".join(html)

    def as_table(self) -> str:
        """Render the form as a table."""
        html = ['<table>']
        for name in self._fields:
            field = self._field_instances[name]
            # Get the value
            value = self._cleaned_data.get(name)
            if value is None:
                value = self.data.get(name)
            if value is None:
                value = field.initial
            html.append('<tr>')
            if field.label:
                html.append(f'<th>{field.render_label(name)}</th>')
            html.append(f'<td>{field.render(name, value)}</td>')
            html.append('</tr>')
        html.append('</table>')
        return "".join(html)

    def as_ul(self) -> str:
        """Render the form as a list."""
        html = ['<ul>']
        for name in self._fields:
            field = self._field_instances[name]
            # Get the value
            value = self._cleaned_data.get(name)
            if value is None:
                value = self.data.get(name)
            if value is None:
                value = field.initial
            html.append('<li>')
            html.append(field.render_with_errors(name, value))
            html.append('</li>')
        html.append('</ul>')
        return "".join(html)

    def hidden_tag(self, csrf_token: str = None) -> str:
        """Render hidden fields including CSRF token."""
        html = []
        # Add CSRF token if provided
        if csrf_token:
            html.append(
                f'<input type="hidden" name="csrf_token" value="{escape_html(csrf_token)}">'
            )
        # Add hidden inputs for fields
        for name in self._fields:
            field = self._field_instances[name]
            if isinstance(field.widget, HiddenInput):
                html.append(field.render(name))
        return "".join(html)

    def __str__(self) -> str:
        """Default string representation."""
        if self._is_bound:
            if self.is_valid():
                return "Valid form"
            return "Invalid form"
        return "Unbound form"


# ---------------------------------------------------------------------------
# Form construction helpers
# ---------------------------------------------------------------------------

def form_for_data(data: dict) -> Form:
    """Create a form bound to the given data."""
    return Form(data=data)


def validate_csrf(session_id: str, token: str) -> bool:
    """Validate a CSRF token for a session."""
    return CSRFToken.validate(session_id, token)


def get_csrf_token(session_id: str) -> str:
    """Get or generate a CSRF token for a session."""
    if session_id not in CSRFToken._tokens:
        CSRFToken.generate(session_id)
    return CSRFToken._tokens[session_id]


# ---------------------------------------------------------------------------
# Export all public names
# ---------------------------------------------------------------------------

__all__ = [
    # Exceptions
    "ValidationError",

    # Validators
    "Validator",
    "RequiredValidator",
    "MinLengthValidator",
    "MaxLengthValidator",
    "MinValueValidator",
    "MaxValueValidator",
    "EmailValidator",
    "ChoiceValidator",
    "RegexValidator",

    # Widgets
    "Widget",
    "InputWidget",
    "TextInput",
    "EmailInput",
    "PasswordInput",
    "NumberInput",
    "CheckboxInput",
    "Textarea",
    "Select",
    "HiddenInput",

    # Fields
    "Field",
    "CharField",
    "EmailField",
    "IntegerField",
    "FloatField",
    "BooleanField",
    "DateField",
    "DateTimeField",
    "ChoiceField",
    "MultipleChoiceField",
    "PasswordField",

    # Form
    "Form",
    "CSRFToken",
]
