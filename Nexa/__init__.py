
try:
    from .nexa import app
except ImportError:
    app = None  # typer not installed
from .asgi import ASGIAdaptor, ASGIServer
from .blade import BladeCompiler, BladeNode, install_blade_loader
from .blueprint import Blueprint
from .config import Config, ConfigValidationError
from .Core import Core
from .devtools import DevTools
from .env import Env, NexaEnv
from .log import (
    debug,
    error,
    fatal,
    get_logger,
    info,
    trace,
    warn,
    warning,
)
from .log import (
    exception as log_exception,
)
from .log import (
    request as log_request,
)
from .nforms import (
    BooleanField,
    CharField,
    CheckboxInput,
    ChoiceField,
    DateField,
    DateTimeField,
    EmailField,
    EmailInput,
    FloatField,
    Form,
    HiddenInput,
    IntegerField,
    MultipleChoiceField,
    NumberInput,
    PasswordField,
    PasswordInput,
    Select,
    Textarea,
    TextInput,
    ValidationError,
)
from .nx import App, Element, Fragment
from .nxserver import Nserver, NXserver, jsonify, render_template, request
from .static import StaticFiles
from .websocket import WebSocket, WebSocketServer


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


def getenv(key:str,default):
    return _env(key,default)


__all__ = [
    "app",
    "App",
    "Element",
    "Fragment",
    "NXserver",
    "Nserver",
    "Core",
    "jsonify",
    "render_template",
    "request",
    "Blueprint",
    "getenv",
    "Nforms",
    "ASGIAdaptor",
    "ASGIServer",
    "StaticFiles",
    "Env",
    "NexaEnv",
    "Config",
    "ConfigValidationError",
    "get_logger",
    "trace",
    "debug",
    "info",
    "warn",
    "warning",
    "error",
    "fatal",
    "log_request",
    "log_exception",
    "BladeCompiler",
    "BladeNode",
    "install_blade_loader",
    "DevTools",
    "WebSocket",
    "WebSocketServer",
]
