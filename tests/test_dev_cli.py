import sys
import types

import pytest
from typer.testing import CliRunner

import Nexa.nxserver as nxserver_module
from Nexa import devserver
from Nexa.devtools import DevTools
from Nexa.nexa import app as cli

APP_SOURCE = """\
from Nexa import NXserver

app = NXserver("demo-app", port=3000)

@app.get("/")
def home():
    return "Hello from Nexa!"
"""


def write_app(tmp_path, source=APP_SOURCE, name="demo.py"):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


@pytest.fixture()
def fake_run(monkeypatch):
    calls = []

    def run(self):
        calls.append(self)

    monkeypatch.setattr(nxserver_module.NXserver, "run", run)
    return calls


def invoke(*args):
    return CliRunner().invoke(cli, list(args))


def combined_output(result):
    return result.output + getattr(result, "stderr", "")


# ---------------------------------------------------------------------------
# Application discovery
# ---------------------------------------------------------------------------


def test_discovers_conventional_app(tmp_path):
    loaded = devserver.load_application(write_app(tmp_path))

    assert loaded.attribute == "app"
    assert loaded.server.name == "demo-app"


def test_discovers_application_variable_name(tmp_path):
    path = write_app(
        tmp_path, 'from Nexa import NXserver\napplication = NXserver("named")\n'
    )

    loaded = devserver.load_application(path)

    assert loaded.attribute == "application"
    assert loaded.server.name == "named"


def test_discovers_single_custom_variable(tmp_path):
    path = write_app(tmp_path, 'from Nexa import NXserver\nmy_thing = NXserver("custom")\n')

    loaded = devserver.load_application(path)

    assert loaded.attribute == "my_thing"
    assert loaded.server.name == "custom"


def test_multiple_servers_require_explicit_selection(tmp_path):
    path = write_app(
        tmp_path,
        'from Nexa import NXserver\napp = NXserver("one")\nadmin = NXserver("two")\n',
    )

    with pytest.raises(devserver.AppDiscoveryError, match="Multiple NXserver"):
        devserver.load_application(path)


def test_multiple_servers_can_be_selected(tmp_path):
    path = write_app(
        tmp_path,
        'from Nexa import NXserver\napp = NXserver("one")\nadmin = NXserver("two")\n',
    )

    loaded = devserver.load_application(path, "admin")

    assert loaded.attribute == "admin"
    assert loaded.server.name == "two"


def test_unconventional_name_must_be_selected(tmp_path):
    path = write_app(
        tmp_path, 'from Nexa import NXserver\napp = NXserver("one")\nzzz = NXserver("two")\n'
    )

    with pytest.raises(devserver.AppDiscoveryError, match="Multiple NXserver"):
        devserver.load_application(path)

    loaded = devserver.load_application(path, "zzz")
    assert loaded.server.name == "two"


def test_missing_server_is_reported(tmp_path):
    path = write_app(tmp_path, "value = 1\n")

    with pytest.raises(devserver.AppDiscoveryError, match="No NXserver"):
        devserver.load_application(path)


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(devserver.AppLoadError, match="not found"):
        devserver.load_application(tmp_path / "absent.py")


def test_import_errors_are_reported(tmp_path):
    path = write_app(tmp_path, "this is not python\n")

    with pytest.raises(devserver.AppLoadError, match="Failed to import"):
        devserver.load_application(path)


def test_main_guard_does_not_start_the_server(tmp_path, fake_run):
    path = write_app(
        tmp_path,
        'from Nexa import NXserver\napp = NXserver("guard")\n'
        'if __name__ == "__main__":\n    app.run()\n',
    )

    loaded = devserver.load_application(path)

    assert loaded.server.name == "guard"
    assert fake_run == []


def test_module_import_side_effects_are_preserved(tmp_path):
    path = write_app(
        tmp_path,
        'from Nexa import NXserver\nmarker = "loaded"\napp = NXserver("side")\n',
    )

    loaded = devserver.load_application(path)

    assert loaded.module.marker == "loaded"


# ---------------------------------------------------------------------------
# `nexa dev --no-reload`
# ---------------------------------------------------------------------------


def test_dev_no_reload_starts_discovered_server(tmp_path, fake_run):
    result = invoke("dev", str(write_app(tmp_path)), "--no-reload")
    output = combined_output(result)

    assert result.exit_code == 0, output
    assert len(fake_run) == 1
    server = fake_run[0]
    assert server.name == "demo-app"
    assert server.debug is False
    assert isinstance(server.devtools, DevTools)
    assert server._mount is not None
    assert output.count("DevTools token:") == 1
    assert "Application: " in output
    assert "http://127.0.0.1:3000/__nexa__/" in output
    assert "Starting development server..." in output


def test_dev_token_authenticates_dashboard(tmp_path, fake_run):
    result = invoke("dev", str(write_app(tmp_path)), "--no-reload")
    assert result.exit_code == 0, combined_output(result)

    server = fake_run[0]
    token = server.devtools.token
    request = types.SimpleNamespace(
        headers={"X-DevTools-Token": token}, cookies={}
    )

    assert token
    assert server.devtools._authenticated(request) is True


def test_dev_accepts_fixed_token(tmp_path, fake_run):
    result = invoke(
        "dev",
        str(write_app(tmp_path)),
        "--no-reload",
        "--devtools-token",
        "fixed-token",
    )
    output = combined_output(result)

    assert result.exit_code == 0, output
    assert fake_run[0].devtools.token == "fixed-token"
    assert "fixed-token" in output


def test_dev_port_and_host_override_the_application(tmp_path, fake_run):
    result = invoke(
        "dev",
        str(write_app(tmp_path)),
        "--no-reload",
        "--port",
        "4321",
        "--host",
        "localhost",
    )

    assert result.exit_code == 0, combined_output(result)
    assert fake_run[0].port == 4321
    assert fake_run[0].host == "localhost"


def test_dev_selects_named_server(tmp_path, fake_run):
    path = write_app(
        tmp_path,
        'from Nexa import NXserver\napp = NXserver("one")\nadmin = NXserver("two")\n',
    )

    result = invoke("dev", str(path), "--no-reload", "--app", "admin")

    assert result.exit_code == 0, combined_output(result)
    assert fake_run[0].name == "two"


def test_dev_missing_file_exits_with_a_clear_error(tmp_path):
    result = invoke("dev", str(tmp_path / "nope.py"), "--no-reload")
    output = combined_output(result)

    assert result.exit_code == 1
    assert "not found" in output


def test_dev_discovery_failure_exits_with_a_clear_error(tmp_path):
    path = write_app(tmp_path, "value = 1\n")

    result = invoke("dev", str(path), "--no-reload")
    output = combined_output(result)

    assert result.exit_code == 1
    assert "No NXserver" in output


def test_production_servers_do_not_enable_devtools(tmp_path):
    """An application's server only gains DevTools through the dev workflow."""
    source = 'from Nexa import NXserver\napp = NXserver("prod")\n'
    loaded = devserver.load_application(write_app(tmp_path, source))

    assert loaded.server._devtools is None
    with pytest.raises(AttributeError):
        _ = loaded.server.devtools


# ---------------------------------------------------------------------------
# Reload behaviour
# ---------------------------------------------------------------------------


def test_reload_requires_watchfiles(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "watchfiles", None)

    result = invoke("dev", str(write_app(tmp_path)))
    output = combined_output(result)

    assert result.exit_code == 1
    assert "Automatic reload requires watchfiles." in output
    assert "python -m pip install watchfiles" in output


def test_worker_command_uses_module_entry_point(tmp_path):
    path = write_app(tmp_path).resolve()

    command = devserver.build_worker_command(
        path, host="127.0.0.1", port=4000, attribute="app"
    )

    assert command[:3] == [sys.executable, "-m", "Nexa.devworker"]
    assert str(path) in command
    assert command[command.index("--port") + 1] == "4000"
    assert command[command.index("--app") + 1] == "app"


def test_worker_startup_uses_an_argument_list(monkeypatch):
    captured = {}

    class FakeProcess:
        def poll(self):
            return 0

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    def fake_popen(command, env=None, **kwargs):
        captured["command"] = command
        captured["env"] = env
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(devserver.subprocess, "Popen", fake_popen)

    devserver.start_worker(
        [sys.executable, "-m", "Nexa.devworker", "demo.py"], {"A": "1"}
    )

    assert isinstance(captured["command"], list)
    assert captured["env"] == {"A": "1"}
    assert captured["kwargs"].get("shell", False) is False


def test_stop_worker_terminates_a_running_child():
    state = {"running": True, "terminated": False}

    class FakeProcess:
        def poll(self):
            return None if state["running"] else 0

        def terminate(self):
            state["terminated"] = True
            state["running"] = False

        def wait(self, timeout=None):
            return 0

    devserver.stop_worker(FakeProcess())

    assert state["terminated"] is True


def test_stop_worker_ignores_a_finished_child():
    class FakeProcess:
        def poll(self):
            return 0

        def terminate(self):
            raise AssertionError("finished children must not be terminated")

    devserver.stop_worker(FakeProcess())


def test_reload_filter_ignores_caches_and_non_python_files():
    assert devserver.should_reload(None, "app.py") is True
    assert devserver.should_reload(None, "app.log") is False
    assert devserver.should_reload(None, "pkg/__pycache__/app.py") is False
    assert devserver.should_reload(None, ".venv/lib/site.py") is False


def test_worker_uses_token_from_environment(tmp_path, monkeypatch):
    from Nexa import devworker

    seen = {}
    monkeypatch.setattr(
        devworker, "run_dev_app", lambda path, **kwargs: seen.update(kwargs)
    )
    monkeypatch.setenv(devserver.WORKER_ENV_TOKEN, "reload-token")

    exit_code = devworker.main([str(write_app(tmp_path))])

    assert exit_code == 0
    assert seen["token"] == "reload-token"


def test_worker_reports_development_errors(tmp_path, monkeypatch):
    from Nexa import devworker

    def broken(path, **kwargs):
        raise devserver.AppLoadError("Cannot load that application.")

    monkeypatch.setattr(devworker, "run_dev_app", broken)

    exit_code = devworker.main([str(write_app(tmp_path))])

    assert exit_code == 1
