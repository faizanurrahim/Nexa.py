"""NXLang module resolution.

NXLang has two module namespaces:

* regular modules — ``include <base_compiler> as bc``
* Nexa-internal modules — ``include <<_request_handler>> as rh``

Internal modules are resolved through this registry only.  They are never
resolved as ordinary Python imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .errors import ImportERR, ModuleERR


@dataclass
class Module:
    """A resolvable NXLang module."""

    name: str
    internal: bool = False
    exports: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.exports.get(key, default)

    def __repr__(self) -> str:
        left, right = ("<<", ">>") if self.internal else ("<", ">")
        return f"{left}{self.name}{right}"


class ModuleRegistry:
    """Separate registries for regular and Nexa-internal modules."""

    def __init__(self) -> None:
        self._regular: dict[str, Module] = {}
        self._internal: dict[str, Module] = {}

    # -- registration ---------------------------------------------------------
    def register(
        self,
        name: str,
        *,
        internal: bool = False,
        exports: Optional[dict[str, Any]] = None,
    ) -> Module:
        module = Module(name=name, internal=internal, exports=dict(exports or {}))
        (self._internal if internal else self._regular)[name] = module
        return module

    def unregister(self, name: str, *, internal: bool = False) -> None:
        (self._internal if internal else self._regular).pop(name, None)

    def available(self, *, internal: bool = False) -> list[str]:
        return sorted(self._internal if internal else self._regular)

    # -- resolution -----------------------------------------------------------
    def resolve(
        self,
        name: str,
        *,
        internal: bool = False,
        filename: Optional[str] = None,
        line: Optional[int] = None,
        column: Optional[int] = None,
    ) -> Module:
        module = (self._internal if internal else self._regular).get(name)
        if module is not None:
            return module

        kind = "internal" if internal else "regular"
        listing = ", ".join(self.available(internal=internal)) or "none"
        message = (
            f"Cannot resolve {kind} NXLang module {name!r} "
            f"(available {kind} modules: {listing})"
        )
        error = ModuleERR if internal else ImportERR
        raise error(message, filename=filename, line=line, column=column)

    @classmethod
    def with_defaults(cls) -> "ModuleRegistry":
        registry = cls()
        registry.register("base_compiler", exports={"kind": "compiler"})
        registry.register("relib", exports={"kind": "library"})
        registry.register("_cur_com_compiler", internal=True, exports={"kind": "compiler"})
        registry.register("_request_handler", internal=True, exports={"kind": "request"})
        registry.register("__edit_init__", internal=True, exports={"kind": "bootstrap"})
        return registry


def default_registry() -> ModuleRegistry:
    """Return a registry pre-populated with the NXLang Base modules."""
    return ModuleRegistry.with_defaults()
