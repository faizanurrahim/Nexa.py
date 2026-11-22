
import json
from typing import Any, Optional


class JSONResponse:
    """A response that renders its data as JSON.
    
    This class is also re-exported by nxserver.jsonify() and can be used
    directly if you prefer the explicit style.
    """

    def __init__(
        self,
        data: Any,
        status: int = 200,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.data = data
        self.status = status
        self.headers = dict(headers) if headers else {}

    def render(self) -> str:
        """Return the JSON-encoded body for this response."""
        return json.dumps(self.data, ensure_ascii=False)


def jsonify(data: Any, status: int = 200, headers: Optional[dict[str, str]] = None) -> JSONResponse:
    """Create a JSON response for a Nexa route.

    Args:
        data: Any JSON-serializable value (dicts, lists, strings, numbers,
            booleans, and None all work).
        status: HTTP status code to attach to the response. Defaults to 200.

    Returns:
        A JSONResponse instance that the Nexa server can render.
    """
    return JSONResponse(data=data, status=status, headers=headers)
