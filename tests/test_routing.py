import json
import uuid

import pytest

from Nexa import NXserver, jsonify


def call_wsgi(app, path="/", method="GET", **extra_environ):
    """Run one request through the WSGI entry point and return (status, payload)."""
    captured = {}

    def start_response(status_line, headers):
        captured["status"] = int(status_line.split(" ", 1)[0])
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "wsgi.input": __import__("io").BytesIO(b""),
        "wsgi.url_scheme": "http",
    }
    environ.update(extra_environ)
    body = b"".join(app.wsgi_app(environ, start_response))
    return captured["status"], body


def json_body(raw):
    return json.loads(raw.decode("utf-8"))


@pytest.fixture()
def app():
    return NXserver("RoutingTest")


def test_int_converter_passes_integer(app):
    @app.get("/users/<int:user_id>")
    def user(user_id):
        return jsonify({"value": user_id, "type": type(user_id).__name__})

    status, body = call_wsgi(app, path="/users/42")

    assert status == 200
    assert json_body(body) == {"value": 42, "type": "int"}


def test_float_converter_passes_float(app):
    @app.get("/prices/<float:amount>")
    def price(amount):
        return jsonify({"value": amount, "type": type(amount).__name__})

    status, body = call_wsgi(app, path="/prices/12.5")

    assert status == 200
    assert json_body(body) == {"value": 12.5, "type": "float"}


def test_uuid_converter_accepts_valid_uuid(app):
    expected = uuid.UUID("12345678-1234-5678-1234-567812345678")

    @app.get("/objects/<uuid:object_id>")
    def object_route(object_id):
        return jsonify({"matches": object_id == expected, "type": type(object_id).__name__})

    status, body = call_wsgi(app, path=f"/objects/{expected}")

    assert status == 200
    assert json_body(body) == {"matches": True, "type": "UUID"}


def test_uuid_converter_rejects_invalid_uuid_with_404(app):
    @app.get("/objects/<uuid:object_id>")
    def object_route(object_id):
        return jsonify({"id": str(object_id)})

    status, body = call_wsgi(app, path="/objects/not-a-uuid")

    assert status == 404
    assert json_body(body)["error"] == "Not Found"


def test_string_converter_stays_backward_compatible(app):
    @app.get("/hello/<name>")
    def hello(name):
        return jsonify({"name": name, "type": type(name).__name__})

    status, body = call_wsgi(app, path="/hello/ada")

    assert status == 200
    assert json_body(body) == {"name": "ada", "type": "str"}


def test_path_converter_handles_nested_paths(app):
    @app.get("/files/<path:filename>")
    def files(filename):
        return jsonify({"filename": filename})

    status, body = call_wsgi(app, path="/files/docs/2026/report.txt")

    assert status == 200
    assert json_body(body) == {"filename": "docs/2026/report.txt"}


@pytest.mark.parametrize("path", ["/count/abc", "/count/1.5", "/count/"])
def test_invalid_values_do_not_crash_the_server(app, path):
    @app.get("/count/<int:value>")
    def count(value):
        return jsonify({"value": value})

    status, body = call_wsgi(app, path=path)

    assert status == 404
    assert json_body(body)["error"] == "Not Found"


def test_static_route_wins_over_parameter_route(app):
    @app.get("/users/me")
    def me():
        return jsonify({"route": "static"})

    @app.get("/users/<name>")
    def other(name):
        return jsonify({"route": "param", "name": name})

    assert json_body(call_wsgi(app, path="/users/me")[1]) == {"route": "static"}
    assert json_body(call_wsgi(app, path="/users/ada")[1]) == {
        "route": "param",
        "name": "ada",
    }


def test_url_for_builds_named_route_url(app):
    @app.get("/users/<int:user_id>/posts/<slug>", name="user_post")
    def user_post(user_id, slug):
        return jsonify({"ok": True})

    assert app.url_for("user_post", user_id=7, slug="hello") == "/users/7/posts/hello"
    assert app.build_url("user_post", user_id=7, slug="hello") == "/users/7/posts/hello"


def test_url_for_percent_encodes_parameter_values(app):
    @app.get("/search/<term>", name="search")
    def search(term):
        return jsonify({"term": term})

    assert app.url_for("search", term="a b/c?") == "/search/a%20b%2Fc%3F"


def test_url_for_path_converter_keeps_slashes(app):
    @app.get("/files/<path:filename>", name="file")
    def files(filename):
        return jsonify({"filename": filename})

    assert app.url_for("file", filename="docs/my report.txt") == "/files/docs/my%20report.txt"


def test_url_for_missing_parameter_raises_clear_error(app):
    @app.get("/users/<int:user_id>", name="user")
    def user(user_id):
        return jsonify({"id": user_id})

    with pytest.raises(ValueError, match="Missing URL parameter"):
        app.url_for("user")


def test_url_for_extra_parameter_raises_clear_error(app):
    @app.get("/users/<int:user_id>", name="user")
    def user(user_id):
        return jsonify({"id": user_id})

    with pytest.raises(ValueError, match="Unexpected URL parameter"):
        app.url_for("user", user_id=1, extra="nope")


def test_url_for_unknown_name_raises_clear_error(app):
    with pytest.raises(ValueError, match="No route named"):
        app.url_for("missing")


def test_duplicate_route_names_are_rejected(app):
    @app.get("/a", name="dup")
    def first():
        return "a"

    with pytest.raises(ValueError, match="already registered"):

        @app.get("/b", name="dup")
        def second():
            return "b"


def test_unknown_converter_is_rejected():
    app = NXserver("BadConverter")

    with pytest.raises(ValueError, match="Unknown converter"):

        @app.get("/x/<money:value>")
        def route(value):
            return value
