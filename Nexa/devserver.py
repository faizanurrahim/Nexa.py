"""Development workflow for ``nexa dev <file>``.

This module implements application discovery, DevTools initialization and the
development lifecycle for an application's existing :class:`NXserver`
instance.  It never creates a second server.

Reloading is implemented with a subprocess worker (``python -m
Nexa.devworker``) instead of ``multiprocessing`` so it works on Windows
without pickling local functions or application objects.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

WORKER_ENV_TOKEN = "NEXA_DEVTOOLS_TOKEN"

#: Variable names checked before falling back to a unique-instance search.
CONVENTIONAL_NAMES = ("app", "application", "server", "nexa_app", "app_server")

MISSING_WATCHFILES_MESSAGE = (
    "Automatic reload requires watchfiles.\n"
    "\n"
    "Install it with:\n"
    "python -m pip install watchfiles"
)

_IGNORED_DIRECTORIES = {
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    ".tox",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "site-packages",
}


class DevError(Exception):
    """A user-facing development CLI error."""


class AppLoadError(DevError):
    """The application file could not be loaded."""


class AppDiscoveryError(DevError):
    """No unambiguous ``NXserver`` instance could be found."""


@dataclass
class LoadedApplication:
    module: Any
    server: Any
    attribute: str
    path: Path


def _nxserver_class() -> Any:
    from .nxserver import NXserver

    return NXserver


# ---------------------------------------------------------------------------
# Loading and discovery
# ---------------------------------------------------------------------------


def load_module(path: str | Path) -> Any:
    """Import the Python file at *path* as a private module.

    The module is executed with ``__name__`` set to a generated name, so a
    conventional ``if __name__ == "__main__": app.run()`` guard does not start
    a second server during discovery.
    """
    file = Path(path)
    if not file.is_file():
        raise AppLoadError(f"Application file not found: {path}")
    if file.suffix != ".py":
        raise AppLoadError(f"Expected a Python application file (.py): {path}")

    resolved = file.resolve()
    module_name = f"nexa_dev_{resolved.stem}_{uuid.uuid4().hex[:8]}"
    spec = importlib.util.spec_from_file_location(module_name, resolved)
    if spec is None or spec.loader is None:
        raise AppLoadError(f"Could not load application file: {path}")

    module = importlib.util.module_from_spec(spec)
    directory = str(resolved.parent)
    inserted = directory not in sys.path
    if inserted:
        sys.path.insert(0, directory)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise AppLoadError(
            f"Failed to import {path}: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        if inserted:
            try:
                sys.path.remove(directory)
            except ValueError:
                pass
    return module


def discover_server(module: Any, attribute: Optional[str] = None) -> tuple[Any, str]:
    """Return ``(server, attribute_name)`` from an imported application module.

    Selection rules:

    1. an explicit *attribute* name always wins;
    2. otherwise the module's only ``NXserver`` instance is used, whatever its
       variable name;
    3. if the module defines more than one, ``--app NAME`` is required.

    Names are never guessed between multiple instances.  The names in
    :data:`CONVENTIONAL_NAMES` are recommended by the documentation and listed
    in the multi-instance error.
    """
    nxserver = _nxserver_class()

    if attribute:
        candidate = getattr(module, attribute, None)
        if isinstance(candidate, nxserver):
            return candidate, attribute
        raise AppDiscoveryError(
            f"The application has no NXserver named {attribute!r}"
        )

    servers = [
        (name, obj)
        for name, obj in vars(module).items()
        if isinstance(obj, nxserver)
    ]
    if len(servers) == 1:
        return servers[0][1], servers[0][0]
    if not servers:
        raise AppDiscoveryError(
            "No NXserver instance found in the application. Create one, for "
            "example `app = NXserver(\"demo\")`, or select one with --app NAME."
        )

    names = ", ".join(sorted(name for name, _ in servers))
    conventional = ", ".join(CONVENTIONAL_NAMES)
    raise AppDiscoveryError(
        f"Multiple NXserver instances found ({names}). "
        f"Choose one with --app NAME (conventional names: {conventional})."
    )


def load_application(
    path: str | Path, attribute: Optional[str] = None
) -> LoadedApplication:
    module = load_module(path)
    server, attribute_name = discover_server(module, attribute)
    return LoadedApplication(
        module=module,
        server=server,
        attribute=attribute_name,
        path=Path(path),
    )


# ---------------------------------------------------------------------------
# Development server
# ---------------------------------------------------------------------------


def generate_token() -> str:
    import secrets

    return secrets.token_urlsafe(24)


def print_banner(application: Path, server: Any, token: str) -> None:
    """Print the development banner for the actual server configuration."""
    host = "127.0.0.1" if server.host == "0.0.0.0" else server.host
    print("Nexa.py Development Server\n", flush=True)
    print(f"Application: {application}", flush=True)
    print(f"Server: http://{host}:{server.port}", flush=True)
    print(f"DevTools: http://{host}:{server.port}/__nexa__/\n", flush=True)
    print(f"DevTools token: {token}\n", flush=True)


def run_dev_app(
    application: str | Path,
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    attribute: Optional[str] = None,
    token: Optional[str] = None,
) -> None:
    """Load *application*, enable DevTools on its server and run it."""
    loaded = load_application(application, attribute)
    server = loaded.server

    if host is not None:
        server.host = host
    if port is not None:
        server.port = port

    token = token or generate_token()
    server.enable_devtools(token=token)

    print_banner(loaded.path, server, token)
    print("Starting development server...\n", flush=True)
    try:
        server.run()
    except KeyboardInterrupt:
        print("\nServer stopped.", flush=True)


# ---------------------------------------------------------------------------
# Reloader (subprocess based, Windows compatible)
# ---------------------------------------------------------------------------


def require_watchfiles() -> Any:
    """Import ``watchfiles`` or raise a friendly :class:`DevError`."""
    try:
        import watchfiles
    except ImportError as exc:
        raise DevError(MISSING_WATCHFILES_MESSAGE) from exc
    return watchfiles


def build_worker_command(
    application: str | Path,
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    attribute: Optional[str] = None,
) -> list[str]:
    """Return the subprocess command used to run the application worker."""
    command = [sys.executable, "-m", "Nexa.devworker", str(application)]
    if host is not None:
        command += ["--host", str(host)]
    if port is not None:
        command += ["--port", str(port)]
    if attribute is not None:
        command += ["--app", str(attribute)]
    return command


def start_worker(command: list[str], env: dict[str, str]) -> Any:
    """Start the worker process (argument list, never ``shell=True``)."""
    return subprocess.Popen(command, env=env)


def stop_worker(process: Any) -> None:
    """Terminate the worker process and make sure it is gone."""
    if process is None:
        return
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def should_reload(change: Any, path: str) -> bool:
    """Reload only for Python files outside caches, VCS and virtualenvs."""
    file = Path(path)
    if file.suffix != ".py":
        return False
    return not (_IGNORED_DIRECTORIES & set(file.parts))


def serve_with_reload(
    application: str | Path,
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    attribute: Optional[str] = None,
    token: Optional[str] = None,
) -> None:
    """Run the application in a worker subprocess and reload it on changes."""
    watchfiles = require_watchfiles()

    resolved = Path(application).resolve()
    target = Path(application)
    token = token or generate_token()
    command = build_worker_command(
        resolved, host=host, port=port, attribute=attribute
    )
    env = dict(os.environ)
    env[WORKER_ENV_TOKEN] = token

    process = start_worker(command, env)
    watched_dir = resolved.parent

    try:
        for _changes in watchfiles.watch(
            str(watched_dir),
            watch_filter=should_reload,
            debounce=300,
            step=100,
        ):
            print("\nChanges detected; restarting development server...\n", flush=True)
            stop_worker(process)
            process = start_worker(command, env)
    except KeyboardInterrupt:
        pass
    finally:
        stop_worker(process)
        print("\nDevelopment server stopped.", flush=True)
