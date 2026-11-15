import io
import json
from concurrent.futures import ThreadPoolExecutor
from wsgiref.util import setup_testing_defaults
from wsgiref.validate import validator

import pytest

from Nexa import Blueprint, NXserver, jsonify, render_template, request
from Nexa import nxserver as nxserver_module
from Nexa.nxserver import CorsConfig, Response


def call_wsgi(app, method="GET", path="/", body=b"", headers=None, **extra_environ):
    headers = headers or {}
    environ = {}
    setup_testing_defaults(environ)
    environ.update({
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "8080",
        "REMOTE_ADDR": "192.0.2.10",
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(body),
    })
    if body or "Content-Length" in headers:
        environ["CONTENT_LENGTH"] = str(headers.pop("Content-Length", len(body)))
    if "Content-Type" in headers:
        environ["CONTENT_TYPE"] = headers.pop("Content-Type")
    for name, value in headers.items():
        environ["HTTP_" + name.upper().replace("-", "_")] = value
    environ.update(extra_environ)

    captured = {}

    def start_response(status, response_headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = response_headers

    result = app(environ, start_response)
    try:
        chunks = list(result)
        assert all(isinstance(chunk, bytes) for chunk in chunks)
        captured["body"] = b"".join(chunks)
    finally:
        close = getattr(result, "close", None)
        if close is not None:
            close()
    return captured


def header_values(response, name):
    return [
        value
        for key, value in response["headers"]
        if key.lower() == name.lower()
    ]


def test_wsgi_get_and_direct_application_call():
    app = NXserver("WSGIGet")

    @app.get("/")
    def home():
        return "Hello from Nexa!"

    response = call_wsgi(validator(app), PATH_INFO="/")

    assert callable(app)
    assert response["status"] == "200 OK"
    assert response["body"] == b"Hello from Nexa!"
    assert header_values(response, "Content-Type") == ["text/html; charset=utf-8"]


def test_wsgi_post_json_and_request_metadata():
    app = NXserver("WSGIJSON")

    @app.post("/items")
    def create_item():
        return jsonify(
            {
                "payload": request.json,
                "remote": request.remote_addr,
                "server": [request.server_name, request.server_port],
                "path": request.path,
            },
            status=201,
        )

    response = call_wsgi(
        app,
        "POST",
        "/items",
        json.dumps({"name": "Nexa"}).encode(),
        {"Content-Type": "application/json"},
    )

    assert response["status"] == "201 Created"
    assert json.loads(response["body"]) == {
        "payload": {"name": "Nexa"},
        "remote": "192.0.2.10",
        "server": ["testserver", "8080"],
        "path": "/items",
    }
    assert header_values(response, "Content-Type") == ["application/json; charset=utf-8"]


def test_wsgi_query_and_dynamic_route_parameters():
    app = NXserver("WSGIParams")

    @app.get("/users/<user_id>")
    def user(user_id):
        return f"{user_id}:{request.query_params['tag'][0]}:{request.query_params['tag'][1]}"

    response = call_wsgi(
        app, path="/users/ada", QUERY_STRING="tag=first&tag=second"
    )

    assert response["body"] == b"ada:first:second"


def test_wsgi_route_decorator_and_path_are_not_decoded():
    app = NXserver("WSGIRoute")

    @app.route("/items/a%2Fb", methods=["GET"])
    def item():
        return request.path

    response = call_wsgi(app, path="/items/a%2Fb")

    assert response["body"] == b"/items/a%2Fb"


def test_wsgi_blueprint_routes():
    app = NXserver("WSGIBlueprint")
    api = Blueprint("api", prefix="/api")

    @api.get("/ping")
    def ping():
        return jsonify({"status": "ok"})

    app.register_blueprint(api)

    response = call_wsgi(app, path="/api/ping")

    assert response["status"] == "200 OK"
    assert json.loads(response["body"]) == {"status": "ok"}


def test_wsgi_html_response_and_template_rendering(tmp_path):
    app = NXserver("WSGIHTML")
    app.template_dir = tmp_path
    (tmp_path / "page.nxs").write_text("<h1>{{name}}</h1>", encoding="utf-8")

    @app.get("/html")
    def html_page():
        return Response("<p>HTML</p>", content_type="text/html")

    @app.get("/template")
    def template_page():
        return render_template("page.nxs", name="Nexa")

    assert call_wsgi(app, path="/html")["body"] == b"<p>HTML</p>"
    rendered = call_wsgi(app, path="/template")
    assert rendered["body"] == b"<h1>Nexa</h1>"
    assert header_values(rendered, "Content-Type") == ["text/html; charset=utf-8"]


def test_wsgi_preserves_custom_headers_without_duplicate_entity_headers():
    app = NXserver("WSGIHeaders")

    @app.get("/")
    def home():
        return Response(
            "hello",
            headers={
                "X-Request-ID": "abc",
                "content-type": "text/plain; charset=utf-8",
                "Content-Length": "999",
            },
        )

    response = call_wsgi(app)

    assert response["body"] == b"hello"
    assert header_values(response, "X-Request-ID") == ["abc"]
    assert header_values(response, "Content-Type") == ["text/plain; charset=utf-8"]
    assert header_values(response, "Content-Length") == ["5"]


def test_wsgi_not_found_and_method_not_allowed():
    app = NXserver("WSGIErrors")

    @app.post("/only-post")
    def only_post():
        return "posted"

    not_found = call_wsgi(app, path="/missing")
    wrong_method = call_wsgi(app, "GET", "/only-post")

    assert not_found["status"] == "404 Not Found"
    assert json.loads(not_found["body"])["error"] == "Not Found"
    assert wrong_method["status"] == "405 Method Not Allowed"
    assert "POST" in header_values(wrong_method, "Allow")[0]


def test_wsgi_head_has_empty_body_and_get_content_length():
    app = NXserver("WSGIHead")

    @app.get("/")
    def home():
        return "hello"

    response = call_wsgi(app, "HEAD")

    assert response["status"] == "200 OK"
    assert response["body"] == b""
    assert header_values(response, "Content-Length") == ["5"]


def test_wsgi_cors_preflight():
    app = NXserver(
        "WSGICORS",
        cors=CorsConfig(
            enabled=True,
            allowed_origins=["https://client.example"],
            allow_credentials=True,
        ),
    )

    response = call_wsgi(
        app,
        "OPTIONS",
        "/missing",
        headers={
            "Origin": "https://client.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response["status"] == "204 No Content"
    assert response["body"] == b""
    assert header_values(response, "Access-Control-Allow-Origin") == [
        "https://client.example"
    ]
    assert header_values(response, "Access-Control-Allow-Credentials") == ["true"]


def test_wsgi_before_and_after_request_hooks():
    app = NXserver("WSGIHooks")
    calls = []

    @app.before_request
    def before(req):
        calls.append(("before", req.path))

    @app.after_request
    def after(body, status, headers):
        calls.append(("after", status))
        headers["X-Hook"] = "done"
        return body, status, headers

    @app.get("/")
    def home():
        return "ok"

    response = call_wsgi(app)

    assert calls == [("before", "/"), ("after", 200)]
    assert header_values(response, "X-Hook") == ["done"]


def test_wsgi_contextvars_are_available_during_request_and_reset_afterward():
    app = NXserver("WSGIContext")
    seen = []

    @app.get("/")
    def home():
        seen.append((nxserver_module._current_request.get(), nxserver_module._current_server.get()))
        return "ok"

    call_wsgi(app)

    assert seen[0][0].path == "/"
    assert seen[0][1] is app
    assert nxserver_module._current_request.get() is None
    assert nxserver_module._current_server.get() is None


def test_wsgi_rejects_malformed_and_oversized_content_lengths():
    app = NXserver("WSGIBodyLimit", max_body_size=4)

    malformed = call_wsgi(
        app,
        "POST",
        body=b"x",
        **{"CONTENT_LENGTH": "-1"},
    )
    oversized = call_wsgi(
        app,
        "POST",
        body=b"12345",
        **{"CONTENT_LENGTH": "5"},
    )

    assert malformed["status"] == "400 Bad Request"
    assert oversized["status"] == "413 Content Too Large"


def test_wsgi_reads_bounded_body_without_content_length():
    app = NXserver("WSGINoLength", max_body_size=4)

    @app.post("/")
    def echo():
        return request.body

    response = call_wsgi(app, "POST", body=b"12345", CONTENT_LENGTH="")

    assert response["status"] == "413 Content Too Large"


def test_wsgi_requests_are_independent_across_threads():
    app = NXserver("WSGIConcurrent")

    @app.get("/<value>")
    def echo(value):
        return f"{value}:{request.remote_addr}"

    def make_request(value):
        return call_wsgi(
            app, path=f"/{value}", REMOTE_ADDR=f"192.0.2.{value}"
        )["body"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.map(make_request, ("1", "2"))

    assert first == b"1:192.0.2.1"
    assert second == b"2:192.0.2.2"


@pytest.mark.parametrize(
    ("method", "decorator_name"),
    [
        ("GET", "get"),
        ("POST", "post"),
        ("PUT", "put"),
        ("PATCH", "patch"),
        ("DELETE", "delete"),
        ("OPTIONS", "options"),
        ("HEAD", "head"),
    ],
)
def test_wsgi_method_decorators(method, decorator_name):
    app = NXserver("WSGIMethods")

    def handler():
        return "ok"

    getattr(app, decorator_name)("/method")(handler)
    response = call_wsgi(app, method, "/method")

    assert response["status"] == "200 OK"
    assert response["body"] == (b"" if method == "HEAD" else b"ok")
