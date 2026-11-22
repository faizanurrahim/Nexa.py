"""Project layout and configuration helpers for Nova."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Dict, Optional


NOVA_DIR = ".nova"
NEXA_RUNTIME = "nexa"


def find_project_root(start: Optional[Path] = None) -> Optional[Path]:
    """Walk up from *start* looking for a ``nexa.toml`` file."""
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / "nexa.toml").is_file():
            return candidate
    return None


def nova_dir(project_root: Path) -> Path:
    return project_root / NOVA_DIR


def runtime_dir(project_root: Path) -> Path:
    return project_root / NOVA_DIR / NEXA_RUNTIME


def venv_dir(project_root: Path) -> Path:
    return project_root / NOVA_DIR / "venv"


def venv_python(project_root: Path) -> Path:
    venv = venv_dir(project_root)
    if _is_windows():
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _is_windows() -> bool:
    import sys

    return sys.platform.startswith("win")


def load_config(project_root: Path) -> Dict[str, Any]:
    path = project_root / "nexa.toml"
    if not path.is_file():
        raise FileNotFoundError(f"nexa.toml not found in {project_root}")
    with path.open("rb") as f:
        return tomllib.load(f)


def write_config(project_root: Path, config: Dict[str, Any]) -> None:
    # Minimal TOML writer for the supported schema.
    lines = []
    project = config.get("project", {})
    lines.append("[project]")
    for key in ("name", "version", "nexa", "description"):
        if key in project:
            lines.append(f'{key} = "{project[key]}"')
    lines.append("")

    deps = config.get("dependencies", {})
    lines.append("[dependencies]")
    for name, constraint in deps.items():
        lines.append(f'{name} = "{constraint}"')
    lines.append("")

    nexa_deps = config.get("nexa.dependencies", config.get("nexa_dependencies", {}))
    lines.append("[nexa.dependencies]")
    for name, constraint in nexa_deps.items():
        lines.append(f'{name} = "{constraint}"')
    lines.append("")

    scripts = config.get("scripts", {})
    lines.append("[scripts]")
    for name, cmd in scripts.items():
        lines.append(f'{name} = "{cmd}"')
    lines.append("")

    (project_root / "nexa.toml").write_text("\n".join(lines), encoding="utf-8")


def ensure_layout(project_root: Path) -> None:
    """Create the ``.nova/`` layout and runtime files if missing."""
    nd = nova_dir(project_root)
    nd.mkdir(parents=True, exist_ok=True)
    # venv itself is created by env.create_venv; do not leave an empty dir here.
    rd = runtime_dir(project_root)
    for sub in ("LIB", "BIN", "runtime", "internal"):
        (rd / sub).mkdir(parents=True, exist_ok=True)
    (nd / "envvariables").mkdir(parents=True, exist_ok=True)
    (nd / "temp").mkdir(parents=True, exist_ok=True)
    # Runtime resource files.
    (rd / "main.nxnexa").touch(exist_ok=True)
    (rd / "netstat").touch(exist_ok=True)
    (project_root / "static").mkdir(exist_ok=True)
    (project_root / "templates").mkdir(exist_ok=True)
    # Ensure .nova on path for LIB imports via a sitecustomize? Not needed.
    # Make LIB importable by writing a .pth? Skip for now.
    # Ensure BIN executable resolution marker.
    (rd / "BIN" / ".keep").touch(exist_ok=True)
    (rd / "LIB" / ".keep").touch(exist_ok=True)


DEFAULT_CONFIG = {
    "project": {
        "name": "my-project",
        "version": "1.0.0",
        "nexa": "1.0.0",
    },
    "dependencies": {},
    "nexa.dependencies": {},
    "scripts": {
        "dev": "nexa dev main.py",
        "start": "nexa run main.py",
    },
}
