"""InnerSpace on the API: REST reads, the action endpoint and GraphQL, against the real core managers.

The console is a stand-in behind the real ``InnerSpaceConnectionManager`` (see
``tests/innerspace_data.py``). Every surface maps a core failure to fixed text:
REST 422/404/403/502, the action endpoint's generic failure with the class
audited, and GraphQL codes. No surface returns image bytes.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import select
from unifi_api.db.models import AuditLog
from unifi_core.exceptions import UniFiAuthError, UniFiMalformedResponseError, UniFiPermissionError, UniFiRateLimitError
from unifi_core.innerspace.managers.connection_manager import (
    INTEGRATION_PREFIX,
    SYSTEM_PATH,
    InnerSpaceConnectionManager,
    InnerSpaceHttpError,
)
from unifi_core.operation_gate import ControllerBusyError

from tests.innerspace_data import (
    DEVICE_IP,
    MAC,
    NOT_INSTALLED,
    PLAN,
    REJECTED,
    SECRET_VALUE,
    SITE,
    bootstrap,
    client,
    console_cm,
    graphql,
    install,
)

BASE = "/v1/sites/default/innerspace"
FLOOR_PLANS = f"{INTEGRATION_PREFIX}/floor_plans"


@pytest.fixture(autouse=True)
def _db_key(monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")


async def _app(tmp_path, cm=None, **kwargs):
    app, key, cid = await bootstrap(tmp_path, **kwargs)
    if cm is not None:
        install(app, cid, cm)
    return app, {"Authorization": f"Bearer {key}"}, key, cid


async def _get(app, headers, path, **params):
    async with client(app) as c:
        return await c.get(path, headers=headers, params=params)


async def _action(app, headers, cid, tool, args):
    async with client(app) as c:
        response = await c.post(
            f"/v1/actions/{tool}", headers=headers, json={"site": "default", "controller": cid, "args": args}
        )
    assert response.status_code == 200, response.text
    return response.json()


async def _audit(app) -> list[AuditLog]:
    async with app.state.sessionmaker() as session:
        return list((await session.execute(select(AuditLog))).scalars().all())


def _params_for(cm, path):
    return [call.kwargs.get("params") for call in cm.request.await_args_list if call.args[1] == path]


# ---------------------------------------------------------------------------
# REST reads, one per tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rest_status_and_project(tmp_path):
    app, headers, _key, _cid = await _app(tmp_path, console_cm())

    status = await _get(app, headers, f"{BASE}/status")
    project = await _get(app, headers, f"{BASE}/project")

    assert status.status_code == 200, status.text
    assert status.json()["data"] == {"installed": True, "running": True, "version": "1.4.3", "update_available": None}
    assert project.status_code == 200, project.text
    body = project.json()["data"]
    assert body["project"]["title"] == "Synthetic"
    assert [plan["id"] for plan in body["plans"]] == [PLAN]
    assert body["unit"] == "metric"
    assert body["shapes"] is None


@pytest.mark.asyncio
async def test_rest_project_shapes_carry_no_device_meta(tmp_path):
    app, headers, _key, _cid = await _app(tmp_path, console_cm())

    response = await _get(app, headers, f"{BASE}/project", include_shapes="true", unit="imperial")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["unit"] == "imperial"
    assert [shape["id"] for shape in data["shapes"]] == ["map-1", "wall-1", "wall-2", "device-1"]
    assert DEVICE_IP not in response.text
    assert MAC not in response.text


@pytest.mark.asyncio
async def test_rest_lists_forward_innerspace_site_and_ignore_path_site(tmp_path):
    cm = console_cm()
    app, headers, _key, _cid = await _app(tmp_path, cm)
    other_site = "/v1/sites/not-an-innerspace-site/innerspace"

    plans = await _get(app, headers, f"{other_site}/floor-plans", innerspace_site_id=SITE)
    points = await _get(app, headers, f"{other_site}/access-points", innerspace_site_id=SITE, unit="metric")
    switches = await _get(app, headers, f"{other_site}/switches")
    inventory = await _get(app, headers, f"{other_site}/inventory", innerspace_site_id=SITE)

    for response in (plans, points, switches, inventory):
        assert response.status_code == 200, response.text
        assert set(response.json()) == {"items", "render_hint"}
    assert [plan["id"] for plan in plans.json()["items"]] == [PLAN]
    assert plans.json()["items"][0]["image_filename"] == "00000000-0000-4000-8000-0000000000c2.png"
    assert [point["mac"] for point in points.json()["items"]] == [MAC]
    assert [switch["id"] for switch in switches.json()["items"]] == ["sw-1"]
    assert [device["id"] for device in inventory.json()["items"]] == ["inv-1"]
    assert _params_for(cm, f"{INTEGRATION_PREFIX}/access_points") == [{"siteId": SITE}]
    assert _params_for(cm, f"{INTEGRATION_PREFIX}/switches") == [None]
    assert _params_for(cm, f"{INTEGRATION_PREFIX}/inventory") == [{"siteId": SITE}]
    # The plan list filters by site; the access point and switch reads use their own site for plan geometry.
    assert _params_for(cm, FLOOR_PLANS) == [{"siteId": SITE}, {"siteId": SITE}, None]


@pytest.mark.asyncio
async def test_rest_walls_and_placed_devices_are_pages(tmp_path):
    app, headers, _key, _cid = await _app(tmp_path, console_cm())

    walls = await _get(app, headers, f"{BASE}/floor-plans/{PLAN}/walls", limit=1)
    devices = await _get(app, headers, f"{BASE}/floor-plans/{PLAN}/devices")

    assert walls.status_code == 200, walls.text
    page = walls.json()["data"]
    assert [wall["id"] for wall in page["walls"]] == ["wall-1"]
    assert (page["limit"], page["total"], page["truncated"], page["plan_id"]) == (1, 2, True, PLAN)
    assert devices.status_code == 200, devices.text
    page = devices.json()["data"]
    assert [device["id"] for device in page["devices"]] == ["device-1"]
    assert (page["limit"], page["total"], page["truncated"]) == (500, 1, False)
    assert page["devices"][0]["mac"] == MAC
    assert DEVICE_IP not in devices.text


@pytest.mark.asyncio
async def test_rest_plan_asset_is_metadata_only(tmp_path):
    cm = console_cm()
    app, headers, _key, _cid = await _app(tmp_path, cm)

    response = await _get(app, headers, f"{BASE}/floor-plans/{PLAN}/asset")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["filename"] == "00000000-0000-4000-8000-0000000000c2.png"
    assert data["content_type"] == "image/png"
    assert "image_base64" not in data
    cm.request_bytes.assert_not_awaited()


# ---------------------------------------------------------------------------
# Plan images: never bytes on the API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_image_bytes_on_any_api_surface(tmp_path):
    cm = console_cm()
    app, headers, key, cid = await _app(tmp_path, cm)

    rest = await _get(app, headers, f"{BASE}/floor-plans/{PLAN}/asset", include_image="true")
    refused = await _action(app, headers, cid, "innerspace_get_plan_asset", {"plan_id": PLAN, "include_image": True})
    action = await _action(app, headers, cid, "innerspace_get_plan_asset", {"plan_id": PLAN})
    body = await graphql(
        app, key, f'{{ innerspace {{ planAsset(controller: "{cid}", planId: "{PLAN}") {{ filename }} }} }}'
    )
    fields = await graphql(app, key, '{ __type(name: "InnerSpacePlanAsset") { fields { name } } }')

    assert rest.status_code == 422
    assert rest.json()["detail"] == {
        "kind": "invalid_innerspace_request",
        "message": "Failed to get InnerSpace plan asset: include_image is not supported by the API; read the image "
        "through the InnerSpace MCP server: its plan image resource, innerspace://plans/{plan_id}/image, serves "
        "PNG plan images; for other formats use innerspace_get_plan_asset with include_image on the MCP server.",
    }
    assert refused == {
        "success": False,
        "error": "Failed to execute action. Check the server audit log for details.",
    }
    assert action["success"] is True
    assert "image_base64" not in action["data"]
    assert body["data"]["innerspace"]["planAsset"] == {"filename": "00000000-0000-4000-8000-0000000000c2.png"}
    names = {field["name"] for field in fields["data"]["__type"]["fields"]}
    assert "filename" in names
    assert not any("image" in name.lower() and "base64" in name.lower() for name in names)
    cm.request_bytes.assert_not_awaited()
    rows = [row for row in await _audit(app) if row.outcome == "error"]
    assert [row.error_kind for row in rows] == ["ValueError"]
    assert "innerspace://plans/{plan_id}/image" in rows[0].detail


# ---------------------------------------------------------------------------
# Bad arguments on every surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_arguments_rest_action_graphql(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    cm = console_cm()
    app, headers, key, cid = await _app(tmp_path, cm)
    bad_plan = f"{REJECTED} x"

    bad_path = await _get(app, headers, f"{BASE}/floor-plans/{REJECTED}%20x/walls")
    bad_limit = await _get(app, headers, f"{BASE}/floor-plans/{PLAN}/walls", limit=0)
    bad_unit = await _get(app, headers, f"{BASE}/floor-plans/{PLAN}/devices", unit=REJECTED)
    bad_site = await _get(app, headers, f"{BASE}/floor-plans", innerspace_site_id=bad_plan)
    action_plan = await _action(app, headers, cid, "innerspace_list_walls", {"plan_id": bad_plan})
    action_extra = await _action(app, headers, cid, "innerspace_list_walls", {"plan_id": PLAN, "extra": REJECTED})
    gql = await graphql(
        app, key, f'{{ innerspace {{ walls(controller: "{cid}", planId: "{bad_plan}") {{ total }} }} }}'
    )
    gql_limit = await graphql(
        app, key, f'{{ innerspace {{ walls(controller: "{cid}", planId: "{PLAN}", limit: 0) {{ total }} }} }}'
    )

    for response in (bad_path, bad_limit, bad_unit, bad_site):
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["kind"] == "invalid_innerspace_request"
        assert "invalid arguments" in response.json()["detail"]["message"]
        assert REJECTED not in response.text
    for result in (action_plan, action_extra):
        assert result == {
            "success": False,
            "error": "Failed to execute action. Check the server audit log for details.",
        }
    rows = [row for row in await _audit(app) if row.outcome == "error"]
    assert [row.error_kind for row in rows] == ["ValidationError", "ValueError"]
    assert all(REJECTED not in (row.detail or "") for row in rows)
    for body in (gql, gql_limit):
        assert body["data"] is None
        assert body["errors"][0]["extensions"]["code"] == "BAD_REQUEST"
        assert body["errors"][0]["message"] == "Failed to list InnerSpace walls: invalid arguments."
    assert REJECTED not in str(gql)
    # The test client's own request log (httpx) is not the server's.
    server_logs = [record.getMessage() for record in caplog.records if not record.name.startswith("httpx")]
    assert server_logs
    assert not [message for message in server_logs if REJECTED in message]
    # Nothing reached the console for a rejected argument.
    assert not any(call.args[1] == f"{INTEGRATION_PREFIX}/project" for call in cm.request.await_args_list)


# ---------------------------------------------------------------------------
# Console failures: fixed text, never 404 for an undetermined lookup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_not_installed_is_502(tmp_path):
    app, headers, key, cid = await _app(tmp_path, console_cm({SYSTEM_PATH: NOT_INSTALLED}))

    rest = await _get(app, headers, f"{BASE}/floor-plans")
    action = await _action(app, headers, cid, "innerspace_list_floor_plans", {})
    gql = await graphql(app, key, f'{{ innerspace {{ floorPlans(controller: "{cid}") {{ id }} }} }}')

    assert rest.status_code == 502
    assert rest.json()["detail"] == {
        "kind": "innerspace_upstream_error",
        "message": "Failed to list InnerSpace floor plans: InnerSpace is not installed on this console",
    }
    assert action["success"] is False
    assert [row.error_kind for row in await _audit(app)] == ["InnerSpaceUnavailableError"]
    assert gql["errors"][0]["extensions"]["code"] == "UPSTREAM_ERROR"
    assert "InnerSpace is not installed on this console" in gql["errors"][0]["message"]


@pytest.mark.asyncio
async def test_init_failure_is_502_and_a_refused_login_is_not_retried(tmp_path, monkeypatch):
    logins = []

    async def _refused(self):
        logins.append(self)
        raise UniFiAuthError("synthetic refusal")

    monkeypatch.setattr(InnerSpaceConnectionManager, "_connect_once", _refused)
    app, headers, key, cid = await _app(tmp_path)

    rest = await _get(app, headers, f"{BASE}/status")
    again = await _get(app, headers, f"{BASE}/floor-plans")
    gql = await graphql(app, key, f'{{ innerspace {{ status(controller: "{cid}") {{ installed }} }} }}')

    assert (rest.status_code, again.status_code) == (502, 502)
    message = rest.json()["detail"]["message"]
    assert message.startswith("Failed to get InnerSpace status: Failed to initialize innerspace controller connection")
    assert "rejected the configured username and password" in message
    # The kept manager answers later calls inside its cool-down without logging in again.
    assert again.json()["detail"]["message"].startswith(
        "Failed to list InnerSpace floor plans: The UniFi OS console rejected"
    )
    assert "Automatic reconnect is paused" in again.json()["detail"]["message"]
    assert "synthetic refusal" not in rest.text + again.text
    assert gql["errors"][0]["extensions"]["code"] == "UPSTREAM_ERROR"
    assert len(logins) == 1
    assert list(app.state.manager_factory._connection_cache.values()) == logins


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status", "kind", "code"),
    [
        (UniFiPermissionError("list InnerSpace walls: refused"), 403, "innerspace_forbidden", "UPSTREAM_FORBIDDEN"),
        (InnerSpaceHttpError("list InnerSpace walls: HTTP 404", status=404), 502, "innerspace_upstream_error", None),
        (InnerSpaceHttpError("list InnerSpace walls: HTTP 503", status=503), 503, "innerspace_unavailable", None),
        (UniFiMalformedResponseError("list InnerSpace walls: not JSON"), 502, "innerspace_upstream_error", None),
        (
            UniFiRateLimitError("list InnerSpace walls: the console rate-limited the request (HTTP 429)"),
            429,
            "innerspace_rate_limited",
            "RATE_LIMITED",
        ),
    ],
)
async def test_console_failures_map_to_fixed_statuses(tmp_path, error, status, kind, code):
    app, headers, key, cid = await _app(tmp_path, console_cm(error=error))

    rest = await _get(app, headers, f"{BASE}/floor-plans/{PLAN}/walls")
    gql = await graphql(app, key, f'{{ innerspace {{ walls(controller: "{cid}", planId: "{PLAN}") {{ total }} }} }}')

    assert rest.status_code == status
    assert rest.json()["detail"]["kind"] == kind
    # Only the InnerSpace application's own 503 is retryable.
    assert ("Retry-After" in rest.headers) == (status == 503)
    # The core text already names the operation; it is not repeated.
    assert rest.json()["detail"]["message"] == f"Failed to {error}"
    assert gql["errors"][0]["extensions"]["code"] == (code or "UPSTREAM_ERROR")


@pytest.mark.asyncio
async def test_unknown_plan_is_404(tmp_path):
    app, headers, key, cid = await _app(tmp_path, console_cm())
    missing = "00000000-0000-4000-8000-0000000000ff"

    rest = await _get(app, headers, f"{BASE}/floor-plans/{missing}/walls")
    gql = await graphql(app, key, f'{{ innerspace {{ walls(controller: "{cid}", planId: "{missing}") {{ total }} }} }}')

    assert rest.status_code == 404
    assert rest.json()["detail"] == {
        "kind": "innerspace_not_found",
        "message": "Failed to list InnerSpace walls: not found.",
    }
    assert gql["errors"][0]["extensions"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_controller_without_innerspace_is_refused_on_every_surface(tmp_path):
    app, headers, key, cid = await _app(tmp_path, products="network")

    rest = await _get(app, headers, f"{BASE}/status")
    action = await _action(app, headers, cid, "innerspace_get_status", {})
    gql = await graphql(app, key, f'{{ innerspace {{ status(controller: "{cid}") {{ installed }} }} }}')

    assert rest.status_code == 409
    assert action["success"] is False
    assert gql["errors"][0]["extensions"]["code"] == "CAPABILITY_MISMATCH"
    assert app.state.manager_factory._connection_cache == {}


# ---------------------------------------------------------------------------
# Redaction policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("redact", "shown"), [(True, "***REDACTED***"), (False, SECRET_VALUE)])
async def test_project_follows_response_redaction_policy(tmp_path, redact, shown):
    app, headers, key, cid = await _app(tmp_path, console_cm(), redact=redact)

    rest = await _get(app, headers, f"{BASE}/project")
    action = await _action(app, headers, cid, "innerspace_get_project", {})
    gql = await graphql(app, key, f'{{ innerspace {{ project(controller: "{cid}") {{ attenuationObjectTypes }} }} }}')

    assert rest.json()["data"]["attenuation_object_types"][0]["password"] == shown
    assert action["data"]["attenuation_object_types"][0]["password"] == shown
    assert gql["data"]["innerspace"]["project"]["attenuationObjectTypes"][0]["password"] == shown


@pytest.mark.asyncio
async def test_wrong_typed_limit_rest_action_graphql(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    cm = console_cm()
    app, headers, key, cid = await _app(tmp_path, cm)

    rest = await _get(app, headers, f"{BASE}/floor-plans/{PLAN}/walls", limit=REJECTED)
    action = await _action(app, headers, cid, "innerspace_list_walls", {"plan_id": PLAN, "limit": REJECTED})
    gql = await graphql(
        app,
        key,
        f'{{ innerspace {{ walls(controller: "{cid}", planId: "{PLAN}", limit: "{REJECTED}") {{ total }} }} }}',
    )

    assert rest.status_code == 422
    assert REJECTED not in rest.text
    assert action == {"success": False, "error": "Failed to execute action. Check the server audit log for details."}
    rows = [row for row in await _audit(app) if row.outcome == "error"]
    assert [row.error_kind for row in rows] == ["ValueError"]
    assert REJECTED not in (rows[0].detail or "")
    assert gql["errors"][0]["extensions"]["code"] == "BAD_REQUEST"
    assert REJECTED not in str(gql)
    server_logs = [record.getMessage() for record in caplog.records if not record.name.startswith("httpx")]
    assert not [message for message in server_logs if REJECTED in message]
    assert not any(call.args[1] == f"{INTEGRATION_PREFIX}/project" for call in cm.request.await_args_list)


@pytest.mark.asyncio
async def test_a_result_without_a_required_field_is_502(tmp_path, monkeypatch):
    from unifi_core.innerspace.managers.system_manager import InnerSpaceSystemManager

    async def _partial(self):
        return {"running": True, "version": "1.4.3"}

    monkeypatch.setattr(InnerSpaceSystemManager, "get_status", _partial)
    app, headers, key, cid = await _app(tmp_path, console_cm())

    rest = await _get(app, headers, f"{BASE}/status")
    gql = await graphql(app, key, f'{{ innerspace {{ status(controller: "{cid}") {{ installed }} }} }}')

    assert rest.status_code == 502
    assert rest.json()["detail"] == {
        "kind": "innerspace_upstream_error",
        "message": "Failed to get InnerSpace status: InnerSpace returned a result without a required field",
    }
    assert gql["errors"][0]["extensions"]["code"] == "UPSTREAM_ERROR"
    assert gql["data"] is None


@pytest.mark.asyncio
async def test_a_busy_gate_is_the_shared_retryable_503_not_an_upstream_error(tmp_path, monkeypatch):
    """The read slot is taken inside the InnerSpace read; its refusal keeps the shared busy answer."""
    app, headers, key, cid = await _app(tmp_path, console_cm())
    cm = app.state.manager_factory

    async def busy(controller_id, product):
        raise ControllerBusyError(
            "The innerspace controller is busy: all 1 read slots stayed in use for 25s. Nothing was sent.",
            reason="wait_budget",
            retry_after=3,
        )

    monkeypatch.setattr(cm, "_take_read_slot", busy)

    rest = await _get(app, headers, f"{BASE}/floor-plans/{PLAN}/walls")
    gql = await graphql(app, key, f'{{ innerspace {{ walls(controller: "{cid}", planId: "{PLAN}") {{ total }} }} }}')

    assert rest.status_code == 503
    assert rest.json()["detail"]["kind"] == "controller_busy"
    assert rest.headers["Retry-After"] == "3"
    assert gql["errors"][0]["extensions"]["code"] == "CONTROLLER_BUSY"
