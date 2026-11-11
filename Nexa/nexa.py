
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer


class NexaError(Exception):
    """Base error class for Nexa.py."""


__version__ = "0.5.0-BETA"
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


if __name__ == "__main__":
    app()
