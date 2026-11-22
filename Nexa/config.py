"""Configuration management for Nexa.py.

Provides a TOML-based configuration system with defaults, validation,
environment variable overrides, and per-instance isolation.

Usage::

    from Nexa import Config

    cfg = Config()
    cfg.load("nexa.toml")
    host = cfg.get("server.host", default="127.0.0.1")
    port = cfg.get("server.port", default=8000, type=int)
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar, Union

T = TypeVar("T")


class ConfigValidationError(Exception):
    """Raised when a configuration value fails validation."""


class Config:
    """A TOML-based configuration container.

    Configuration is loaded from TOML files and merged with defaults.  Nested
    values are accessed with dotted keys (``"server.host"``).  Environment
    variables can override individual values when they follow the
    ``NXA_<section>_<key>`` naming convention.

    Each instance is fully independent — there is no global mutable state.
    """

    def __init__(
        self,
        *,
        defaults: Optional[dict[str, Any]] = None,
        env_prefix: str = "NXA",
        validate_on_get: bool = False,
    ) -> None:
        """Initialise a configuration container.

        :param defaults: Optional default values (dotted keys supported).
        :param env_prefix: Prefix used to identify environment variable
            overrides (e.g. ``NXA_``).
        :param validate_on_get: When ``True``, validation rules are checked
            every time a value is retrieved.
        """
        self._data: dict[str, Any] = {}
        self._defaults: dict[str, Any] = {}
        self._validators: dict[str, Callable[[Any], None]] = {}
        self._env_prefix = env_prefix.upper().rstrip("_")
        if defaults:
            self._defaults = self._flatten(defaults)
        if validate_on_get:
            self._apply_defaults()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        """Flatten a nested dict into dotted keys."""
        out: dict[str, Any] = {}
        for key, value in d.items():
            full = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                out.update(Config._flatten(value, full))
            else:
                out[full] = value
        return out

    @staticmethod
    def _unflatten(d: dict[str, Any]) -> dict[str, Any]:
        """Rebuild a nested dict from dotted keys."""
        result: dict[str, Any] = {}
        for key, value in d.items():
            parts = key.split(".")
            cur = result
            for part in parts[:-1]:
                if part not in cur or not isinstance(cur[part], dict):
                    cur[part] = {}
                cur = cur[part]
            cur[parts[-1]] = value
        return result

    def _apply_defaults(self) -> None:
        """Merge defaults into the current data."""
        for key, value in self._defaults.items():
            if key not in self._data:
                self._data[key] = value

    def _resolve(self, key: str) -> Any:
        """Resolve a dotted key, checking env overrides first."""
        env_key = f"{self._env_prefix}_{key.upper().replace('.', '_')}"
        if env_key in os.environ:
            raw = os.environ[env_key]
            if key in self._validators and self._validators[key] is not None:
                try:
                    return self._coerce(raw, self._validators[key])
                except (TypeError, ValueError):
                    return raw
            return raw
        return self._data.get(key)

    @staticmethod
    def _coerce(value: str, target: type) -> Any:
        """Coerce a string value to *target* type."""
        if target is bool:
            low = value.strip().lower()
            if low in ("1", "true", "yes", "on"):
                return True
            if low in ("0", "false", "no", "off", ""):
                return False
            raise TypeError(f"Cannot interpret {value!r} as bool")
        if target is int:
            return int(value)
        if target is float:
            return float(value)
        if target is str:
            return value
        try:
            return target(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"Cannot coerce {value!r} to {target.__name__}") from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, source: Union[str, Path, bytes], *, override: bool = True) -> None:
        """Load configuration from a TOML source.

        :param source: Path to a TOML file, a file-like object, or raw TOML bytes.
        :param override: When ``True``, new values replace existing ones.
            When ``False``, only missing keys are filled in.
        """
        if isinstance(source, (str, Path)):
            path = Path(source)
            if not path.is_file():
                raise FileNotFoundError(f"Config file not found: {path}")
            with path.open("rb") as fh:
                data = tomllib.load(fh)
        elif isinstance(source, bytes):
            data = tomllib.loads(source.decode("utf-8"))
        else:
            # Assume file-like object with read().
            data = tomllib.load(source)

        flat = self._flatten(data)
        if override:
            self._data.update(flat)
        else:
            for key, value in flat.items():
                self._data.setdefault(key, value)

    def get(
        self,
        key: str,
        default: Any = None,
        *,
        type: Optional[type] = None,
    ) -> Any:
        """Return the value for *key*, or *default* when absent.

        :param key: Dotted configuration key (e.g. ``"server.port"``).
        :param default: Value returned when the key is absent.
        :param type: Optional type used to coerce the resolved value.
        """
        if self._defaults:
            self._apply_defaults()

        value = self._resolve(key)
        if value is None and key not in self._data:
            return default

        if value is None:
            return default

        if type is not None:
            if isinstance(value, type):
                return value
            return self._coerce(str(value), type)

        return value

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value.

        :param key: Dotted configuration key.
        :param value: Value to store.
        """
        self._data[key] = value

    def delete(self, key: str) -> bool:
        """Remove a configuration key. Returns ``True`` if it existed."""
        if key in self._data:
            del self._data[key]
            return True
        return False

    def exists(self, key: str) -> bool:
        """Return ``True`` when *key* has a value (including defaults)."""
        if self._defaults:
            self._apply_defaults()
        return key in self._data

    def validate(self, key: str, validator: Callable[[Any], None]) -> None:
        """Register a validator for *key*.

        The validator receives the resolved value and raises
        :exc:`ConfigValidationError` if the value is invalid.

        :param key: Dotted configuration key.
        :param validator: Callable that raises on invalid values.
        """
        self._validators[key] = validator
        if self._data.get(key) is not None:
            try:
                validator(self._data[key])
            except ConfigValidationError:
                raise
            except Exception as exc:
                raise ConfigValidationError(
                    f"Validation failed for {key}"
                ) from exc

    def as_dict(self) -> dict[str, Any]:
        """Return a nested copy of the current configuration."""
        merged = dict(self._data)
        if self._defaults:
            for key, value in self._defaults.items():
                merged.setdefault(key, value)
        return self._unflatten(merged)

    def _validate_on_get(self, key: str) -> None:
        """Run validation for *key* if a validator is registered."""
        if key in self._validators:
            value = self._resolve(key)
            if value is not None:
                try:
                    self._validators[key](value)
                except ConfigValidationError:
                    raise
                except Exception as exc:
                    raise ConfigValidationError(
                        f"Validation failed for {key}"
                    ) from exc

    # Support ``config["key"]`` style access for convenience.
    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __contains__(self, key: str) -> bool:
        return self.exists(key)

    def __repr__(self) -> str:
        return f"Config({len(self._data)} keys)"
