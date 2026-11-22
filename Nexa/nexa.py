
from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path
from typing import Optional

import typer


class NexaError(Exception):
    """Base error class for Nexa.py."""


__version__ = "0.7.0"


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
        help="Script alias or filename, e.g. main.",
    ),
    noenv: bool = typer.Option(
        False,
        "--noenv",
        help="Skip Nexa environment initialization.",
    ),
):
    """Execute a standalone Nexa script."""
    _execute_script(script, noenv)


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
    port: int = typer.Option(3000, "--port", "-p", help="Port to listen on."),
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="Host to bind to."),
    reload: bool = typer.Option(
        True,
        "--reload/--no-reload",
        help="Watch for file changes and restart the server.",
    ),
    debug_token: Optional[str] = typer.Option(
        None,
        "--devtools-token",
        help="Token for the DevTools dashboard. If not set, a random token is generated.",
    ),
):
    """Start the Nexa development server with auto-reload.

    The server runs in debug mode with the DevTools dashboard enabled.
    When --reload is active (the default), the server watches for file
    changes and restarts automatically.
    """
    from Nexa import NXserver

    app_server = NXserver("dev", debug=True, port=port, host=host)

    if debug_token is not None:
        app_server.devtools.token = debug_token

    print(f"\nDevTools token: {app_server.devtools.token}")
    print(f"DevTools dashboard: http://{host}:{port}/__nexa__/\n")

    if reload:
        import multiprocessing

        import watchfiles

        def _run_server() -> None:
            try:
                app_server.run()
            except KeyboardInterrupt:
                pass

        ctx = multiprocessing.get_context("spawn")
        proc = ctx.Process(target=_run_server, daemon=True)
        proc.start()

        try:
            watchfiles.watch(
                str(Path.cwd()),
                watch_filter=watchfiles.PythonFilter(),
                debounce=300,
                on_iter=lambda change_queue: _reload_on_changes(change_queue, proc, _run_server),
            )
        except KeyboardInterrupt:
            proc.terminate()
            proc.join(timeout=5)
            print("\nServer stopped.")
    else:
        try:
            app_server.run()
        except KeyboardInterrupt:
            print("\nServer stopped.")


def _reload_on_changes(change_queue, proc, run_server_fn) -> None:
    """Reload the server when Python files change."""
    changes = list(change_queue)
    if changes:
        print(f"\nChanges detected in: {[str(c[0]) for c in changes]}")
        print("Restarting server...\n")
        proc.terminate()
        proc.join(timeout=5)
        ctx = multiprocessing.get_context("spawn")
        new_proc = ctx.Process(target=run_server_fn, daemon=True)
        new_proc.start()
        return new_proc


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
