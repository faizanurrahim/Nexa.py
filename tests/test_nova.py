"""Tests for the Nova package manager."""

import subprocess
import sys

import pytest


def _nova(args, cwd):
    # Prefer installed entry point.
    return subprocess.run(["nova", *args], cwd=str(cwd), capture_output=True, text=True)


@pytest.fixture
def project(tmp_path):
    r = _nova(["init"], tmp_path)
    assert r.returncode == 0, r.stderr
    return tmp_path


def test_fresh_init_creates_real_venv(project):
    venv = project / ".nova" / "venv"
    assert venv.is_dir()
    if sys.platform.startswith("win"):
        py = venv / "Scripts" / "python.exe"
    else:
        py = venv / "bin" / "python"
    assert py.is_file()
    assert (venv / "pyvenv.cfg").is_file()
    res = subprocess.run([str(py), "--version"], capture_output=True, text=True)
    assert res.returncode == 0


def test_doctor_after_init_succeeds_for_venv(project):
    r = _nova(["doctor"], project)
    # Nexa may not be installed yet, but venv checks should pass.
    assert "venv valid: yes" in r.stdout


def test_install_repairs_empty_venv(tmp_path):
    _nova(["init"], tmp_path)
    venv = tmp_path / ".nova" / "venv"
    # Empty it.
    import shutil

    for child in venv.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    assert not any(venv.iterdir())
    r = _nova(["install"], tmp_path)
    assert r.returncode == 0, r.stderr
    if sys.platform.startswith("win"):
        py = venv / "Scripts" / "python.exe"
    else:
        py = venv / "bin" / "python"
    assert py.is_file()


def test_dependency_install_location(tmp_path):
    _nova(["init"], tmp_path)
    r = _nova(["install", "requests"], tmp_path)
    assert r.returncode == 0, r.stderr
    venv = tmp_path / ".nova" / "venv"
    if sys.platform.startswith("win"):
        py = venv / "Scripts" / "python.exe"
    else:
        py = venv / "bin" / "python"
    res = subprocess.run([str(py), "-c", "import requests; print(requests.__file__)"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "site-packages" in res.stdout


def test_paths_with_spaces(tmp_path):
    spaced = tmp_path / "my project"
    spaced.mkdir()
    r = _nova(["init"], spaced)
    assert r.returncode == 0, r.stderr
    venv = spaced / ".nova" / "venv"
    if sys.platform.startswith("win"):
        py = venv / "Scripts" / "python.exe"
    else:
        py = venv / "bin" / "python"
    assert py.is_file()
