"""Environment variable management for Nexa.py.

Provides a project-scoped environment abstraction with defaults, type helpers,
file-based persistence, and safe secret handling.

Usage::

    from Nexa import Env

    env = Env("myapp")
    env.set("DEBUG", "true", type=bool)
    assert env.get("DEBUG") is True
    assert env.exists("DEBUG")
    env.delete("DEBUG")
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional, TypeVar, Union

T = TypeVar("T")


class Env:
    """A project-scoped environment manager.

    Keys are namespaced under the given prefix so different projects or modules
    do not accidentally collide.  Values are stored in a JSON file next to the
    environment file when persistence is requested, but the in-memory store
    takes precedence.

    Environment variables from the real process environment are visible through
    :meth:`get` only when no in-memory value exists for the same key, and
    :meth:`set` never overwrites an existing OS-level variable unless
    :paramref:`override` is ``True``.

    Secrets are deliberately excluded from structured dumps and diagnostic
    output.
    """

    _TYPE_GUESS: frozenset[str] = frozenset({"true", "false", "null", "none"})

    def __init__(
        self,
        prefix: str = "NXA",
        env_file: Optional[Union[str, Path]] = None,
        *,
        auto_create: bool = True,
    ) -> None:
        """Initialise an environment manager.

        :param prefix: Namespace prefix applied to all keys.
        :param env_file: Optional path to a JSON file used for persistence.
            When omitted, no file is read or written.
        :param auto_create: When ``True``, the env file directory is created
            automatically if it does not exist.
        """
        self._prefix = prefix.upper()
        self._store: dict[str, Any] = {}
        self._env_file: Optional[Path] = None
        self._auto_create = auto_create

        if env_file is not None:
            self._env_file = Path(env_file)
            if self._env_file.suffix != ".json":
                self._env_file = self._env_file.with_suffix(".json")
            if auto_create:
                self._env_file.parent.mkdir(parents=True, exist_ok=True)
            self._load_file()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prefixed(self, key: str) -> str:
        """Return the internal (prefixed) form of *key*."""
        if key.startswith(f"{self._prefix}_"):
            return key
        return f"{self._prefix}_{key.upper()}"

    def _real_env_key(self, key: str) -> str:
        """Return the OS environment variable name for *key*."""
        return self._prefixed(key)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_file(self) -> None:
        """Load persisted values from the env file, if any."""
        if self._env_file is None or not self._env_file.is_file():
            return
        try:
            with self._env_file.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            # Corrupt or unreadable file: start fresh rather than failing.
            self._store.clear()
            return
        if isinstance(data, dict):
            self._store.update(data)

    def _save_file(self) -> None:
        """Persist the current in-memory store to the env file, if configured."""
        if self._env_file is None:
            return
        if self._auto_create:
            self._env_file.parent.mkdir(parents=True, exist_ok=True)
        with self._env_file.open("w", encoding="utf-8") as fh:
            json.dump(self._store, fh, indent=2, sort_keys=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(
        self,
        key: str,
        default: Any = None,
        *,
        type: Optional[type] = None,
    ) -> Any:
        """Return the value for *key*, or *default* when absent.

        The lookup prefers in-memory values, then OS environment variables,
        then *default*.  A ``type`` hint converts the resolved value before
        returning it; passing ``type=bool`` recognises the common boolean
        spellings.

        :param key: Environment key (optionally already prefixed).
        :param default: Value returned when the key is absent.
        :param type: Optional type used to coerce the resolved value.
        """
        full_key = self._prefixed(key)

        value: Any = self._store.get(full_key)
        if value is None and full_key in os.environ:
            value = os.environ[full_key]

        if value is None:
            return default

        if type is None:
            return value

        return self._coerce(value, type)

    def set(
        self,
        key: str,
        value: Any,
        *,
        type: Optional[type] = None,
        override: bool = False,
        persist: bool = False,
    ) -> None:
        """Store *value* under *key*.

        By default, an existing OS-level environment variable is not overwritten.
        Set :paramref:`override` to ``True`` to replace it.

        When :paramref:`persist` is ``True``, the value is also written to the
        env file (if one is configured).

        :param key: Environment key (optionally already prefixed).
        :param value: Value to store.
        :param type: Optional type used to coerce *value* before storing.
        :param override: Replace an existing OS-level variable.
        :param persist: Write the value to the env file.
        """
        full_key = self._prefixed(key)

        if type is not None:
            value = self._coerce(value, type)

        os_key = self._real_env_key(key)
        if not override and os_key in os.environ:
            self._store[full_key] = value
            return

        if not override and os_key in os.environ:
            self._store[full_key] = value
        else:
            self._store[full_key] = value
            if override:
                os.environ[os_key] = str(value)

        if persist:
            self._save_file()

    def delete(self, key: str, *, persist: bool = False) -> bool:
        """Remove *key* from the in-memory store.

        Returns ``True`` when the key was present, ``False`` otherwise.

        :param key: Environment key (optionally already prefixed).
        :param persist: Remove the key from the env file as well.
        """
        full_key = self._prefixed(key)
        existed = full_key in self._store
        self._store.pop(full_key, None)
        if persist and self._env_file is not None:
            self._save_file()
        return existed

    def exists(self, key: str) -> bool:
        """Return ``True`` when *key* has a value in memory or the OS env."""
        full_key = self._prefixed(key)
        return full_key in self._store or full_key in os.environ

    def load(self, mapping: dict[str, Any]) -> None:
        """Load multiple values from a mapping into the in-memory store.

        Values from *mapping* take precedence over existing in-memory values
        but do not touch OS environment variables.

        :param mapping: Mapping of keys to values.
        """
        for key, value in mapping.items():
            full_key = self._prefixed(key)
            self._store[full_key] = value

    def dump(self, *, include_defaults: bool = False) -> dict[str, Any]:
        """Return a copy of the in-memory store.

        Secret values are replaced with ``"***"`` so they never appear in
        logs, diagnostics, or structured output.

        :param include_defaults: When ``True``, keys that only exist in the
            OS environment are also included.
        """
        out: dict[str, Any] = {}
        for key, value in self._store.items():
            if self._is_secret_like(key, value):
                out[key] = "***"
            else:
                out[key] = value
        if include_defaults:
            for key in os.environ:
                if key.startswith(f"{self._prefix}_") and key not in out:
                    out[key] = "***" if self._is_secret_like(key, os.environ[key]) else os.environ[key]
        return out

    # ------------------------------------------------------------------
    # Type helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce(value: Any, type: type) -> Any:
        """Coerce *value* to *type*."""
        if type is bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                low = value.strip().lower()
                if low in ("1", "true", "yes", "on"):
                    return True
                if low in ("0", "false", "no", "off", ""):
                    return False
                raise TypeError(f"Cannot interpret {value!r} as bool")
            if isinstance(value, (int, float)):
                return bool(value)
            return bool(value)

        if type is int:
            if isinstance(value, bool):
                return int(value)
            return int(value)

        if type is float:
            if isinstance(value, bool):
                return float(value)
            return float(value)

        if type is str:
            return str(value)

        # For anything else, try the constructor directly.
        try:
            return type(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"Cannot coerce {value!r} to {type.__name__}") from exc

    @staticmethod
    def _is_secret_like(key: str, value: Any) -> bool:
        """Return ``True`` when *key* or *value* smells like a secret."""
        k = key.lower()
        secret_hints = {
            "secret", "token", "password", "passwd", "api_key", "apikey",
            "access_token", "auth", "credential", "private_key", "secret_key",
        }
        for hint in secret_hints:
            if hint in k:
                return True
        if isinstance(value, str) and len(value) > 8 and value.isascii():
            # Very rough heuristic: a long hex/base64-looking string.
            return False
        return False


class NexaEnv:
    """Legacy alias kept for backwards compatibility with existing code.

    Prefer :class:`Env` for new code.
    """

    def __init__(self, prefix: str = "NXA") -> None:
        self._env = Env(prefix)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._env, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            super().__setattr__(name, value)
            return
        self._env.set(name, value)
