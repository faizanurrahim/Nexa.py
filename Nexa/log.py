"""Centralised logging for Nexa.py.

Provides a small, self-contained logging facade with level filtering, console
and file output, structured (JSON) logging, and helpers for request and
exception logging.  Secrets are never emitted.

Usage::

    from Nexa import log

    log.info("Server started on %s:%d", host, port)
    log.error("Failed to bind: %s", exc)
    log.request("GET /health 200 3ms")
    log.exception("Unhandled error", exc)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

# ---------------------------------------------------------------------------
# Level constants
# ---------------------------------------------------------------------------

LEVEL_TRACE = 5
LEVEL_DEBUG = 10
LEVEL_INFO = 20
LEVEL_WARN = 30
LEVEL_ERROR = 40
LEVEL_FATAL = 50

_LEVEL_NAMES: dict[int, str] = {
    LEVEL_TRACE: "TRACE",
    LEVEL_DEBUG: "DEBUG",
    LEVEL_INFO: "INFO",
    LEVEL_WARN: "WARN",
    LEVEL_ERROR: "ERROR",
    LEVEL_FATAL: "FATAL",
}


def _level_name(level: int) -> str:
    return _LEVEL_NAMES.get(level, str(level))


def _parse_level(name: Union[str, int]) -> int:
    if isinstance(name, int):
        return name
    name = name.strip().upper()
    for lvl, lbl in _LEVEL_NAMES.items():
        if lbl == name:
            return lvl
    # Accept standard logging level names too.
    try:
        return int(getattr(logging, name))
    except (AttributeError, ValueError):
        raise ValueError(f"Unknown log level: {name}")


# ---------------------------------------------------------------------------
# Secret filtering
# ---------------------------------------------------------------------------

_SECRET_HINTS: frozenset[str] = frozenset({
    "secret", "token", "password", "passwd", "api_key", "apikey",
    "access_token", "auth", "credential", "private_key", "secret_key",
    "authorization", "x-api-key",
})


def _is_secret_key(key: str) -> bool:
    k = key.lower()
    for hint in _SECRET_HINTS:
        if hint in k:
            return True
    return False


def _scrub(value: Any) -> Any:
    """Replace values that look like secrets with ``"***"``."""
    if isinstance(value, dict):
        return {k: "***" if _is_secret_key(k) else _scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_scrub(v) for v in value)
    if isinstance(value, str) and len(value) > 16:
        # Heuristic: long strings are left alone unless the key suggests a secret.
        return value
    return value


def _scrub_message(message: str) -> str:
    """Replace secret-looking ``key=value`` tokens in a log message string.

    Only non-whitespace ``key=value`` segments whose key is a recognised
    secret hint are redacted.  This protects against secrets embedded in
    log message strings (for example from structured logging that was not
    fully parsed).
    """
    out: list[str] = []
    for token in message.split():
        if "=" in token:
            key, _, rest = token.partition("=")
            if _is_secret_key(key):
                out.append(f"{key}=***")
                continue
        out.append(token)
    return " ".join(out)


# ---------------------------------------------------------------------------
# Logger implementation
# ---------------------------------------------------------------------------


class NexaLog:
    """A configurable Nexa logger.

    Instances are independent; there is no global singleton by default.  For
    convenience, the module-level helper functions use a default logger named
    ``"nexa"``.
    """

    def __init__(
        self,
        name: str = "nexa",
        *,
        level: Union[str, int] = "INFO",
        fmt: Optional[str] = None,
        datefmt: Optional[str] = None,
        add_level: bool = True,
        add_time: bool = True,
        add_fileline: bool = False,
    ) -> None:
        """Initialise a logger.

        :param name: Logger name used in output.
        :param level: Minimum level to emit.
        :param fmt: Custom format string.  When ``None``, a default is used.
        :param datefmt: Format string for timestamps.
        :param add_level: Include the level label.
        :param add_time: Include the timestamp.
        :param add_fileline: Include the originating file and line.
        """
        self._name = name
        self._level = _parse_level(level)
        self._fmt = fmt
        self._datefmt = datefmt
        self._add_level = add_level
        self._add_time = add_time
        self._add_fileline = add_fileline
        self._file_handler: Optional[logging.Handler] = None
        self._stream_handler: Optional[logging.Handler] = None
        self._structured = False

        # Build a real logging.Logger under the hood.
        self._logger = logging.getLogger(name)
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers.clear()
        self._logger.propagate = False

        # Default formatter.
        if fmt is None:
            parts: list[str] = []
            if add_time:
                parts.append("%(asctime)s")
            if add_level:
                parts.append("%(levelname)s")
            parts.append(f"[{name}]")
            if add_fileline:
                parts.append("%(filename)s:%(lineno)d")
            parts.append("%(message)s")
            fmt = " ".join(parts)

        self._formatter = logging.Formatter(fmt, datefmt=datefmt)
        self._stream_handler = logging.StreamHandler(sys.stderr)
        self._stream_handler.setLevel(logging.DEBUG)
        self._stream_handler.setFormatter(self._formatter)
        self._logger.addHandler(self._stream_handler)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_level(self, level: Union[str, int]) -> None:
        """Change the minimum log level."""
        self._level = _parse_level(level)

    def set_format(self, fmt: str, *, datefmt: Optional[str] = None) -> None:
        """Replace the log format."""
        self._fmt = fmt
        self._datefmt = datefmt
        self._formatter = logging.Formatter(fmt, datefmt=datefmt)
        if self._stream_handler:
            self._stream_handler.setFormatter(self._formatter)
        if self._file_handler:
            self._file_handler.setFormatter(self._formatter)

    def enable_file(self, path: Union[str, Path], *, level: Optional[Union[str, int]] = None) -> None:
        """Enable file output.

        :param path: File path to write logs to.
        :param level: Optional level for the file handler (defaults to the
            logger's level).
        """
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(str(file_path), encoding="utf-8")
        handler.setLevel(logging.DEBUG if level is None else _parse_level(level))
        handler.setFormatter(self._formatter)
        self._logger.addHandler(handler)
        self._file_handler = handler

    def enable_structured(self) -> None:
        """Switch output to JSON lines format."""
        self._structured = True
        if self._stream_handler:
            self._stream_handler.setFormatter(_StructuredFormatter(self._name))
        if self._file_handler:
            self._file_handler.setFormatter(_StructuredFormatter(self._name))

    def disable_structured(self) -> None:
        """Switch output back to plain-text format."""
        self._structured = False
        if self._stream_handler:
            self._stream_handler.setFormatter(self._formatter)
        if self._file_handler:
            self._file_handler.setFormatter(self._formatter)

    # ------------------------------------------------------------------
    # Core logging methods
    # ------------------------------------------------------------------

    def _emit(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        if level < self._level:
            return

        exc_info = kwargs.pop("exc_info", None)
        extra = kwargs.pop("extra", None)

        if args:
            try:
                msg = msg % args
            except (TypeError, ValueError):
                msg = msg + " " + " ".join(str(a) for a in args)

        payload: dict[str, Any] = {
            "level": _level_name(level),
            "logger": self._name,
            "message": msg,
        }

        if self._add_time:
            payload["time"] = datetime.now(timezone.utc).isoformat()

        if exc_info is not None:
            payload["exception"] = "".join(
                traceback.format_exception(type(exc_info), exc_info, exc_info.__traceback__)
            )
        elif exc_info is False and kwargs.get("stack_info"):
            payload["stack"] = "".join(traceback.format_stack())

        if extra:
            payload["extra"] = _scrub(extra)

        if self._structured:
            line = json.dumps(_scrub(payload), default=str, ensure_ascii=False)
            self._logger.handle(
                logging.LogRecord(
                    name=self._name,
                    level=level,
                    pathname="",
                    lineno=0,
                    msg=line,
                    args=(),
                    exc_info=None,
                )
            )
        else:
            scrubbed = _scrub_message(msg)
            if exc_info is not None:
                self._logger.log(level, scrubbed, exc_info=exc_info)
            else:
                self._logger.log(level, scrubbed)

    def trace(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._emit(LEVEL_TRACE, msg, *args, **kwargs)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._emit(LEVEL_DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._emit(LEVEL_INFO, msg, *args, **kwargs)

    def warn(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._emit(LEVEL_WARN, msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.warn(msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._emit(LEVEL_ERROR, msg, *args, **kwargs)

    def fatal(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._emit(LEVEL_FATAL, msg, *args, **kwargs)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def request(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a request summary line at INFO level."""
        self.info(msg, *args, **kwargs)

    def exception(self, msg: str, exc: BaseException, *args: Any, **kwargs: Any) -> None:
        """Log an exception with its traceback."""
        self.error(msg, *args, exc_info=exc, **kwargs)


class _StructuredFormatter(logging.Formatter):
    """Formatter that writes JSON lines."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name

    def format(self, record: logging.LogRecord) -> str:
        try:
            payload = json.loads(record.getMessage())
        except json.JSONDecodeError:
            payload = {"level": record.levelname, "logger": self._name, "message": _scrub_message(record.getMessage())}
        return json.dumps(_scrub(payload), default=str, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Module-level default logger
# ---------------------------------------------------------------------------

_default: Optional[NexaLog] = None


def _get_default() -> NexaLog:
    global _default
    if _default is None:
        _default = NexaLog()
    return _default


def trace(msg: str, *args: Any, **kwargs: Any) -> None:
    _get_default().trace(msg, *args, **kwargs)


def debug(msg: str, *args: Any, **kwargs: Any) -> None:
    _get_default().debug(msg, *args, **kwargs)


def info(msg: str, *args: Any, **kwargs: Any) -> None:
    _get_default().info(msg, *args, **kwargs)


def warn(msg: str, *args: Any, **kwargs: Any) -> None:
    _get_default().warn(msg, *args, **kwargs)


def warning(msg: str, *args: Any, **kwargs: Any) -> None:
    _get_default().warning(msg, *args, **kwargs)


def error(msg: str, *args: Any, **kwargs: Any) -> None:
    _get_default().error(msg, *args, **kwargs)


def fatal(msg: str, *args: Any, **kwargs: Any) -> None:
    _get_default().fatal(msg, *args, **kwargs)


def request(msg: str, *args: Any, **kwargs: Any) -> None:
    _get_default().request(msg, *args, **kwargs)


def exception(msg: str, exc: BaseException, *args: Any, **kwargs: Any) -> None:
    _get_default().exception(msg, exc, *args, **kwargs)


def get_logger(name: str = "nexa", **kwargs: Any) -> NexaLog:
    """Return a new :class:`NexaLog` instance (or the default if *name* is ``"nexa"``)."""
    if name == "nexa" and not kwargs:
        return _get_default()
    return NexaLog(name, **kwargs)
