
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer


class NexaError(Exception):
    """Base error class for Nexa.py."""


__version__ = "1.0.0"


app = typer.Typer(
    name="nexa",
    help="Nexa.py — Python development platform.",
    add_completion=False,
    no_args_is_help=True,
)


def get_env():
    """Initialize the Nexa environment from the current project."""
    cwd = str(Path.cwd())

    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    try:
        from .env import Env
        return Env().dump()
    except ModuleNotFoundError as exc:
        raise NexaError(
            "CDE Env.NEXA ERR"
        ) from exc


@app.command()
def doctor():
    """Verify the Nexa.py installation and environment."""
    from .log import info as _log_info

    _log_info("Running Nexa doctor checks...")

    checks: list[tuple[str, bool, str]] = []

    # Python version.
    py_version = sys.version.split()[0]
    checks.append(("Python version", True, py_version))

    # Nexa version.
    checks.append(("Nexa version", True, __version__))

    # Typer availability.
    try:
        import typer  # noqa: F401
        checks.append(("Typer", True, typer.__version__))
    except ImportError:
        checks.append(("Typer", False, "not installed"))

    # Writable cache directory.
    cache_dir = Path.home() / ".nexa" / "cache"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        test_file = cache_dir / ".doctor_test"
        test_file.write_text("ok")
        test_file.unlink()
        checks.append(("Cache directory", True, str(cache_dir)))
    except OSError as exc:
        checks.append(("Cache directory", False, str(exc)))

    # Config file presence.
    config_path = Path.cwd() / "nexa.toml"
    if config_path.is_file():
        checks.append(("Project config", True, str(config_path)))
    else:
        checks.append(("Project config", True, "not present (optional)"))

    # Environment file presence.
    env_path = Path.cwd() / ".env.json"
    if env_path.is_file():
        checks.append(("Environment file", True, str(env_path)))
    else:
        checks.append(("Environment file", True, "not present (optional)"))

    # Report.
    all_ok = True
    for name, ok, detail in checks:
        status = "OK" if ok else "FAIL"
        _log_info(f"  [{status}] {name}: {detail}")
        if not ok:
            all_ok = False

    if all_ok:
        _log_info("All checks passed.")
    else:
        _log_info("Some checks failed. Review the items above.")

    raise typer.Exit(code=0 if all_ok else 1)


@app.command()
def info():
    """Show Nexa.py runtime information."""
    from .log import info as _log_info

    _log_info(f"Nexa.py {__version__}")
    _log_info(f"Python {sys.version.split()[0]} ({sys.executable})")
    _log_info(f"Platform: {sys.platform}")
    _log_info(f"Working directory: {Path.cwd()}")

    # Show loaded commands.
    _log_info("\nCommands:")
    for cmd in app.registered_commands:
        if cmd.name:
            _log_info(f"  nexa {cmd.name}")

    raise typer.Exit(code=0)


@app.callback(invoke_without_command=True)
def main(

    ctx: typer.Context,

    code: Optional[str] = typer.Option(
        None, "--code", "-c",
        help="Execute code in the Nexa environment.",
    ),
    noenv: bool = typer.Option(
        False, "--noenv",
        help="Skip Nexa environment initialization.",
    ),
    version: bool = typer.Option(
        False, "--version",
        help="Show the Nexa.py version.",
    ),
       
):
    """Nexa.py command-line interface."""

    # Let subcommands such as "run" handle their own arguments.
    if ctx.invoked_subcommand is not None:
        return

    if version:
        typer.echo(f"Nexa.py {__version__}")
        raise typer.Exit()





    if code is not None:
        try:
            namespace = {"__name__": "__main__"}

            if not noenv:
                namespace["Metadata"] = get_env()

            exec(compile(code, "<nexa-inline>", "exec"), namespace)

        except NexaError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=0) from exc

        return

    # Display help if no command or inline code was supplied.
    typer.echo(ctx.get_help())



@app.command()
def run(
    script: str = typer.Argument(
        ...,
        help="Script alias or filename, e.g. dev:desktop or main.nx.",
    ),
    noenv: bool = typer.Option(
        False,
        "--noenv",
        help="Skip Nexa environment initialization.",
    ),
):
    """Run a Nexa script or target."""
    _execute_script(script, noenv)


@app.command("exec")
def exec_script(
    script: str = typer.Argument(
        ...,
        help="NXLang file (main, main.nx) or Nexa script alias.",
    ),
    args: list[str] = typer.Argument(
        None,
        help="Arguments passed to the NXLang program.",
    ),
    noenv: bool = typer.Option(
        False,
        "--noenv",
        help="Skip Nexa environment initialization.",
    ),
):
    """Execute an NXLang source file or a standalone Nexa script."""
    if _execute_nxlang(script, list(args or [])):
        return
    _execute_script(script, noenv)


def _resolve_nxlang_path(script: str) -> Optional[Path]:
    """Return the ``.nx`` file for *script*, or ``None`` if it is not NXLang."""
    path = Path(script)
    if path.suffix == ".nx":
        return path if path.is_file() else None
    candidate = path.with_suffix(".nx")
    return candidate if candidate.is_file() else None


def _execute_nxlang(script: str, args: list[str]) -> bool:
    """Run *script* through NXLang when it names an ``.nx`` file.

    Returns ``True`` when the script was executed as NXLang source and
    ``False`` when the caller should use the legacy script runner.
    """
    target = _resolve_nxlang_path(script)
    if target is None:
        if script.endswith(".nx"):
            typer.echo(f"NXLang error: source file not found: {script}", err=True)
            raise typer.Exit(code=1)
        return False

    from .nxlang import ERR as NXLangERR
    from .nxlang import run_file

    try:
        run_file(target, args=args)
    except NXLangERR as exc:
        typer.echo(f"NXLang error: {exc.format()}", err=True)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        typer.echo("\nNXLang execution interrupted.", err=True)
        raise typer.Exit(code=130)
    return True


def _execute_script(script: str, noenv: bool) -> None:
    try:
        from .NEXA.nexa_stp import AbordErr, ScriptError, Scripts

        Scripts().toexec(script, noenv=noenv)

    except AbordErr as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=130) from exc

    except ScriptError as exc:
        typer.echo(f"Nexa error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    except KeyboardInterrupt:
        typer.echo("\nNexa execution interrupted.", err=True)
        raise typer.Exit(code=130)


@app.command("dev")
def dev(
    application: str = typer.Argument(
        ...,
        help="Python application file to run, e.g. demo.py.",
    ),
    host: Optional[str] = typer.Option(
        None,
        "--host",
        "-H",
        help="Host to bind to (overrides the application).",
    ),
    port: Optional[int] = typer.Option(
        None,
        "--port",
        "-p",
        help="Port to listen on (overrides the application).",
    ),
    reload: bool = typer.Option(
        True,
        "--reload/--no-reload",
        help="Restart the server when Python files change (default: on).",
    ),
    app_name: Optional[str] = typer.Option(
        None,
        "--app",
        help="NXserver variable to use when the file defines several.",
    ),
    debug_token: Optional[str] = typer.Option(
        None,
        "--devtools-token",
        help="Fixed DevTools token. A secure token is generated when omitted.",
    ),
):
    """Run a Nexa application in development mode with DevTools."""
    from .devserver import DevError, run_dev_app, serve_with_reload

    try:
        if reload:
            serve_with_reload(
                application,
                host=host,
                port=port,
                attribute=app_name,
                token=debug_token,
            )
        else:
            run_dev_app(
                application,
                host=host,
                port=port,
                attribute=app_name,
                token=debug_token,
            )
    except DevError as exc:
        typer.echo(f"Nexa development error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        typer.echo(f"Nexa development error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        typer.echo("\nServer stopped.", err=True)
        raise typer.Exit(code=130)


@app.command("routes")
def list_routes(script: str = typer.Argument(
    ...,
    help="Script alias or filename to load before listing routes.",
)):
    """Load a script and print its registered routes."""
    from Nexa import NXserver

    try:
        # Execute the script to register its routes.
        _execute_script(script, noenv=False)
    except Exception as exc:
        typer.echo(f"Failed to load script: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    # Find the server instance that was created by the script.
    # We look through all NXserver instances that have been created.
    # For simplicity, we assume the script created exactly one server.
    # A more robust approach would require the script to expose its server.
    typer.echo("\nRegistered routes:")
    typer.echo("-" * 60)

    # Try to get routes from the most recently created server.
    # This is a heuristic; production use should expose the server explicitly.
    import gc
    servers = []
    for obj in gc.get_objects():
        if isinstance(obj, NXserver):
            servers.append(obj)

    if not servers:
        typer.echo("No server found. Make sure your script creates an NXserver.")
        raise typer.Exit(code=1)

    server = servers[-1]  # most recently created

    if not server.registered_routes:
        typer.echo("No routes registered.")
        return

    for path, methods, handler_name in server.registered_routes:
        typer.echo(f"  {path:<40} {','.join(methods):<12} {handler_name}")

    if server.registered_middleware:
        typer.echo("\nMiddleware:")
        typer.echo("-" * 60)
        for name, priority in server.registered_middleware:
            typer.echo(f"  {name:<40} priority={priority}")


if __name__ == "__main__":
    app()
