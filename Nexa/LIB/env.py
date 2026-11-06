
import sys
import tomllib
from pathlib import Path


class __env_init_err__(Exception):
    pass


def __get_lib__bin(script: str):
    try:
        import importlib
        return importlib.import_module(f"nexa.BIN.{script}")
    except ModuleNotFoundError as exc:
        if exc.name == f"nexa.BIN.{script}" or exc.name.startswith("nexa.BIN."):
            raise __env_init_err__(
                f"CDE CNTFNDCRPT: Cannot find nexa.BIN.{script}"
            ) from exc
        raise


def __env_setup__():
    cwd = Path.cwd()
    cwd_str = str(cwd)

    if cwd_str not in sys.path:
        sys.path.insert(0, cwd_str)

    config_path = cwd / "nexa.toml"

    if not config_path.is_file():
        raise __env_init_err__(
            f"CDE CNTFNDTOML: nexa.toml not found in {cwd}"
        )

    try:
        with config_path.open("rb") as file:
            return tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        raise __env_init_err__(
            f"CDE INVALIDTOML: {exc}"
        ) from exc
