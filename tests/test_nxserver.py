import errno
import json
import threading
import warnings
from http.client import HTTPConnection
from http.server import HTTPServer as StdHTTPServer

import pytest

from Nexa import Blueprint, Core, Nserver, NXserver
from Nexa import nxserver as nxserver_module
from Nexa.nexa import app as cli_app
from Nexa.nserver import Nserver as ModuleNserver


def install_test_server(monkeypatch, serve_forever):
    instances = []

    class TestHTTPServer(StdHTTPServer):
        def __init__(self, address, handler):
            super().__init__(address, handler)
            instances.append(self)

        def serve_forever(self):
            serve_forever(self)

    monkeypatch.setattr(nxserver_module, "HTTPServer", TestHTTPServer)
    return instances


def stop_immediately(_server):
    raise KeyboardInterrupt()


@pytest.mark.parametrize(
    ("kwargs", "expected_host"),
    [
        ({}, "127.0.0.1"),
        ({"host": "localhost"}, "127.0.0.1"),
        ({"host": "127.0.0.1"}, "127.0.0.1"),
        ({"host": "0.0.0.0"}, "0.0.0.0"),
    ],
)
def test_server_binds_configured_host_and_port(monkeypatch, kwargs, expected_host):
    servers = install_test_server(monkeypatch, stop_immediately)
    app = NXserver("BindingTest", port=0, **kwargs)

    app.run()

    assert servers[0].server_address[0] == expected_host
    assert servers[0].server_address[1] > 0


def test_host_and_port_validation():
    for host in ("", "not a host", "256.0.0.1", "::1"):
        with pytest.raises(ValueError, match="Invalid host"):
            NXserver("InvalidHost", host=host)

    for port in (-1, 65536, "not a port", True):
        with pytest.raises(ValueError, match="port"):
            NXserver("InvalidPort", port=port)


def test_configured_port_is_passed_to_http_server(monkeypatch):
    captured = {}

    class CaptureHTTPServer:
        def __init__(self, address, _handler):
            captured["address"] = address
            self.server_address = address

        def serve_forever(self):
            raise KeyboardInterrupt()

        def server_close(self):
            pass

    monkeypatch.setattr(nxserver_module, "HTTPServer", CaptureHTTPServer)
    NXserver("PortTest", host="127.0.0.1", port=43210).run()

    assert captured["address"] == ("127.0.0.1", 43210)


def test_address_in_use_has_clear_error(monkeypatch):
    def fail_to_bind(_address, _handler):
        raise OSError(errno.EADDRINUSE, "address already in use")

    monkeypatch.setattr(nxserver_module, "HTTPServer", fail_to_bind)
    app = NXserver("Busy", host="127.0.0.1", port=3000)

    with pytest.raises(OSError, match="127.0.0.1:3000 is already in use"):
        app.run()


def test_unavailable_interface_has_clear_error(monkeypatch):
    def fail_to_bind(_address, _handler):
        raise OSError(errno.EADDRNOTAVAIL, "address unavailable")

    monkeypatch.setattr(nxserver_module, "HTTPServer", fail_to_bind)
    app = NXserver("Unavailable", host="192.0.2.10", port=3000)

    with pytest.raises(OSError, match="not assigned to a local interface"):
        app.run()


def test_startup_output_uses_accessible_url_for_all_interfaces(
    monkeypatch, capsys
):
    install_test_server(monkeypatch, stop_immediately)
    app = NXserver("PublicBind", host="0.0.0.0", port=0)

    app.run()

    output = capsys.readouterr().out
    assert "listening on 0.0.0.0:" in output
    assert "access at http://127.0.0.1:" in output
    assert "access at http://0.0.0.0:" not in output


def test_nserver_is_a_deprecated_compatibility_name():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        app = Nserver("Legacy")

    assert isinstance(app, NXserver)
    assert any(item.category is DeprecationWarning for item in caught)
    assert Nserver is not NXserver
    assert ModuleNserver is Nserver


def test_cli_exposes_exec_command():
    assert any(command.name == "exec" for command in cli_app.registered_commands)


def test_blueprint_routes_remain_available():
    app = NXserver("BlueprintTest")
    blueprint = Blueprint("api", prefix="/api")

    @blueprint.get("/ping")
    def ping():
        return "pong"

    app.register_blueprint(blueprint)
    route, params = app.router.match("/api/ping")

    assert route is not None
    assert params == {}
    assert route.handler() == "pong"


def test_core_event_uses_nxserver_request_response_pipeline(monkeypatch):
    def serve_once(server):
        server.timeout = 3
        server.handle_request()

    servers = install_test_server(monkeypatch, serve_once)
    app = NXserver("CoreTest", port=0)
    Core.init_app(app)

    @Core.event("nxserver_test_hello")
    def hello(data):
        return {"message": "Hello " + data.get("name", "Guest")}

    thread = threading.Thread(target=app.run)
    thread.start()
    try:
        server = _wait_for_instance(thread, servers)
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        connection.request(
            "POST",
            app.core_event_endpoint,
            body=json.dumps({"event": "nxserver_test_hello", "data": {"name": "Ada"}}),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()

        assert response.status == 200
        assert payload == {"message": "Hello Ada"}
    finally:
        thread.join(timeout=3)
        if thread.is_alive():
            raise AssertionError("NXserver did not stop after serving the test request.")


def _wait_for_instance(thread, instances):
    for _ in range(100):
        if instances:
            return instances[0]
        if not thread.is_alive():
            break
        threading.Event().wait(0.01)
    raise AssertionError("NXserver did not start listening.")


def test_core_chooses_endpoint_away_from_application_routes():
    app = NXserver("CoreCollision")

    @app.get("/__nexa/core/events")
    def application_route():
        return "application"

    Core.init_app(app)

    assert app.core_event_endpoint == "/__nexa/core/events-1"
    route, _ = app.router.match("/__nexa/core/events")
    assert route is not None
    assert route.handler() == "application"
