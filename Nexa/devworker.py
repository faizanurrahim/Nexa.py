"""Worker process used by ``nexa dev --reload``.

The reloader starts this module with ``python -m Nexa.devworker <file>`` so
the worker target is a normal module entry point: no nested functions, no
pickled application objects, and the same behaviour on Windows and POSIX.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from .devserver import WORKER_ENV_TOKEN, DevError, run_dev_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m Nexa.devworker")
    parser.add_argument("application", help="Python application file to run.")
    parser.add_argument("--host", default=None, help="Host to bind to.")
    parser.add_argument("--port", type=int, default=None, help="Port to listen on.")
    parser.add_argument(
        "--app",
        dest="attribute",
        default=None,
        help="NXserver variable name to use.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    token = os.environ.get(WORKER_ENV_TOKEN)

    try:
        run_dev_app(
            args.application,
            host=args.host,
            port=args.port,
            attribute=args.attribute,
            token=token,
        )
    except DevError as exc:
        print(f"Nexa development error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Nexa development error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
