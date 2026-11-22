"""Response normalization and error-handler integration tests.

These cover the failure where a custom error handler returned a
``JSONResponse`` and the HTTP/WSGI layer tried to unpack it as a
``(body, status, headers)`` tuple.
"""

import io
import json
from wsgiref.util import setup_testing_defaults

import pytest

from Nexa import NXserver, jsonify
from Nexa.nxserver import (
    HTMLResponse,
    JSONResponse,
    Request,
    Response,
    html,
    text,
)


def call_wsgi(app, method="GET", path="/", body=b"", headers=None, **extra_environ):
    environ = {}
    setup_testing_defaults(environ)
    environ.update(
        {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "SERVER_NAME": "testserver",
            "SERVER_PORT": "8080",
            "REMOTE_ADDR": "127.0.0.1",
            "wsgi.url_scheme": "http",
            "wsgi.input": io.BytesIO(body),
        }
    )
    headers = dict(headers or {})
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
    captured["body"] = b"".join(result)
    return captured


def header(captured, name):
    return [
        value
        for key, value in captured["headers"]
        if key.lower() == name.lower()
    ]


def status_code(captured):
    return int(captured["status"].split(" ", 1)[0])


# ---------------------------------------------------------------------------
# Route return types
# ---------------------------------------------------------------------------


def test_route_returning_json_response():
    app = NXserver("json-route")

    @app.get("/")
    def home():
        return jsonify({"hello": "world"})

    result = call_wsgi(app)

    assert status_code(result) == 200
    assert header(result, "Content-Type") == ["application/json; charset=utf-8"]
    assert json.loads(result["body"]) == {"hello": "world"}


def test_route_returning_html_response_preserves_status_and_headers():
    app = NXserver("html-route")

    @app.get("/")
    def home():
        return HTMLResponse(
            "<h1>Created</h1>",
            status=201,
            headers={"X-Request-Id": "abc", "Set-Cookie": "a=1; Path=/"},
        )

    result = call_wsgi(app)

    assert status_code(result) == 201
    assert result["body"] == b"<h1>Created</h1>"
    assert header(result, "Content-Type") == ["text/html; charset=utf-8"]
    assert header(result, "X-Request-Id") == ["abc"]
    assert header(result, "Set-Cookie") == ["a=1; Path=/"]


def test_route_returning_plain_string():
    app = NXserver("str-route")

    @app.get("/")
    def home():
        return "plain text"

    result = call_wsgi(app)

    assert status_code(result) == 200
    assert result["body"] == b"plain text"


def test_route_returning_bytes():
    app = NXserver("bytes-route")

    @app.get("/")
    def home():
        return b"\x00binary\xff"

    result = call_wsgi(app)

    assert result["body"] == b"\x00binary\xff"
    assert header(result, "Content-Length") == [str(len(b"\x00binary\xff"))]


def test_route_returning_tuple_preserves_status_and_headers():
    app = NXserver("tuple-route")

    @app.get("/")
    def home():
        return "Accepted", 202, {"X-Reason": "queued", "Content-Type": "text/plain"}

    result = call_wsgi(app)

    assert status_code(result) == 202
    assert result["body"] == b"Accepted"
    assert header(result, "X-Reason") == ["queued"]
    assert header(result, "Content-Type") == ["text/plain"]


def test_route_returning_response_helper():
    app = NXserver("response-route")

    @app.get("/")
    def home():
        return Response.json({"ok": True}, status=201, headers={"X-Test": "yes"})

    result = call_wsgi(app)

    assert status_code(result) == 201
    assert json.loads(result["body"]) == {"ok": True}
    assert header(result, "X-Test") == ["yes"]


def test_empty_response_body():
    app = NXserver("empty-route")

    @app.get("/")
    def home():
        return Response.empty()

    result = call_wsgi(app)

    assert status_code(result) == 204
    assert result["body"] == b""
    assert header(result, "Content-Length") == []


def test_none_route_result_is_an_empty_200():
    app = NXserver("none-route")

    @app.get("/")
    def home():
        return None

    result = call_wsgi(app)

    assert status_code(result) == 200
    assert result["body"] == b""
    assert header(result, "Content-Length") == ["0"]


def test_unknown_route_returns_json_404():
    app = NXserver("missing-route")

    result = call_wsgi(app, path="/nope")

    assert status_code(result) == 404
    payload = json.loads(result["body"])
    assert payload["error"] == "Not Found"


def test_route_raising_an_exception_returns_500():
    app = NXserver("boom-route")

    @app.get("/")
    def home():
        raise RuntimeError("exploded")

    result = call_wsgi(app)

    assert status_code(result) == 500
    assert json.loads(result["body"])["error"] == "Internal Server Error"


def test_head_request_sends_no_body():
    app = NXserver("head-route")

    @app.get("/")
    def home():
        return text("hello")

    result = call_wsgi(app, method="HEAD")

    assert result["body"] == b""
    assert header(result, "Content-Length") == ["5"]


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------


def test_error_handler_returning_json_response():
    """The original crash: the handler's JSONResponse was unpacked by the server."""
    app = NXserver("json-error-handler")

    @app.get("/")
    def home():
        raise ValueError("bad input")

    @app.error_handler(ValueError)
    def handle_value_error(request, exc):
        return jsonify({"handled": True, "message": str(exc)})

    result = call_wsgi(app)

    assert status_code(result) == 200
    assert header(result, "Content-Type") == ["application/json; charset=utf-8"]
    assert json.loads(result["body"]) == {"handled": True, "message": "bad input"}


def test_error_handler_returning_html_response():
    app = NXserver("html-error-handler")

    @app.get("/")
    def home():
        raise KeyError("missing")

    @app.error_handler(KeyError)
    def handle_key_error(request, exc):
        return HTMLResponse("<h1>Not here</h1>", status=410)

    result = call_wsgi(app)

    assert status_code(result) == 410
    assert result["body"] == b"<h1>Not here</h1>"
    assert header(result, "Content-Type") == ["text/html; charset=utf-8"]


def test_error_handler_returning_tuple():
    app = NXserver("tuple-error-handler")

    @app.get("/")
    def home():
        raise LookupError("missing")

    @app.error_handler(LookupError)
    def handle_lookup(request, exc):
        return b"gone", 410, {"X-Handled": "yes"}

    result = call_wsgi(app)

    assert status_code(result) == 410
    assert result["body"] == b"gone"
    assert header(result, "X-Handled") == ["yes"]


def test_error_handler_returning_plain_string():
    app = NXserver("str-error-handler")

    @app.get("/")
    def home():
        raise ArithmeticError("math")

    @app.error_handler(ArithmeticError)
    def handle_math(request, exc):
        return "friendly failure"

    result = call_wsgi(app)

    assert status_code(result) == 200
    assert result["body"] == b"friendly failure"


def test_error_handler_that_raises_returns_safe_500():
    app = NXserver("broken-error-handler")

    @app.get("/")
    def home():
        raise ValueError("original problem")

    @app.error_handler(ValueError)
    def handle_value_error(request, exc):
        raise RuntimeError("handler problem")

    result = call_wsgi(app)

    assert status_code(result) == 500
    payload = json.loads(result["body"])
    assert payload["error"] == "Internal Server Error"
    assert "custom error handler" in payload["detail"].lower()


def test_error_handler_returning_unsupported_value_returns_safe_500():
    app = NXserver("bad-error-handler")

    @app.get("/")
    def home():
        raise ValueError("original problem")

    @app.error_handler(ValueError)
    def handle_value_error(request, exc):
        return "a", "b", "c", "d"

    result = call_wsgi(app)

    assert status_code(result) == 500
    assert json.loads(result["body"])["error"] == "Internal Server Error"


def test_status_code_handler_returning_json_response():
    app = NXserver("json-404-handler")

    @app.error(404)
    def not_found(request, exc):
        return jsonify({"error": "custom missing"}), 404, {}

    result = call_wsgi(app, path="/definitely-not-here")

    assert status_code(result) == 404
    assert json.loads(result["body"]) == {"error": "custom missing"}


def test_status_code_handler_returning_html_response():
    app = NXserver("html-404-handler")

    @app.error(404)
    def not_found(request, exc):
        return HTMLResponse("<h1>Lost</h1>", status=404)

    result = call_wsgi(app, path="/definitely-not-here")

    assert status_code(result) == 404
    assert result["body"] == b"<h1>Lost</h1>"


def test_status_code_handler_that_raises_falls_back_to_default():
    app = NXserver("broken-404-handler")

    @app.error(404)
    def not_found(request, exc):
        raise RuntimeError("broken 404 page")

    result = call_wsgi(app, path="/definitely-not-here")

    assert status_code(result) == 404
    assert json.loads(result["body"])["error"] == "Not Found"


# ---------------------------------------------------------------------------
# Normalization internals and DevTools routes
# ---------------------------------------------------------------------------


def test_finalize_response_accepts_a_json_response_directly():
    app = NXserver("finalize")

    body, status, headers = app._finalize_response(jsonify({"ok": True}))

    assert status == 200
    assert body == b'{"ok": true}'
    assert ("Content-Type", "application/json; charset=utf-8") in headers


def test_finalize_response_accepts_prepared_tuple():
    app = NXserver("finalize-prepared")
    prepared = (b"ok", 200, [("Content-Type", "text/plain; charset=utf-8")])

    assert app._finalize_response(prepared) == prepared


def test_unknown_return_value_keeps_string_fallback():
    app = NXserver("fallback")

    @app.get("/")
    def home():
        return 42

    result = call_wsgi(app)

    assert status_code(result) == 200
    assert result["body"] == b"42"


def build_request(method, path, body=b"", headers=None):
    headers = dict(headers or {})
    if body:
        headers.setdefault("Content-Length", str(len(body)))
    return Request(
        method=method,
        path=path,
        url=path,
        query_string="",
        headers=headers,
        body_bytes=body,
        remote_addr="127.0.0.1",
        max_body_size=1_048_576,
        server_name="127.0.0.1",
        server_port="8080",
    )


def test_devtools_dashboard_serves_login_page():
    app = NXserver("devtools-dashboard")
    app.enable_devtools(token="test-token")

    body, status, headers = app._process_request(build_request("GET", "/__nexa__/"))

    assert status == 200
    assert b"name='token'" in body
    assert b"serviceWorker" not in body
    assert ("Content-Type", "text/html; charset=utf-8") in headers


def test_devtools_login_route_succeeds_and_sets_cookie():
    app = NXserver("devtools-login")
    app.enable_devtools(token="test-token")

    body, status, headers = app._process_request(
        build_request(
            "POST",
            "/__nexa__/login",
            body=b"token=test-token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    )

    assert status == 303
    assert body == b""
    assert dict(headers).get("Location") == "/__nexa__/"
    assert "nexa_devtools=" in dict(headers).get("Set-Cookie", "")


def test_devtools_login_rejects_wrong_token():
    app = NXserver("devtools-bad-login")
    app.enable_devtools(token="test-token")

    body, status, _headers = app._process_request(
        build_request(
            "POST",
            "/__nexa__/login",
            body=b"token=wrong",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    )

    assert status == 200
    assert b"Invalid DevTools token." in body


def test_service_worker_request_returns_clean_404():
    """The dashboard registers no service worker; /sw.js stays a normal 404."""
    app = NXserver("sw-route")

    result = call_wsgi(app, path="/sw.js")

    assert status_code(result) == 404
    assert json.loads(result["body"])["error"] == "Not Found"
