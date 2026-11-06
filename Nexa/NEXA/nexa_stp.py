
from pathlib import Path
import runpy
import sys
import tomllib


class AbordErr(Exception):
    pass


class ScriptError(Exception):
    pass


def getYNinput(text: str) -> bool:
    while True:
        try:
            inp = input(text).strip().lower()
        except KeyboardInterrupt:
            print()
            continue

        if inp == "y":
            return True
        if inp == "n":
            return False
        print("Please enter y or n.")


class Scripts:
    def __init__(self, config_path="nexa.toml"):
        self.project_dir = Path.cwd().resolve()
        self.config_path = self.project_dir / config_path

        if not self.config_path.is_file():
            raise ScriptError(
                f"Nexa configuration not found: {self.config_path}"
            )

        try:
            with self.config_path.open("rb") as file:
                self.config = tomllib.load(file)
        except tomllib.TOMLDecodeError as exc:
            raise ScriptError(f"Invalid nexa.toml: {exc}") from exc

        self.scripts = self.config.get("scripts", {})

    def resolve(self, script_name: str) -> Path:
        # Use an alias if one exists; otherwise treat it as a file path.
        target = self.scripts.get(script_name, script_name)
        path = Path(target)

        if not path.is_absolute():
            path = self.project_dir / path

        path = path.resolve()

        if not path.is_file():
            available = ", ".join(self.scripts) or "(none)"
            raise ScriptError(
                f"Script file not found: {path}\n"
                f"Configured targets: {available}"
            )

        if path.suffix.lower() not in {".py", ".nx"}:
            raise ScriptError(f"Unsupported script type: {path.suffix}")

        return path

    def toexec(self, script_name: str, noenv: bool = False):
        project = str(self.project_dir)
        if project not in sys.path:
            sys.path.insert(0, project)

        path = self.resolve(script_name)

        if not noenv:
            try:
                from LIB.env import __env_setup__
                __env_setup__()
            except Exception as exc:
                raise ScriptError(
                    f"Environment initialization failed: {exc}"
                ) from exc

        sys.argv = [str(path)]

        def execute():
            if path.suffix.lower() == ".py":
                runpy.run_path(str(path), run_name="__main__")
                return

            try:
                from compiler import compile_file
            except ImportError as exc:
                raise ScriptError(
                    f"Cannot import compile_file from compiler.py: {exc}"
                ) from exc

            source = compile_file(path)
            code = compile(source, str(path), "exec")
            namespace = {
                "__name__": "__main__",
                "__file__": str(path),
                "__package__": None,
            }
            exec(code, namespace)

        while True:
            try:
                execute()
                return
            except KeyboardInterrupt:
                print()
                if getYNinput("Are you sure you want to abort? [y/n]: "):
                    raise AbordErr("Execution aborted by user.")
                print("Resuming execution...")
