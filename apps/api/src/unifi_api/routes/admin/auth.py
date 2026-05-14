"""Admin UI login + logout routes.

Login is a thin shell — actual key validation happens client-side against
/v1/health/ready (admin-scoped). The server's POST handler trusts the
submitted key and returns the login template with a bootstrap_key context
value, whose inline script sets localStorage and redirects to /admin/.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request

from unifi_api.routes.admin._common import render

router = APIRouter()


@router.get("/admin/login", include_in_schema=False)
async def login_page(request: Request):
    return render(request, "login.html")


@router.post("/admin/login", include_in_schema=False)
async def login_submit(request: Request, key: str = Form(...)):
    return render(request, "login.html", {"bootstrap_key": key})


@router.get("/admin/logout", include_in_schema=False)
async def logout(request: Request):
    return render(request, "login.html", {"clear_storage": True})
