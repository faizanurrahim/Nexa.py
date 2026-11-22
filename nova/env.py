"""Virtual-environment helpers for Nova."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .project import venv_dir, venv_python


def is_valid_venv(project_root: Path) -> bool:
    """Return True if *project_root* has a working virtual environment."""
    venv = venv_dir(project_root)
    py = venv_python(project_root)
    if not venv.is_dir() or not py.is_file():
        return False
    if not (venv / "pyvenv.cfg").is_file():
        return False
    try:
        res = subprocess.run(
            [str(py), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def create_venv(project_root: Path) -> Path:
    """Create (or repair) the project virtual environment and return its python."""
    venv = venv_dir(project_root)
    py = venv_python(project_root)

    if is_valid_venv(project_root):
        return py

    # If a directory exists but is not a valid environment, warn and recreate.
    if venv.exists():
        import sys as _sys

        try:
            import typer as _typer

            _typer.echo(
                "Nova warning: existing .nova/venv is invalid or incomplete; recreating it.",
                err=True,
            )
        except Exception:
            print(
                "Nova warning: existing .nova/venv is invalid or incomplete; recreating it.",
                file=_sys.stderr,
            )
        shutil.rmtree(venv, ignore_errors=True)

    venv.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "venv", str(venv)],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Python interpreter not found; cannot create a virtual environment."
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(
            "Failed to create virtual environment: "
            + (detail if detail else str(exc))
        ) from exc

    if not is_valid_venv(project_root):
        raise RuntimeError(
            "Virtual environment creation completed but the interpreter is not usable."
        )
    return venv_python(project_root)


def run_in_venv(project_root: Path, args: list[str], **kwargs) -> subprocess.CompletedProcess:
    py = venv_python(project_root)
    if not py.is_file() or not is_valid_venv(project_root):
        raise FileNotFoundError("Project virtual environment not found. Run 'nova install'.")
    env = dict(kwargs.pop("env", None) or {})
    import os

    env = {**os.environ, **env}
    # Add project .nova/nexa/LIB and BIN to paths.
    from .project import runtime_dir

    rd = runtime_dir(project_root)
    lib = str(rd / "LIB")
    bin_dir = str(rd / "BIN")
    pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([lib, str(project_root), pp]) if pp else os.pathsep.join([lib, str(project_root)])
    path_var = env.get("PATH", "")
    env["PATH"] = os.pathsep.join([bin_dir, path_var]) if path_var else bin_dir
    return subprocess.run([str(py), *args], cwd=str(project_root), env=env, **kwargs)


def pip(project_root: Path, args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return run_in_venv(project_root, ["-m", "pip", *args], **kwargs)


def find_nexa_source() -> Optional[str]:
    """Locate a local Nexa.py source tree (for offline installs)."""
    from pathlib import Path

    # Search from this module upward.
    cur = Path(__file__).resolve().parent
    for candidate in [cur, *cur.parents]:
        if (candidate / "pyproject.toml").is_file():
            try:
                text = (candidate / "pyproject.toml").read_text(encoding="utf-8")
            except OSError:
                continue
            if 'name = "Nexa.py"' in text or "name = 'Nexa.py'" in text:
                return str(candidate)
    # Also search cwd and parents.
    cur = Path.cwd().resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / "pyproject.toml").is_file():
            try:
                text = (candidate / "pyproject.toml").read_text(encoding="utf-8")
            except OSError:
                continue
            if 'name = "Nexa.py"' in text or "name = 'Nexa.py'" in text:
                return str(candidate)
    return None
