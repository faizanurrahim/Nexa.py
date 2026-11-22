"""NXLang Base — the language subsystem introduced in Nexa.py 0.9.0.

Implemented in this release:

* lexer, parser, AST and compiler pipeline
* native ``nx`` execution environment (the ``py`` environment is reserved)
* module inclusion syntax: ``include <module> as alias`` and
  ``include <<internal_module>> as alias``
* ``do { } unless ERR as e { }`` error handling with inheritance matching
* the ``ERR`` error hierarchy
* ``nexa exec`` integration

Not implemented yet: a full language, expressions beyond calls/literals,
user-defined functions, and Python interoperability.
"""

from __future__ import annotations

from .compiler import CompiledProgram, Compiler, compile_source
from .environments import (
    Environment,
    NativeEnvironment,
    PythonEnvironment,
    get_environment,
    list_environments,
)
from .errors import (
    ERROR_TYPES,
    ERR,
    CompileERR,
    EnvironmentERR,
    ImportERR,
    InternalERR,
    ModuleERR,
    NameERR,
    RuntimeERR,
    SyntaxERR,
    TypeERR,
    resolve_error_type,
)
from .lexer import Lexer, Token
from .modules import Module, ModuleRegistry, default_registry
from .nx import NXLang, execute, run_file, run_source
from .parser import Parser
from .runtime import Runtime

__all__ = [
    "ERR",
    "SyntaxERR",
    "CompileERR",
    "RuntimeERR",
    "ImportERR",
    "ModuleERR",
    "EnvironmentERR",
    "TypeERR",
    "NameERR",
    "InternalERR",
    "ERROR_TYPES",
    "resolve_error_type",
    "Lexer",
    "Token",
    "Parser",
    "Compiler",
    "CompiledProgram",
    "compile_source",
    "Runtime",
    "Module",
    "ModuleRegistry",
    "default_registry",
    "Environment",
    "NativeEnvironment",
    "PythonEnvironment",
    "get_environment",
    "list_environments",
    "NXLang",
    "run_source",
    "run_file",
    "execute",
]
