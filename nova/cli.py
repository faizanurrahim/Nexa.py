"""Nova command-line interface."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .commands import CommandError, project_env, run_command
from .env import create_venv, find_nexa_source, is_valid_venv, pip, run_in_venv
from .project import (
    DEFAULT_CONFIG,
    ensure_layout,
    find_project_root,
    load_config,
    nova_dir,
    runtime_dir,
    venv_python,
    write_config,
)

app = typer.Typer(
    name="nova",
    help="Nova — package and project manager for the Nexa ecosystem.",
    add_completion=False,
    no_args_is_help=True,
)


def _project_root_or_exit() -> Path:
    root = find_project_root()
    if root is None:
        typer.echo("Nova error: nexa.toml not found. Run 'nova init' first.", err=True)
        raise typer.Exit(code=1)
    return root


def _nexa_version_from_config(cfg: dict) -> str:
    project = cfg.get("project", {})
    return str(project.get("nexa", "1.0.0"))


@app.command()
def init(name: Optional[str] = typer.Option(None, "--name", "-n", help="Project name.")) -> None:
    """Initialize a new Nexa project in the current directory."""
    root = Path.cwd().resolve()
    if (root / "nexa.toml").is_file():
        typer.echo("nexa.toml already exists; leaving it unchanged.")
    else:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        if name:
            config["project"]["name"] = name
        # Use directory name as project name if not provided.
        if not name:
            config["project"]["name"] = root.name
        write_config(root, config)
    ensure_layout(root)
    # Initialize a real virtual environment (never leave an empty venv/ dir).
    try:
        create_venv(root)
    except Exception as exc:
        typer.echo(f"Nova error: failed to create virtual environment: {exc}", err=True)
        raise typer.Exit(code=1)
    # Create main.py if missing.
    main_py = root / "main.py"
    if not main_py.is_file():
        main_py.write_text(
            'from Nexa import NXserver\n\n'
            'app = NXserver("{name}")\n\n'
            '@app.get("/")\n'
            'def home():\n'
            '    return "Hello from Nexa!"\n\n'
            'if __name__ == "__main__":\n'
            '    app.run()\n'.format(name=root.name),
            encoding="utf-8",
        )
    typer.echo(f"Initialized Nexa project in {root}")
    typer.echo(f"Runtime resources: {root / '.nova' / 'nexa'}")


@app.command()
def install(
    package: Optional[str] = typer.Argument(None, help="Package to install (PyPI name)."),
    nexa_dep: bool = typer.Option(False, "--nexa", help="Install as a Nexa dependency into .nova/nexa/LIB."),
) -> None:
    """Install dependencies into the project-local environment."""
    root = _project_root_or_exit()
    cfg = load_config(root)
    ensure_layout(root)
    create_venv(root)
    py = venv_python(root)

    # Install Nexa.py itself first.
    nexa_src = find_nexa_source()
    version = _nexa_version_from_config(cfg)
    typer.echo("Installing Nexa.py...")
    if nexa_src:
        subprocess.run(
            [str(py), "-m", "pip", "install", "-e", nexa_src],
            check=True,
            cwd=str(root),
        )
    else:
        subprocess.run(
            [str(py), "-m", "pip", "install", f"Nexa.py=={version}"],
            check=True,
            cwd=str(root),
        )

    if package:
        # Add to config.
        if nexa_dep:
            cfg.setdefault("nexa.dependencies", cfg.get("nexa.dependencies", {}))
            cfg["nexa.dependencies"][package] = "latest"
            write_config(root, cfg)
            rd = runtime_dir(root)
            subprocess.run(
                [str(py), "-m", "pip", "install", "--target", str(rd / "LIB"), package],
                check=True,
                cwd=str(root),
            )
            typer.echo(f"Installed Nexa dependency {package} into .nova/nexa/LIB")
        else:
            cfg.setdefault("dependencies", cfg.get("dependencies", {}))
            cfg["dependencies"][package] = "latest"
            write_config(root, cfg)
            subprocess.run(
                [str(py), "-m", "pip", "install", package],
                check=True,
                cwd=str(root),
            )
            typer.echo(f"Installed {package}")
        return

    # Install all declared dependencies.
    deps = cfg.get("dependencies", {}) or {}
    for name, constraint in deps.items():
        spec = name if constraint in (None, "", "latest") else f"{name}{constraint}"
        typer.echo(f"Installing {name}...")
        subprocess.run(
            [str(py), "-m", "pip", "install", spec],
            check=True,
            cwd=str(root),
        )

    nexa_deps = cfg.get("nexa.dependencies", {}) or {}
    rd = runtime_dir(root)
    for name, constraint in nexa_deps.items():
        spec = name if constraint in (None, "", "latest") else f"{name}{constraint}"
        typer.echo(f"Installing Nexa dependency {name}...")
        subprocess.run(
            [str(py), "-m", "pip", "install", "--target", str(rd / "LIB"), spec],
            check=True,
            cwd=str(root),
        )

    typer.echo("Installation complete.")


@app.command()
def update() -> None:
    """Update project dependencies."""
    root = _project_root_or_exit()
    cfg = load_config(root)
    py = venv_python(root)
    if not py.is_file():
        typer.echo("No virtual environment. Run 'nova install'.", err=True)
        raise typer.Exit(code=1)
    subprocess.run([str(py), "-m", "pip", "install", "--upgrade", "pip"], check=False)
    deps = list((cfg.get("dependencies", {}) or {}).keys())
    if deps:
        subprocess.run([str(py), "-m", "pip", "install", "--upgrade", *deps], check=False)
    typer.echo("Dependencies updated.")


@app.command()
def remove(package: str) -> None:
    """Remove a dependency."""
    root = _project_root_or_exit()
    cfg = load_config(root)
    py = venv_python(root)
    # Try pip uninstall
    if py.is_file():
        subprocess.run([str(py), "-m", "pip", "uninstall", "-y", package], check=False)
    # Remove from config
    changed = False
    if package in (cfg.get("dependencies", {}) or {}):
        del cfg["dependencies"][package]
        changed = True
    if package in (cfg.get("nexa.dependencies", {}) or {}):
        del cfg["nexa.dependencies"][package]
        changed = True
    if changed:
        write_config(root, cfg)
    typer.echo(f"Removed {package}.")


@app.command("list")
def list_deps() -> None:
    """List installed dependencies."""
    root = _project_root_or_exit()
    py = venv_python(root)
    if not py.is_file():
        typer.echo("No virtual environment. Run 'nova install'.", err=True)
        raise typer.Exit(code=1)
    subprocess.run([str(py), "-m", "pip", "list"], check=False)


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def run(
    script: str = typer.Argument(
        "main.py", help="Script name from [scripts], or a Python file to run."
    ),
    args: Optional[list[str]] = typer.Argument(
        None, help="Extra arguments passed to the command."
    ),
) -> None:
    """Run a project script using the project environment."""
    root = _project_root_or_exit()
    cfg = load_config(root)
    scripts = cfg.get("scripts", {}) or {}

    if script in scripts:
        # Values in [scripts] are command lines, not filenames.
        command = scripts[script]
        try:
            code = run_command(root, command, list(args or []))
        except CommandError as exc:
            typer.echo(f"Nova error: {exc}", err=True)
            raise typer.Exit(code=127) from exc
        raise typer.Exit(code=code)

    # Not a configured script: preserve the direct "python file" behaviour.
    path = Path(script)
    if not path.is_absolute():
        path = root / path
    if not path.is_file():
        typer.echo(
            f"Script not found: {script!r} (no [scripts] entry and no such file)",
            err=True,
        )
        raise typer.Exit(code=1)
    py = venv_python(root)
    if not py.is_file():
        typer.echo("No virtual environment. Run 'nova install'.", err=True)
        raise typer.Exit(code=1)
    result = subprocess.run(
        [str(py), str(path), *(args or [])], cwd=str(root), env=project_env(root)
    )
    raise typer.Exit(code=result.returncode)


@app.command("exec", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def exec_cmd(ctx: typer.Context) -> None:
    """Execute a command in the project environment."""
    command = list(ctx.args)
    if not command:
        typer.echo("No command provided.", err=True)
        raise typer.Exit(code=1)
    root = _project_root_or_exit()
    py = venv_python(root)
    if not py.is_file():
        typer.echo("No virtual environment. Run 'nova install'.", err=True)
        raise typer.Exit(code=1)
    import os

    from .project import runtime_dir

    rd = runtime_dir(root)
    env = {**os.environ}
    env["PYTHONPATH"] = os.pathsep.join([str(rd / "LIB"), str(root), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    env["PATH"] = os.pathsep.join([str(rd / "BIN"), os.environ.get("PATH", "")])
    result = subprocess.run(command, cwd=str(root), env=env)
    raise typer.Exit(code=result.returncode)


@app.command()
def doctor() -> None:
    """Diagnose the project environment."""
    root = find_project_root()
    ok = True
    checks = []
    import sys as _sys

    checks.append(("Python version", True, _sys.version.split()[0]))
    if root is None:
        typer.echo("Nova doctor: no nexa.toml found.", err=True)
        raise typer.Exit(code=1)
    checks.append(("nexa.toml", True, str(root / "nexa.toml")))
    try:
        cfg = load_config(root)
        checks.append(("config valid", True, "ok"))
    except Exception as exc:
        checks.append(("config valid", False, str(exc)))
        ok = False
        cfg = {}
    nd = nova_dir(root)
    checks.append((".nova directory", nd.is_dir(), str(nd)))
    rd = runtime_dir(root)
    checks.append(("runtime dir", rd.is_dir(), str(rd)))
    for sub in ("main.nxnexa", "netstat"):
        p = rd / sub
        checks.append((f"runtime file {sub}", p.is_file(), str(p)))
    py = venv_python(root)
    checks.append(("venv python", py.is_file(), str(py)))
    venv_ok = is_valid_venv(root)
    checks.append(("venv valid", venv_ok, "yes" if venv_ok else "no"))
    if py.is_file():
        # pip availability
        try:
            res = subprocess.run(
                [str(py), "-m", "pip", "--version"],
                capture_output=True,
                text=True,
                cwd=str(root),
            )
            if res.returncode == 0:
                checks.append(("pip available", True, res.stdout.strip()))
            else:
                checks.append(("pip available", False, res.stderr.strip()))
                ok = False
        except Exception as exc:
            checks.append(("pip available", False, str(exc)))
            ok = False
        try:
            res = subprocess.run(
                [str(py), "-c", "import Nexa; print(Nexa.__version__ if hasattr(Nexa,'__version__') else 'ok')"],
                capture_output=True,
                text=True,
                cwd=str(root),
            )
            if res.returncode == 0:
                checks.append(("Nexa importable", True, res.stdout.strip()))
                # version check
                required = _nexa_version_from_config(cfg)
                if res.stdout.strip() and res.stdout.strip() != required and res.stdout.strip() != "ok":
                    checks.append(("Nexa version", False, f"installed {res.stdout.strip()}, required {required}"))
                    ok = False
                else:
                    checks.append(("Nexa version", True, required))
            else:
                checks.append(("Nexa importable", False, res.stderr.strip()))
                ok = False
        except Exception as exc:
            checks.append(("Nexa importable", False, str(exc)))
            ok = False
    # deps
    deps = list((cfg.get("dependencies", {}) or {}).keys())
    checks.append(("declared dependencies", True, ", ".join(deps) if deps else "(none)"))
    if py.is_file() and venv_ok:
        try:
            res = subprocess.run(
                [str(py), "-m", "pip", "check"],
                capture_output=True,
                text=True,
                cwd=str(root),
            )
            if res.returncode == 0:
                checks.append(("dependency check", True, "no conflicts"))
            else:
                detail = (res.stdout + res.stderr).strip()
                checks.append(("dependency check", False, detail or "conflicts found"))
                ok = False
        except Exception as exc:
            checks.append(("dependency check", False, str(exc)))
            ok = False

    for name, good, detail in checks:
        status = "OK" if good else "FAIL"
        typer.echo(f"  [{status}] {name}: {detail}")
        if not good:
            ok = False
    if ok:
        typer.echo("All checks passed.")
    else:
        typer.echo("Some checks failed.")
    raise typer.Exit(code=0 if ok else 1)


@app.command()
def clean() -> None:
    """Remove generated files that are safe to regenerate."""
    root = _project_root_or_exit()
    nd = nova_dir(root)
    # Remove temp
    temp = nd / "temp"
    if temp.is_dir():
        for child in temp.iterdir():
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
    # Remove pycaches
    for pycache in root.rglob("__pycache__"):
        if pycache.is_dir():
            shutil.rmtree(pycache, ignore_errors=True)
    typer.echo("Cleaned generated files.")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, version: bool = typer.Option(False, "--version", help="Show version.")) -> None:
    if ctx.invoked_subcommand is not None:
        return
    if version:
        typer.echo(f"Nova {__version__}")
        raise typer.Exit()
    typer.echo(ctx.get_help())


if __name__ == "__main__":
    app()
