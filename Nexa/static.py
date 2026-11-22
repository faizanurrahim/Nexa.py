"""Static file serving for Nexa.py.

Provides safe static file serving with path traversal protection, MIME type
detection, content-length, HEAD support, cache headers, and conditional
requests.

Usage::

    from Nexa import StaticFiles

    static = StaticFiles(directory="public")
    response = static.handle_request(method="GET", path="/css/style.css")
"""

from __future__ import annotations

import datetime
import hashlib
import mimetypes
import os
import time
from email.utils import formatdate, parsedate_to_datetime
from email.utils import formatdate
from pathlib import Path
from typing import Any, Optional, Tuple

# ---------------------------------------------------------------------------
# MIME types
# ---------------------------------------------------------------------------

_mimetypes_read: Optional[mimetypes.MimeTypes] = None


def _get_mimetypes() -> mimetypes.MimeTypes:
    global _mimetypes_read
    if _mimetypes_read is None:
        _mimetypes_read = mimetypes.MimeTypes()
    return _mimetypes_read


# ---------------------------------------------------------------------------
# Static files handler
# ---------------------------------------------------------------------------


class StaticFiles:
    """Serve static files from a directory safely.

    Paths are resolved relative to :paramref:`directory` with traversal
    protection.  The handler returns a ``(status, headers, body)`` tuple that
    can be used directly in a Nexa response pipeline.
    """

    def __init__(
        self,
        directory: Union[str, Path],
        *,
        index_file: Optional[str] = "index.html",
        follow_symlinks: bool = False,
        cache_max_age: int = 3600,
        file_url_prefix: str = "/static",
    ) -> None:
        """Initialise the static file handler.

        :param directory: Directory to serve files from.
        :param index_file: Optional index file name for directory requests.
        :param follow_symlinks: When ``True``, symlinks are followed.
        :param cache_max_age: Default ``Cache-Control`` max-age in seconds.
        :param file_url_prefix: URL prefix for static files.
        """
        self._directory = Path(directory).resolve()
        self._index_file = index_file
        self._follow_symlinks = follow_symlinks
        self._cache_max_age = cache_max_age
        self._file_url_prefix = file_url_prefix.rstrip("/")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle_request(
        self,
        method: str,
        path: str,
        *,
        accept_encoding: Optional[str] = None,
        if_modified_since: Optional[str] = None,
        if_none_match: Optional[str] = None,
    ) -> Tuple[int, list, Any]:
        """Handle a static file request.

        Returns ``(status, headers, body)`` where *body* is either ``bytes``
        or a file-like object for streaming.

        :param method: HTTP method (GET or HEAD).
        :param path: URL path (without the static prefix).
        :param accept_encoding: Optional ``Accept-Encoding`` header value.
        :param if_modified_since: Optional ``If-Modified-Since`` header value.
        :param if_none_match: Optional ``If-None-Match`` header value.
        """
        method_upper = method.upper()
        if method_upper not in ("GET", "HEAD"):
            return 405, [("Allow", "GET, HEAD")], b"Method Not Allowed"

        file_path = self._resolve_path(path)
        if file_path is None:
            return 404, [], b"Not Found"

        if file_path.is_dir():
            if self._index_file:
                index_path = file_path / self._index_file
                if index_path.is_file():
                    file_path = index_path
                else:
                    return 404, [], b"Not Found"
            else:
                return 404, [], b"Not Found"

        if not file_path.is_file():
            return 404, [], b"Not Found"

        # Stat the file.
        try:
            stat = file_path.stat()
        except OSError:
            return 404, [], b"Not Found"

        file_size = stat.st_size
        file_mtime = stat.st_mtime
        file_mtime_header = formatdate(timeval=file_mtime, usegmt=True)

        content_type = self._guess_content_type(file_path)
        headers: list = [
            ("Content-Type", content_type),
            ("Content-Length", str(file_size)),
            ("Last-Modified", file_mtime_header),
            ("Cache-Control", f"public, max-age={self._cache_max_age}"),
        ]

        # ETag based on size + mtime + inode (where available).
        inode = getattr(stat, "st_ino", 0)
        etag = f'"{hashlib.md5(f"{file_size}-{file_mtime}-{inode}".encode()).hexdigest()}"'
        headers.append(("ETag", etag))

        # Conditional request handling.
        if if_none_match and if_none_match == etag:
            return 304, headers, b""

        if if_modified_since:
            from email.utils import parsedate_to_datetime
            try:
                ifmod = parsedate_to_datetime(if_modified_since)
                file_dt = datetime.datetime.fromtimestamp(file_mtime, tz=datetime.timezone.utc)
                if file_dt <= ifmod:
                    return 304, headers, b""
            except (ValueError, TypeError):
                pass

        if method_upper == "HEAD":
            return 200, headers, b""

        # Return the file content.  For large files, a file object can be used,
        # but for simplicity and compatibility with the existing pipeline, we
        # return bytes.  The caller is responsible for memory usage.
        try:
            body = file_path.read_bytes()
        except OSError:
            return 500, [], b"Internal Server Error"

        return 200, headers, body

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_path(self, url_path: str) -> Optional[Path]:
        """Resolve a URL path to a file path, with traversal protection."""
        # Strip leading slash.
        clean = url_path.lstrip("/")
        if not clean:
            return self._directory

        # Join with the base directory and resolve.
        joined = self._directory / clean
        try:
            resolved = joined.resolve()
        except (OSError, ValueError):
            return None

        # Ensure the resolved path is under the base directory.
        try:
            resolved.relative_to(self._directory)
        except ValueError:
            return None

        # Symlink safety.
        if not self._follow_symlinks and resolved.is_symlink():
            return None

        return resolved

    def _guess_content_type(self, path: Path) -> str:
        """Guess the content type for a file path."""
        mt = _get_mimetypes().guess_type(str(path))[0]
        return mt or "application/octet-stream"

    def list_directory(self, url_path: str) -> Tuple[int, list, Any]:
        """Generate a directory listing response (for debugging only)."""
        file_path = self._resolve_path(url_path)
        if file_path is None or not file_path.is_dir():
            return 404, [], b"Not Found"

        entries = sorted(file_path.iterdir())
        lines = [
            "<html><head><title>Directory listing</title></head><body>",
            f"<h2>{self._directory}/{url_path}</h2>",
            "<ul>",
        ]
        for entry in entries:
            name = entry.name
            if entry.is_dir():
                name += "/"
            elif entry.is_symlink():
                name += "@"
            display = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            lines.append(f'<li><a href="{display}">{display}</a></li>')
        lines.append("</ul></body></html>")
        body = "\n".join(lines).encode("utf-8")
        return 200, [("Content-Type", "text/html; charset=utf-8")], body
