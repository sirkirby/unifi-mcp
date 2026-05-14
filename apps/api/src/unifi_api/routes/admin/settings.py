"""Admin UI: /admin/settings — audit retention + log file config + manual prune."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.admin._common import render
from unifi_api.services.audit_pruner import prune_audit

router = APIRouter()


# Defaults match the migration seed data so a fresh DB without seeded rows
# (e.g. test DBs that use Base.metadata.create_all instead of running migrations)
# still renders sensible values.
_AUDIT_DEFAULTS = {
    "max_age_days": 90,
    "max_rows": 1_000_000,
    "enabled": True,
    "prune_interval_hours": 6,
}
_LOGS_DEFAULTS = {
    "enabled": True,
    "path": "state/api.log",
    "max_bytes": 10 * 1024 * 1024,
    "backup_count": 5,
    "level": "INFO",
}


async def _read_settings(svc) -> dict:
    """Materialize the typed settings dict the form needs."""
    return {
        "audit": {
            "max_age_days": await svc.get_int("audit.retention.max_age_days", default=_AUDIT_DEFAULTS["max_age_days"]),
            "max_rows": await svc.get_int("audit.retention.max_rows", default=_AUDIT_DEFAULTS["max_rows"]),
            "enabled": await svc.get_bool("audit.retention.enabled", default=_AUDIT_DEFAULTS["enabled"]),
            "prune_interval_hours": await svc.get_int(
                "audit.retention.prune_interval_hours", default=_AUDIT_DEFAULTS["prune_interval_hours"]
            ),
        },
        "logs": {
            "enabled": await svc.get_bool("logs.file.enabled", default=_LOGS_DEFAULTS["enabled"]),
            "path": await svc.get_str("logs.file.path", default=_LOGS_DEFAULTS["path"]),
            "max_bytes": await svc.get_int("logs.file.max_bytes", default=_LOGS_DEFAULTS["max_bytes"]),
            "backup_count": await svc.get_int("logs.file.backup_count", default=_LOGS_DEFAULTS["backup_count"]),
            "level": await svc.get_str("logs.file.level", default=_LOGS_DEFAULTS["level"]),
        },
    }


@router.get("/admin/settings", include_in_schema=False)
async def settings_page(request: Request):
    """Unauth HTMX shell — the form fragment is admin-scoped and pre-populated."""
    return render(request, "settings/page.html")


@router.get(
    "/admin/settings/_form",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def settings_form(request: Request):
    svc = request.app.state.settings_service
    return render(request, "settings/_form.html", {"s": await _read_settings(svc), "saved": False})


def _coerce_checkbox(value: str) -> bool:
    return (value or "").strip().lower() in ("on", "true", "1", "yes")


@router.post(
    "/admin/settings/save",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def settings_save(
    request: Request,
    audit_max_age_days: int = Form(...),
    audit_max_rows: int = Form(...),
    audit_enabled: str = Form(""),
    audit_prune_interval_hours: int = Form(...),
    logs_enabled: str = Form(""),
    logs_max_bytes: int = Form(...),
    logs_backup_count: int = Form(...),
    logs_level: str = Form(...),
):
    """Persist the changed settings and re-render the form with a 'Saved' indicator.

    Note: `logs.file.path` is intentionally NOT writable here — changing the
    path requires a service restart anyway, so the field is rendered readonly
    and excluded from the form post.
    """
    svc = request.app.state.settings_service
    await svc.set_int("audit.retention.max_age_days", audit_max_age_days)
    await svc.set_int("audit.retention.max_rows", audit_max_rows)
    await svc.set_bool("audit.retention.enabled", _coerce_checkbox(audit_enabled))
    await svc.set_int("audit.retention.prune_interval_hours", audit_prune_interval_hours)
    await svc.set_bool("logs.file.enabled", _coerce_checkbox(logs_enabled))
    await svc.set_int("logs.file.max_bytes", logs_max_bytes)
    await svc.set_int("logs.file.backup_count", logs_backup_count)
    await svc.set_str("logs.file.level", logs_level)
    return render(
        request,
        "settings/_form.html",
        {"s": await _read_settings(svc), "saved": True},
    )


@router.post(
    "/admin/settings/_prune",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def settings_prune(request: Request):
    """Manual 'Prune now' button. Runs prune_audit using the current settings
    values and renders the result fragment."""
    svc = request.app.state.settings_service
    sm = request.app.state.sessionmaker
    max_age = await svc.get_int("audit.retention.max_age_days", default=_AUDIT_DEFAULTS["max_age_days"])
    max_rows = await svc.get_int("audit.retention.max_rows", default=_AUDIT_DEFAULTS["max_rows"])
    result = await prune_audit(sm, max_age_days=max_age, max_rows=max_rows)
    return render(request, "settings/_prune_result.html", {"result": result})
