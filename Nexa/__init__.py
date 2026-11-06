
try:
    from .nexa import app
except ImportError:
    app = None  # typer not installed
from .nx import App, Element, Fragment
from .nserver import Nserver, jsonify , render_template
from .blueprint import Blueprint
from .nforms import (
    Form,
    ValidationError,
    CharField,
    EmailField,
    IntegerField,
    FloatField,
    BooleanField,
    DateField,
    DateTimeField,
    ChoiceField,
    MultipleChoiceField,
    PasswordField,
    TextInput,
    EmailInput,
    PasswordInput,
    NumberInput,
    CheckboxInput,
    Select,
    Textarea,
    HiddenInput,
)

# Create Nforms namespace class for cleaner imports
class Nforms:
    '''Nexa's native form-handling system.'''
    Form = Form
    ValidationError = ValidationError
    CharField = CharField
    EmailField = EmailField
    IntegerField = IntegerField
    FloatField = FloatField
    BooleanField = BooleanField
    DateField = DateField
    DateTimeField = DateTimeField
    ChoiceField = ChoiceField
    MultipleChoiceField = MultipleChoiceField
    PasswordField = PasswordField
    TextInput = TextInput
    EmailInput = EmailInput
    PasswordInput = PasswordInput
    NumberInput = NumberInput
    CheckboxInput = CheckboxInput
    Select = Select
    Textarea = Textarea
    HiddenInput = HiddenInput

    # Also expose widgets that map to field types
    DateInput = TextInput  # DateField uses TextInput for now
    
from os import getenv as _env

def getenv(key:Str):
    return _env(key)


__all__ = [
    "app",
    "App",
    "Element",
    "Fragment",
    "Nserver",
    "jsonify",
    "render_template",
    "Blueprint",
    "getenv",
    "Nforms"
]
