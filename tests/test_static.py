"""Tests for Nexa.static module."""

from pathlib import Path

from Nexa.static import StaticFiles


class TestStaticFilesBasics:
    """Basic static file serving."""

    def test_serve_existing_file(self, tmp_path):
        index = tmp_path / "index.html"
        index.write_text("<!DOCTYPE html><html></html>")
        static = StaticFiles(directory=str(tmp_path))
        status, headers, body = static.handle_request("GET", "/index.html")
        assert status == 200
        assert isinstance(body, bytes)
        assert body.startswith(b"<!DOCTYPE html>")

    def test_content_type_set(self, tmp_path):
        css = tmp_path / "style.css"
        css.write_text("body{}")
        static = StaticFiles(directory=str(tmp_path))
        status, headers, body = static.handle_request("GET", "/style.css")
        assert status == 200
        content_type = dict(headers).get("Content-Type", "")
        assert content_type.startswith("text/css")


class TestStaticFilesHead:
    """HEAD request support."""

    def test_head_request_returns_no_body(self, tmp_path):
        file = tmp_path / "readme.txt"
        file.write_text("hello static")
        static = StaticFiles(directory=str(tmp_path))
        status, headers, body = static.handle_request("HEAD", "/readme.txt")
        assert status == 200
        assert body == b""


class TestStaticFilesNotFound:
    """404 handling."""

    def test_missing_file_returns_404(self, tmp_path):
        static = StaticFiles(directory=str(tmp_path))
        status, headers, body = static.handle_request("GET", "/missing.html")
        assert status == 404


class TestStaticFilesTraversal:
    """Path traversal protection."""

    def test_traversal_attempt_rejected(self, tmp_path):
        # Create a file in the static dir; traversal should return 404.
        (tmp_path / "secret.txt").write_text("secret content")
        static = StaticFiles(directory=str(tmp_path))
        # Attempt path traversal.
        status, headers, body = static.handle_request("GET", "/../secret.txt")
        assert status == 404


class TestStaticFilesCacheHeaders:
    """Cache-Control and conditional headers."""

    def test_cache_control_header_present(self, tmp_path):
        file = tmp_path / "cache.html"
        file.write_text("cached content")
        static = StaticFiles(directory=str(tmp_path))
        status, headers, body = static.handle_request("GET", "/cache.html")
        assert status == 200
        # Should include cache-related headers.
        header_keys = {k.lower() for k, _ in headers}
        assert "cache-control" in header_keys


class TestStaticFilesConditionalRequests:
    """If-Modified-Since / If-None-Match support."""

    def test_if_modified_since_returns_304(self, tmp_path):
        file = tmp_path / "modified.html"
        file.write_text("modified content")
        static = StaticFiles(directory=str(tmp_path))
        # Send an If-Modified-Since header far in the future to force 304.
        status, headers, body = static.handle_request(
            "GET", "/modified.html",
            if_modified_since="Fri, 31 Dec 9999 23:59:59 GMT",
        )
        assert status == 304

    def test_if_none_match_returns_304(self, tmp_path):
        file = tmp_path / "etag.html"
        file.write_text("etag content")
        static = StaticFiles(directory=str(tmp_path))
        # Compute ETag from file content (size+mtime+inode based).
        import hashlib
        stat = file.stat()
        inode = getattr(stat, "st_ino", 0)
        etag_input = f"{stat.st_size}-{stat.st_mtime}-{inode}"
        md5 = hashlib.md5(etag_input.encode()).hexdigest()
        status, headers, body = static.handle_request(
            "GET", "/etag.html",
            if_none_match=f'"{md5}"',
        )
        assert status == 304


class TestStaticFilesDirectoryListing:
    """Directory listing."""

    def test_list_directory_with_index_file(self, tmp_path):
        (tmp_path / "index.html").write_text("<h1>index</h1>")
        static = StaticFiles(directory=str(tmp_path))
        status, headers, body = static.handle_request("GET", "/")
        assert status == 200
        assert b"<h1>index</h1>" in body

    def test_list_directory_via_list_directory_method(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        static = StaticFiles(directory=str(tmp_path))
        status, headers, body = static.list_directory("/")
        assert status == 200
        assert b"a.txt" in body
        assert b"b.txt" in body

    def test_list_directory_returns_html(self, tmp_path):
        (tmp_path / "x.txt").write_text("x")
        static = StaticFiles(directory=str(tmp_path))
        # list_directory returns HTML even though it's meant for debugging.
        status, headers, body = static.list_directory("/")
        assert status == 200
        assert isinstance(body, bytes)
        assert b"x.txt" in body


class TestStaticFilesNoListingByDefault:
    """Directory listing disabled by default."""

    def test_directory_returns_404_when_no_index(self, tmp_path):
        static = StaticFiles(directory=str(tmp_path))
        status, headers, body = static.handle_request("GET", "/")
        assert status == 404
