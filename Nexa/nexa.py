
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
class NexaError(Exception):
    """Base error class for Nexa.py."""


__version__ = "0.0.1-ALPHA"
def __err_fix__(CDE: str):
    """Get a fix for an error code."""
    fixes = {
        "0": "Try running with the --noenv flag.",
        "1": "The CDE might be invalid. Check it and try again.",
    }

    fix = fixes.get(CDE)

    if fix is None:
        raise NexaError(f"ERR : CDE 1 : {CDE}")

    typer.echo(f"FIX FOR CDE {CDE}: {fix}")



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
        from .LIB import env
        return env.__env_setup__()
    except ModuleNotFoundError as exc:
        raise NexaError(
            f"CDE Env.NEXA ERR"
        ) from exc


@app.callback(invoke_without_command=True)
def main(

    ctx: typer.Context,
    errors: bool = typer.Option(
        False, "--errors", "-e",
        help="Show all Nexa error codes.",
    ),
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
        fixerr: Optional[str] = typer.Option(
    None,
    "--fixerr",
    "-fe",
    help="Show a suggested fix for an error code.",
    ),
):
    """Nexa.py command-line interface."""

    # Let subcommands such as "run" handle their own arguments.
    if ctx.invoked_subcommand is not None:
        return

    if version:
        typer.echo(f"Nexa.py {__version__}")
        raise typer.Exit()

    if errors:
        typer.echo("0:ENV.NEXA_ERR")
        typer.echo("1:CDE.UNKN_ERR")
        raise typer.Exit()
    if fixerr is not None:
        try:
            __err_fix__(fixerr)
        except NexaError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc

        raise typer.Exit()
    if code is not None:
        try:
            namespace = {"__name__": "__main__"}

            if not noenv:
                namespace["Mtdata"] = get_env()

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

    try:
        from .NEXA.nexa_stp import Scripts, ScriptError, AbordErr

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


if __name__ == "__main__":
    app()
