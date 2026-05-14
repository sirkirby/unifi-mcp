"""Shared Jinja2 render helper for /admin/* routes.

Every admin response sets Cache-Control: no-store. Templates are resolved
from apps/api/src/unifi_api/templates/admin/.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "admin"
_templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


def render(request: Request, name: str, context: dict[str, Any] | None = None) -> HTMLResponse:
    """Render a Jinja2 template with no-store caching."""
    response = _templates.TemplateResponse(request, name, context or {})
    response.headers["Cache-Control"] = "no-store"
    return response
