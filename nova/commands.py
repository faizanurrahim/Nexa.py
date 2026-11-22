"""Command parsing and execution for Nova project scripts.

``[scripts]`` values in ``nexa.toml`` are command lines, for example
``dev = "nexa dev main.py"``.  They must be split into an executable plus
arguments -- never treated as a single filesystem path.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, Optional

from .project import runtime_dir, venv_dir, venv_python


class CommandError(Exception):
    """A configured command could not be parsed, resolved, or executed."""


def _is_windows() -> bool:
    return os.name == "nt"


def _strip_windows_quotes(token: str) -> str:
    """Remove quotes retained by ``shlex`` in non-POSIX mode."""
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        return token[1:-1]
    return token


def split_command(command: str) -> list[str]:
    """Split a configured command line into executable and arguments.

    Quotes group arguments and are removed.  On Windows the non-POSIX shlex
    mode is used so backslashes in paths are preserved.
    """
    if not isinstance(command, str) or not command.strip():
        raise CommandError("empty command string")
    posix = not _is_windows()
    try:
        tokens = shlex.split(command, posix=posix)
    except ValueError as exc:
        raise CommandError(f"invalid command {command!r}: {exc}") from exc
    if not posix:
        tokens = [_strip_windows_quotes(token) for token in tokens]
    if not tokens or not tokens[0]:
        raise CommandError(f"invalid command {command!r}: no executable")
    return tokens


def project_env(project_root: Path) -> dict[str, str]:
    """Environment with the project venv and Nexa runtime directories first."""
    env = dict(os.environ)
    venv = venv_dir(project_root)
    rd = runtime_dir(project_root)
    bin_dir = venv / ("Scripts" if _is_windows() else "bin")

    path_parts = [str(bin_dir), str(rd / "BIN")]
    if env.get("PATH"):
        path_parts.append(env["PATH"])
    env["PATH"] = os.pathsep.join(path_parts)

    python_path = [str(rd / "LIB"), str(project_root)]
    if env.get("PYTHONPATH"):
        python_path.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(python_path)

    if (venv / "pyvenv.cfg").is_file():
        env["VIRTUAL_ENV"] = str(venv)
    return env


def _windows_candidates(path: Path) -> Iterable[Path]:
    yield path
    if path.suffix:
        return
    extensions = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    for extension in extensions.split(os.pathsep):
        if extension:
            yield path.with_name(path.name + extension.lower())


def _path_candidates(path: Path, project_root: Path) -> Iterable[Path]:
    if path.is_absolute():
        base = path
    else:
        base = project_root / path
    if _is_windows():
        yield from _windows_candidates(base)
    else:
        yield base


def resolve_executable(executable: str, project_root: Path, env: dict[str, str]) -> str:
    """Resolve *executable* against the project environment and system PATH."""
    has_separator = os.sep in executable or bool(os.altsep and os.altsep in executable)
    path = Path(executable)
    looks_like_path = path.is_absolute() or has_separator or (_is_windows() and ":" in executable)

    if looks_like_path:
        for candidate in _path_candidates(path, project_root):
            if candidate.is_file():
                return str(candidate)
        raise CommandError(f"executable not found: {executable}")

    found = shutil.which(executable, path=env.get("PATH"))
    if found:
        return found

    # Also accept a file in the project root even if it is not on PATH.
    for candidate in _path_candidates(Path(executable), project_root):
        if candidate.is_file():
            return str(candidate)
    raise CommandError(f"executable not found: {executable}")


def build_command_argv(
    tokens: list[str], project_root: Path, env: dict[str, str]
) -> list[str]:
    """Turn split command tokens into an argv list ready for ``subprocess``."""
    executable = tokens[0]
    resolved = resolve_executable(executable, project_root, env)
    resolved_path = Path(resolved)

    # A Python file configured as a command runs with the project interpreter.
    if resolved_path.suffix.lower() == ".py":
        python = venv_python(project_root)
        if not python.is_file():
            raise CommandError(
                "no virtual environment; run 'nova install' to create one"
            )
        return [str(python), resolved, *tokens[1:]]

    # Windows cannot CreateProcess a .cmd/.bat directly; use cmd.exe without
    # a shell string so arguments remain an explicit argv list.
    if _is_windows() and resolved_path.suffix.lower() in (".cmd", ".bat"):
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        return [comspec, "/d", "/c", "call", resolved, *tokens[1:]]

    return [resolved, *tokens[1:]]


def run_command(
    project_root: Path,
    command: str,
    extra_args: Optional[list[str]] = None,
) -> int:
    """Execute a configured command from *project_root* and return its exit code."""
    tokens = split_command(command)
    if extra_args:
        tokens.extend(extra_args)
    env = project_env(project_root)
    argv = build_command_argv(tokens, project_root, env)
    try:
        # stdout/stderr are inherited, so output goes straight to the terminal.
        result = subprocess.run(argv, cwd=str(project_root), env=env, shell=False)
    except OSError as exc:
        raise CommandError(f"failed to execute {tokens[0]!r}: {exc}") from exc
    return result.returncode
