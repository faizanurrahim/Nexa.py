"""Regression tests for ``nova run`` command resolution."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from nova.commands import CommandError, project_env, resolve_executable, split_command


def _nova(args, cwd):
    return subprocess.run(["nova", *args], cwd=str(cwd), capture_output=True, text=True)


def _toml_string(value: str) -> str:
    # JSON string escaping is valid for TOML basic strings.
    return json.dumps(value)


def _write_project(root: Path, scripts: dict[str, str]) -> None:
    lines = [
        "[project]",
        'name = "tmp"',
        'version = "1.0.0"',
        'nexa = "1.0.0"',
        "",
        "[dependencies]",
        "",
        "[nexa.dependencies]",
        "",
        "[scripts]",
    ]
    for key, value in scripts.items():
        lines.append(f"{key} = {_toml_string(value)}")
    (root / "nexa.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _install_fake_nexa(root: Path) -> None:
    """Create a fake ``nexa`` executable inside the project virtualenv."""
    recorder = root / "recorder.py"
    recorder.write_text(
        "import json, os, sys\n"
        "with open(os.path.join(os.getcwd(), 'record.json'), 'w', encoding='utf-8') as f:\n"
        "    json.dump({'argv': sys.argv[1:], 'cwd': os.getcwd()}, f)\n"
        "if sys.argv[1:2] == ['fail']:\n"
        "    sys.exit(7)\n",
        encoding="utf-8",
    )
    venv = root / ".nova" / "venv"
    if sys.platform.startswith("win"):
        bin_dir = venv / "Scripts"
        bin_dir.mkdir(parents=True)
        (bin_dir / "nexa.cmd").write_text(
            "@echo off\r\n"
            f'"{sys.executable}" "{recorder}" %*\r\n',
            encoding="utf-8",
        )
    else:
        bin_dir = venv / "bin"
        bin_dir.mkdir(parents=True)
        launcher = bin_dir / "nexa"
        launcher.write_text(
            "#!/bin/sh\n"
            f'exec "{sys.executable}" "{recorder}" "$@"\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    _write_project(
        root,
        {
            "dev": "nexa dev main.py",
            "start": "nexa run main.py",
            "withargs": "nexa one two three",
            "quoted": 'nexa "hello world" --flag=value',
            "fail": "nexa fail",
            "missing": "definitely-not-a-real-executable-xyz arg",
        },
    )
    _install_fake_nexa(root)
    return root


def _record(root: Path) -> dict:
    return json.loads((root / "record.json").read_text(encoding="utf-8"))


def test_run_dev_executes_nexa_dev(project):
    result = _nova(["run", "dev"], project)
    assert result.returncode == 0, result.stderr
    assert _record(project)["argv"] == ["dev", "main.py"]


def test_run_start_executes_nexa_run(project):
    result = _nova(["run", "start"], project)
    assert result.returncode == 0, result.stderr
    assert _record(project)["argv"] == ["run", "main.py"]


def test_run_command_with_arguments(project):
    result = _nova(["run", "withargs"], project)
    assert result.returncode == 0, result.stderr
    assert _record(project)["argv"] == ["one", "two", "three"]


def test_run_command_with_quoted_arguments(project):
    result = _nova(["run", "quoted"], project)
    assert result.returncode == 0, result.stderr
    assert _record(project)["argv"] == ["hello world", "--flag=value"]


def test_run_extra_arguments_are_forwarded(project):
    result = _nova(["run", "dev", "--port", "9000"], project)
    assert result.returncode == 0, result.stderr
    assert _record(project)["argv"] == ["dev", "main.py", "--port", "9000"]


def test_missing_executable_reports_clear_error(project):
    result = _nova(["run", "missing"], project)
    assert result.returncode == 127
    assert "definitely-not-a-real-executable-xyz" in result.stderr
    assert "not found" in result.stderr.lower()
    assert not (project / "record.json").exists()


def test_script_exit_code_is_propagated(project):
    result = _nova(["run", "fail"], project)
    assert result.returncode == 7


def test_execution_uses_project_root_as_cwd(project):
    result = _nova(["run", "dev"], project)
    assert result.returncode == 0, result.stderr
    assert Path(_record(project)["cwd"]).resolve() == project.resolve()


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows executable resolution")
def test_windows_exe_and_cmd_resolution(project):
    env = project_env(project)
    # .cmd scripts from the project venv are discovered.
    resolved = resolve_executable("nexa", project, env)
    assert resolved.lower().endswith((".cmd", ".bat", ".exe"))


def test_split_command_preserves_quotes():
    tokens = split_command('tool "two words" --flag=value')
    assert tokens == ["tool", "two words", "--flag=value"]


def test_empty_command_is_rejected():
    with pytest.raises(CommandError):
        split_command("   ")
