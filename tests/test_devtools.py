import json
import threading
from http.client import HTTPConnection
from http.server import HTTPServer as StdHTTPServer

import pytest

from Nexa import NXserver
from Nexa import nxserver as nxserver_module


def install_test_server(monkeypatch, serve_forever):
    """Monkeypatch HTTPServer so the server can serve exactly one request.

    Returns a list that will contain the TestHTTPServer instance once
    ``app.run()`` constructs it.
    """
    instances = []

    class TestHTTPServer(StdHTTPServer):
        def __init__(self, address, handler):
            super().__init__(address, handler)
            instances.append(self)

        def serve_forever(self):
            serve_forever(self)

    monkeypatch.setattr(nxserver_module, "HTTPServer", TestHTTPServer)
    return instances


def _serve_once(_server):
    """Serve a single request then shut down.

    The ``serve_forever`` callback receives the server instance.
    """
    _server.timeout = 5
    _server.handle_request()


def _wait_for_instance(thread, instances):
    """Block until a TestHTTPServer instance exists or the thread dies."""
    for _ in range(100):
        if instances:
            return instances[0]
        if not thread.is_alive():
            break
        threading.Event().wait(0.01)
    raise AssertionError("NXserver did not start listening.")


# ---------------------------------------------------------------------------
# DevTools integration tests
# ---------------------------------------------------------------------------


def test_devtools_dashboard_request(monkeypatch):
    """A GET to /__nexa__/ returns the DevTools dashboard HTML when debug=True."""
    instances = install_test_server(monkeypatch, _serve_once)
    app = NXserver("DevToolsDashboard", port=0, debug=True)

    @app.get("/")
    def home():
        return "<h1>Hello</h1>"

    thread = threading.Thread(target=app.run)
    thread.start()
    try:
        server = _wait_for_instance(thread, instances)
        # DevTools object is created inside run() before HTTPServer; set token now.
        app.devtools.token = "test-token"
        conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        conn.request("GET", "/__nexa__/", headers={"X-DevTools-Token": "test-token"})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()

        assert resp.status == 200
        assert b"Nexa DevTools" in body
        assert b"<title>Nexa DevTools" in body
    finally:
        thread.join(timeout=3)
        if thread.is_alive():
            raise AssertionError("NXserver did not stop after serving the test request.")


def test_devtools_api_subroutes(monkeypatch):
    """DevTools JSON API endpoints return valid JSON with the correct structure."""

    def _serve_three(_server):
        """Serve three requests then shut down."""
        _server.timeout = 5
        for _ in range(3):
            _server.handle_request()

    instances = install_test_server(monkeypatch, _serve_three)
    app = NXserver("DevToolsAPI", port=0, debug=True)

    @app.get("/")
    def home():
        return "ok"

    thread = threading.Thread(target=app.run)
    thread.start()
    try:
        server = _wait_for_instance(thread, instances)
        app.devtools.token = "api-token"

        # /__nexa__/api — routes JSON
        conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        conn.request(
            "GET",
            "/__nexa__/api",
            headers={"X-DevTools-Token": "api-token"},
        )
        resp = conn.getresponse()
        data = json.loads(resp.read())
        conn.close()
        assert resp.status == 200
        assert "server" in data
        assert "routes" in data
        assert "middleware" in data
        assert isinstance(data["routes"], list)

        # /__nexa__/log — log tail JSON
        conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        conn.request(
            "GET",
            "/__nexa__/log",
            headers={"X-DevTools-Token": "api-token"},
        )
        resp = conn.getresponse()
        log_data = json.loads(resp.read())
        conn.close()
        assert resp.status == 200
        assert "logs" in log_data
        assert isinstance(log_data["logs"], list)

        # /__nexa__/clear — clear logs
        conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        conn.request(
            "POST",
            "/__nexa__/clear",
            headers={"X-DevTools-Token": "api-token"},
        )
        resp = conn.getresponse()
        clear_data = json.loads(resp.read())
        conn.close()
        assert resp.status == 200
        assert clear_data == {"ok": True}
    finally:
        thread.join(timeout=3)
        if thread.is_alive():
            raise AssertionError("NXserver did not stop after serving the test request.")


def test_devtools_missing_token_returns_403(monkeypatch):
    """Requests without X-DevTools-Token return 403."""
    instances = install_test_server(monkeypatch, _serve_once)
    app = NXserver("DevToolsNoToken", port=0, debug=True)
    # Let DevTools use its auto-generated random token; we just don't send it.

    @app.get("/")
    def home():
        return "ok"

    thread = threading.Thread(target=app.run)
    thread.start()
    try:
        server = _wait_for_instance(thread, instances)
        conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        conn.request("GET", "/__nexa__/api")  # no token header
        resp = conn.getresponse()
        body = resp.read()
        conn.close()

        assert resp.status == 403
        payload = json.loads(body)
        assert payload["error"] == "forbidden"
    finally:
        thread.join(timeout=3)
        if thread.is_alive():
            raise AssertionError("NXserver did not stop after serving the test request.")


def test_devtools_invalid_token_returns_403(monkeypatch):
    """Requests with wrong X-DevTools-Token return 403."""
    instances = install_test_server(monkeypatch, _serve_once)
    app = NXserver("DevToolsBadToken", port=0, debug=True)

    @app.get("/")
    def home():
        return "ok"

    thread = threading.Thread(target=app.run)
    thread.start()
    try:
        server = _wait_for_instance(thread, instances)
        app.devtools.token = "correct-token"
        conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        conn.request(
            "GET",
            "/__nexa__/api",
            headers={"X-DevTools-Token": "wrong-token"},
        )
        resp = conn.getresponse()
        body = resp.read()
        conn.close()

        assert resp.status == 403
        payload = json.loads(body)
        assert payload["error"] == "forbidden"
    finally:
        thread.join(timeout=3)
        if thread.is_alive():
            raise AssertionError("NXserver did not stop after serving the test request.")


def test_devtools_normal_routes_still_work(monkeypatch):
    """Normal application routes continue working when debug=True and DevTools is mounted."""
    instances = install_test_server(monkeypatch, _serve_once)
    app = NXserver("DevToolsNormal", port=0, debug=True)

    @app.get("/")
    def home():
        return "<h1>Home</h1>"

    thread = threading.Thread(target=app.run)
    thread.start()
    try:
        server = _wait_for_instance(thread, instances)

        # Normal route should work (no DevTools token needed for app routes)
        conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        conn.request("GET", "/")
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        assert resp.status == 200
        assert b"<h1>Home</h1>" in body
    finally:
        thread.join(timeout=3)
        if thread.is_alive():
            raise AssertionError("NXserver did not stop after serving the test request.")


def test_no_devtools_when_debug_false(monkeypatch):
    """When debug=False, /__nexa__/ returns 404 and normal routes work."""
    instances = install_test_server(monkeypatch, _serve_once)
    app = NXserver("NoDevTools", port=0, debug=False)

    @app.get("/")
    def home():
        return "<h1>Home</h1>"

    thread = threading.Thread(target=app.run)
    thread.start()
    try:
        server = _wait_for_instance(thread, instances)

        # /__nexa__/ should 404 (not mounted)
        conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        conn.request("GET", "/__nexa__/")
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        assert resp.status == 404
    finally:
        thread.join(timeout=3)
        if thread.is_alive():
            raise AssertionError("NXserver did not stop after serving the test request.")


def test_devtools_404_for_unknown_subroute(monkeypatch):
    """Unknown DevTools sub-routes return 404."""
    instances = install_test_server(monkeypatch, _serve_once)
    app = NXserver("DevTools404", port=0, debug=True)

    thread = threading.Thread(target=app.run)
    thread.start()
    try:
        server = _wait_for_instance(thread, instances)
        app.devtools.token = "token"
        conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        conn.request(
            "GET",
            "/__nexa__/nonexistent",
            headers={"X-DevTools-Token": "token"},
        )
        resp = conn.getresponse()
        body = resp.read()
        conn.close()

        assert resp.status == 404
        payload = json.loads(body)
        assert payload["error"] == "not found"
    finally:
        thread.join(timeout=3)
        if thread.is_alive():
            raise AssertionError("NXserver did not stop after serving the test request.")
