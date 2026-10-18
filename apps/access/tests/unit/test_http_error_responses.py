"""The HTTP transports never send a Python traceback to a client.

Starlette's debug mode answers an unhandled exception with the full traceback,
including file paths and the exception message. AGENTS.md: raw tracebacks MUST
NOT be exposed to MCP clients.
"""

import pytest
from starlette.routing import Route
from starlette.testclient import TestClient

_DETAIL = "detail-that-must-not-reach-the-client"


async def _raise(request):
    raise RuntimeError(_DETAIL)


def _server():
    from unifi_access_mcp.runtime import get_server

    return get_server()


def test_server_is_not_built_in_debug_mode():
    assert _server().settings.debug is False


@pytest.mark.parametrize("build_app", ["streamable_http_app", "sse_app"])
def test_unhandled_http_error_returns_no_traceback(build_app):
    app = getattr(_server(), build_app)()
    app.router.routes.append(Route("/raise", _raise))

    response = TestClient(app, raise_server_exceptions=False).get("/raise")

    assert response.status_code == 500
    assert "Traceback" not in response.text
    assert _DETAIL not in response.text
