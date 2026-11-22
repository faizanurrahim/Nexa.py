import time

import pytest

from Nexa import NXserver
from Nexa.devtools import DevTools, _DevToolsMount


class StubRequest:
    """Minimal stand-in for a Nexa Request in DevTools unit tests."""

    def __init__(
        self,
        path="/__nexa__/",
        method="GET",
        headers=None,
        cookie_header="",
        form=None,
        remote_addr="127.0.0.1",
    ):
        self.path = path
        self.method = method
        self.headers = headers or {}
        self._cookie_header = cookie_header
        self._form = form or {}
        self.remote_addr = remote_addr

    @property
    def cookies(self):
        parsed = {}
        for part in self._cookie_header.split(";"):
            if "=" in part:
                key, _, value = part.partition("=")
                parsed[key.strip()] = value.strip()
        return parsed

    @property
    def form(self):
        return self._form


@pytest.fixture()
def devtools():
    instance = DevTools(NXserver("DevToolsAuth"))
    instance.token = "known-token"
    return instance


@pytest.fixture()
def mount(devtools):
    return _DevToolsMount(devtools)


def session_from(response):
    """Return (session_id, raw Set-Cookie header) from a dispatch result."""
    raw = response[2].get("Set-Cookie", "")
    cookie = raw.split(";", 1)[0]
    _, _, session_id = cookie.partition("=")
    return session_id, raw


def cookie_request(devtools, session_id, path="/__nexa__/"):
    return StubRequest(
        path=path,
        cookie_header=f"{devtools.SESSION_COOKIE}={session_id}",
    )


# ---------------------------------------------------------------------------
# Programmatic authentication
# ---------------------------------------------------------------------------


def test_header_token_still_authenticates(mount):
    response = mount.dispatch(
        StubRequest(headers={"X-DevTools-Token": "known-token"})
    )
    assert response[1] == 200
    assert b"Errors (" in response[0]


def test_missing_credentials_get_forbidden_json(mount):
    response = mount.dispatch(StubRequest(path="/__nexa__/api"))
    assert response[1] == 403
    assert b"forbidden" in response[0]


def test_browser_without_session_gets_login_page(mount):
    response = mount.dispatch(StubRequest())
    assert response[1] == 200
    assert b"name='token'" in response[0]
    assert b"Errors (" not in response[0]


# ---------------------------------------------------------------------------
# Browser sessions
# ---------------------------------------------------------------------------


def test_login_creates_hardened_session_cookie(mount, devtools):
    response = mount.dispatch(
        StubRequest(
            path="/__nexa__/login",
            method="POST",
            form={"token": "known-token"},
        )
    )

    assert response[1] == 303
    assert response[2]["Location"] == "/__nexa__/"
    session_id, raw = session_from(response)
    assert session_id
    assert session_id != devtools.token
    assert devtools.token not in raw
    assert "HttpOnly" in raw
    assert "SameSite=Strict" in raw
    assert "Path=/__nexa__" in raw
    assert "Max-Age=" in raw


def test_session_cookie_authenticates_the_dashboard(mount, devtools):
    login = mount.dispatch(
        StubRequest(path="/__nexa__/login", method="POST", form={"token": "known-token"})
    )
    session_id, _ = session_from(login)

    response = mount.dispatch(cookie_request(devtools, session_id))

    assert response[1] == 200
    assert b"Errors (" in response[0]


def test_wrong_token_does_not_create_a_session(mount):
    response = mount.dispatch(
        StubRequest(path="/__nexa__/login", method="POST", form={"token": "wrong"})
    )

    assert response[1] == 200
    assert b"Invalid DevTools token" in response[0]
    assert "Set-Cookie" not in response[2]


def test_login_rotates_session_identifiers(mount):
    first = mount.dispatch(
        StubRequest(path="/__nexa__/login", method="POST", form={"token": "known-token"})
    )
    second = mount.dispatch(
        StubRequest(path="/__nexa__/login", method="POST", form={"token": "known-token"})
    )

    first_id, _ = session_from(first)
    second_id, _ = session_from(second)
    assert first_id != second_id


def test_logout_invalidates_the_session(mount, devtools):
    login = mount.dispatch(
        StubRequest(path="/__nexa__/login", method="POST", form={"token": "known-token"})
    )
    session_id, _ = session_from(login)

    logout = mount.dispatch(cookie_request(devtools, session_id, path="/__nexa__/logout"))
    assert logout[1] == 303
    assert "Max-Age=0" in logout[2]["Set-Cookie"]

    response = mount.dispatch(cookie_request(devtools, session_id))
    assert b"Errors (" not in response[0]
    assert b"name='token'" in response[0]


def test_expired_sessions_are_rejected(mount, devtools):
    login = mount.dispatch(
        StubRequest(path="/__nexa__/login", method="POST", form={"token": "known-token"})
    )
    session_id, _ = session_from(login)
    devtools._sessions[session_id] = time.time() - 1

    response = mount.dispatch(cookie_request(devtools, session_id))

    assert b"name='token'" in response[0]


def test_session_cookie_is_secure_when_forwarded_over_https(mount):
    response = mount.dispatch(
        StubRequest(
            path="/__nexa__/login",
            method="POST",
            form={"token": "known-token"},
            headers={"X-Forwarded-Proto": "https"},
        )
    )

    assert "; Secure" in response[2]["Set-Cookie"]


# ---------------------------------------------------------------------------
# Localhost restriction
# ---------------------------------------------------------------------------


def test_non_local_clients_are_refused(mount):
    response = mount.dispatch(StubRequest(remote_addr="203.0.113.7"))

    assert response[1] == 403
    assert b"localhost" in response[0]


def test_non_local_clients_cannot_log_in(mount):
    response = mount.dispatch(
        StubRequest(
            path="/__nexa__/login",
            method="POST",
            form={"token": "known-token"},
            remote_addr="203.0.113.7",
        )
    )

    assert response[1] == 403
    assert "Set-Cookie" not in response[2]


# ---------------------------------------------------------------------------
# Initialization before run() — `nexa dev` regression
# ---------------------------------------------------------------------------


def test_devtools_is_initialized_before_run_when_debug():
    app = NXserver("DevToolsInit", debug=True)

    devtools = app.devtools

    assert isinstance(devtools, DevTools)
    assert devtools.token
    assert app.devtools is devtools
    assert app._ensure_devtools() is devtools


def test_devtools_stays_unavailable_without_debug():
    app = NXserver("DevToolsNoDebug")

    with pytest.raises(AttributeError):
        _ = app.devtools


def test_num_devtools_instances_is_one_after_run_setup():
    app = NXserver("DevToolsSingleInstance", debug=True)

    app._ensure_devtools()
    first = app._devtools
    app._ensure_devtools()

    assert app._devtools is first


def test_initialized_token_authenticates_dashboard():
    app = NXserver("DevToolsInitAuth", debug=True)
    app.devtools.token = "dev-token"
    mount = _DevToolsMount(app.devtools)

    response = mount.dispatch(StubRequest(headers={"X-DevTools-Token": "dev-token"}))

    assert response[1] == 200
    assert b"Errors (" in response[0]


def test_nexa_dev_prints_exactly_one_token(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    import Nexa.nxserver as nxserver_module
    from Nexa.nexa import app as cli

    app_file = tmp_path / "demo.py"
    app_file.write_text(
        'from Nexa import NXserver\napp = NXserver("dev-init", port=3000)\n',
        encoding="utf-8",
    )

    started = {}

    def fake_run(self):
        started["debug"] = self.debug
        started["devtools"] = self.devtools

    monkeypatch.setattr(nxserver_module.NXserver, "run", fake_run)

    result = CliRunner().invoke(cli, ["dev", str(app_file), "--no-reload"])
    output = result.output + getattr(result, "stderr", "")

    assert result.exit_code == 0, output
    assert started["debug"] is False
    assert isinstance(started["devtools"], DevTools)
    assert output.count("DevTools token:") == 1
    assert started["devtools"].token in output
