"""InnerSpace write actions on the API: catalog binding, request-only previews, confirmed writes, gates.

Confirmed writes run the real core managers against the stateful loopback console
(``testsupport/innerspace_stub.py``), so the CSRF header, the app check, the
single write and the read-back all happen on the wire.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from innerspace_stub import connected, console, manager  # noqa: F401  (fixtures, by name)
from jsonschema import Draft202012Validator
from sqlalchemy import select
from unifi_api.db.models import AuditLog
from unifi_api.graphql.schema import schema as graphql_schema
from unifi_api.services.actions import DispatchEntry, dispatch_action
from unifi_api.services.managers import _build_innerspace_managers
from unifi_api.services.manifest import ManifestRegistry, ToolEntry
from unifi_core.innerspace.managers.attenuation_manager import InnerSpaceAttenuationManager
from unifi_core.innerspace.managers.connection_manager import INTEGRATION_PREFIX, SHAPE_CHANGE_PATH, SYSTEM_PATH
from unifi_core.innerspace.managers.floor_plan_manager import InnerSpaceFloorPlanManager
from unifi_core.innerspace.managers.project_settings_manager import InnerSpaceProjectSettingsManager
from unifi_core.innerspace.managers.wall_manager import InnerSpaceWallManager
from unifi_core.innerspace.managers.wall_type_manager import InnerSpaceWallTypeManager

from tests.innerspace_data import PLAN, REJECTED, bootstrap, client, console_cm, install

FIXTURES = Path(__file__).resolve().parents[3] / "packages/unifi-core/tests/innerspace/fixtures"
PLAN_A = "00000000-0000-4000-8000-000000000003"
PLAN_B = "00000000-0000-4000-8000-000000000004"
PLAN_C = "00000000-0000-4000-8000-000000000005"
PLAN_D = "00000000-0000-4000-8000-000000000037"
STORED_WALL = "00000000-0000-4000-8000-000000000008"
# Plan A: 1000 x 800 px at 100 plan units per metre, plain map; frame (1, 1)-(3, 1) m is inside the image.
WALL = {"x1": 1.0, "y1": 1.0, "x2": 3.0, "y2": 1.0, "variant": "drywall"}
POLYGON = {"points": [{"x": 1, "y": 1}, {"x": 2, "y": 1}, {"x": 2, "y": 2}, {"x": 1, "y": 1}], "variant": "car"}

MANAGER_CLASSES = {
    "wall_manager": InnerSpaceWallManager,
    "wall_type_manager": InnerSpaceWallTypeManager,
    "attenuation_manager": InnerSpaceAttenuationManager,
    "floor_plan_manager": InnerSpaceFloorPlanManager,
    "project_settings_manager": InnerSpaceProjectSettingsManager,
}

# tool -> (category, action, valid args)
WRITES: dict[str, tuple[str, str, dict]] = {
    "innerspace_create_walls": ("walls", "create", {"plan_id": PLAN, "walls": [WALL], "unit": "metric"}),
    "innerspace_update_walls": (
        "walls",
        "update",
        {"plan_id": PLAN, "walls": [{"id": "wall-1", "variant": "glass"}], "unit": "metric"},
    ),
    "innerspace_remove_walls": ("walls", "delete", {"plan_id": PLAN, "wall_ids": ["wall-1"]}),
    "innerspace_create_wall_type": (
        "wall_types",
        "create",
        {"name": "Brick wall", "attenuation_db": 12.0, "color": "#aa5500"},
    ),
    "innerspace_update_wall_type": ("wall_types", "update", {"wall_type_id": "wt-1", "attenuation_db": 9.0}),
    "innerspace_create_attenuation_objects": (
        "attenuation",
        "create",
        {"plan_id": PLAN, "objects": [POLYGON], "unit": "metric"},
    ),
    "innerspace_update_attenuation_objects": (
        "attenuation",
        "update",
        {"plan_id": PLAN, "objects": [{"id": "ao-shape-1", "variant": "truck"}], "unit": "metric"},
    ),
    "innerspace_remove_attenuation_objects": ("attenuation", "delete", {"plan_id": PLAN, "object_ids": ["ao-1"]}),
    "innerspace_create_attenuation_object_type": (
        "attenuation",
        "create",
        {"name": "Rack", "attenuation_db": 6.0, "color": "#123456"},
    ),
    "innerspace_update_attenuation_object_type": (
        "attenuation",
        "update",
        {"attenuation_object_type_id": "ao-1", "color": "#654321"},
    ),
    "innerspace_rename_floor_plan": ("floor_plans", "update", {"plan_id": PLAN, "title": "Upstairs"}),
    "innerspace_set_floor_attenuation": ("floor_plans", "update", {"plan_id": PLAN, "attenuation_db": None}),
    "innerspace_reorder_floor_plans": ("floor_plans", "update", {"plan_ids": [PLAN]}),
    "innerspace_set_plan_scale": (
        "floor_plans",
        "delete",
        {"plan_id": PLAN, "x1": 0.0, "y1": 0.0, "x2": 2.0, "y2": 0.0, "length": 2.0, "unit": "metric"},
    ),
    "innerspace_set_project_unit": ("project", "update", {"unit": "imperial"}),
}


@pytest.fixture(autouse=True)
def _db_key(monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")


def _load(name: str):
    return json.loads((FIXTURES / name).read_text())


def _rows():
    return deepcopy(_load("v1_floor_plans.json")["floor_plans"])


def _state():
    data = deepcopy(_load("v1_project.json")["data"])
    data["project"]["unit"] = "metric"
    return data


def _ready(stub, *, applies: int = 1) -> None:
    """Serve the project from state and script the checks of ``applies`` confirmed writes."""
    stub.load_project(_state())
    stub.reply("GET", SYSTEM_PATH, _load("system.json"))
    for _ in range(applies):
        stub.script_write(floor_plans=_rows())


async def _app(tmp_path, cm):
    app, key, cid = await bootstrap(tmp_path)
    install(app, cid, cm)
    return app, {"Authorization": f"Bearer {key}"}, cid


async def _post(app, headers, cid, tool, args, *, confirm=False):
    async with client(app) as c:
        return await c.post(
            f"/v1/actions/{tool}",
            headers=headers,
            json={"site": "default", "controller": cid, "args": args, "confirm": confirm},
        )


async def _action(app, headers, cid, tool, args, *, confirm=False) -> dict:
    response = await _post(app, headers, cid, tool, args, confirm=confirm)
    assert response.status_code == 200, response.text
    return response.json()


async def _audit(app) -> list[AuditLog]:
    async with app.state.sessionmaker() as session:
        return list((await session.execute(select(AuditLog))).scalars().all())


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", sorted(WRITES))
def test_every_write_binds_to_its_apply_method(tool):
    entry = ManifestRegistry.load().resolve(tool)
    category, action, _ = WRITES[tool]

    assert entry.manager_method == "apply_" + tool.removeprefix("innerspace_")
    assert (entry.category, entry.permission_action, entry.read_only_hint) == (category, action, False)
    assert (entry.auth_method, entry.connection_kind) == ("local_only", "controller")
    # The factory builds the manager, and it has the method and its preview twin.
    manager_class = MANAGER_CLASSES[entry.manager_attr]
    assert entry.manager_attr in _build_innerspace_managers()
    assert callable(getattr(manager_class, entry.manager_method))
    assert callable(getattr(manager_class, "preview_" + entry.manager_method.removeprefix("apply_")))
    # The dispatcher passes the action's arguments as keywords, so the method takes every one of them.
    parameters = inspect.signature(getattr(manager_class, entry.manager_method)).parameters
    assert set(entry.input_schema["properties"]) <= set(parameters) - {"self"}


def test_every_write_tool_is_covered():
    registry = ManifestRegistry.load()
    writes = {
        name
        for name in registry.all_tools()
        if registry.resolve(name).product == "innerspace" and not registry.resolve(name).read_only_hint
    }

    assert writes == set(WRITES) and len(WRITES) == 15


@pytest.mark.parametrize("tool", sorted(WRITES))
def test_write_input_schemas_are_valid_and_accept_the_documented_arguments(tool):
    entry = ManifestRegistry.load().resolve(tool)
    Draft202012Validator.check_schema(entry.input_schema)
    validator = Draft202012Validator(entry.input_schema)

    assert list(validator.iter_errors(WRITES[tool][2])) == []
    assert "confirm" not in entry.input_schema["properties"]
    assert list(validator.iter_errors({**WRITES[tool][2], "extra": 1}))


def test_nested_item_schemas_carry_fields_enums_and_caps():
    registry = ManifestRegistry.load()
    walls = registry.resolve("innerspace_create_walls").input_schema["properties"]["walls"]
    objects = registry.resolve("innerspace_update_attenuation_objects").input_schema["properties"]["objects"]
    removes = registry.resolve("innerspace_remove_walls").input_schema["properties"]["wall_ids"]

    assert walls["maxItems"] == 100 and walls["items"]["additionalProperties"] is False
    assert "drywall" in walls["items"]["properties"]["variant"]["enum"]
    assert set(walls["items"]["required"]) == {"x1", "y1", "x2", "y2", "variant"}
    assert objects["maxItems"] == 100 and "id" in objects["items"]["required"]
    assert removes["maxItems"] == 50


def test_graphql_has_no_mutations():
    assert graphql_schema.as_str().count("type Mutation") == 0
    assert graphql_schema._schema.mutation_type is None


# ---------------------------------------------------------------------------
# Previews: request-only, nothing reaches the console
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_preview_is_request_only(tmp_path):
    cm = console_cm()
    app, headers, cid = await _app(tmp_path, cm)

    for tool, (category, _action_name, args) in WRITES.items():
        body = await _action(app, headers, cid, tool, args)
        assert body["success"] is True and body["requires_confirmation"] is True, tool
        assert body["tool"] == tool and body["product"] == "innerspace"
        assert body["resource_type"] == category
        # The preview repeats the request: every argument appears in it.
        for value in args.values():
            assert json.dumps(value) in json.dumps(body), (tool, value)

    assert cm.request.await_count == 0


# ---------------------------------------------------------------------------
# Confirmed writes on the loopback console
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmed_wall_create_then_a_repeat_is_already_applied(tmp_path, connected, console):  # noqa: F811
    _ready(console, applies=2)
    app, headers, cid = await _app(tmp_path, connected)
    args = {"plan_id": PLAN_A, "walls": [WALL], "unit": "metric"}

    preview = await _action(app, headers, cid, "innerspace_create_walls", args)
    assert preview["requires_confirmation"] is True and console.writes() == []

    applied = await _action(app, headers, cid, "innerspace_create_walls", args, confirm=True)
    assert applied["success"] is True and applied["mutation_applied"] is True
    (wall_id,) = applied["created_ids"]
    assert any(shape["id"] == wall_id for shape in console.project["shapes"])
    assert "warnings" in applied and "effects" in applied

    again = await _action(app, headers, cid, "innerspace_create_walls", args, confirm=True)
    assert again["success"] is True and again["mutation_applied"] is False
    assert again["noop"] == "already_applied" and again["created_ids"] == [wall_id]
    assert len(console.shape_changes()) == 1
    console.assert_csrf()


@pytest.mark.asyncio
async def test_confirmed_wall_remove_sends_the_stored_object(tmp_path, connected, console):  # noqa: F811
    _ready(console)
    app, headers, cid = await _app(tmp_path, connected)
    stored = next(shape for shape in console.project["shapes"] if shape["id"] == STORED_WALL)

    result = await _action(
        app, headers, cid, "innerspace_remove_walls", {"plan_id": PLAN_A, "wall_ids": [STORED_WALL]}, confirm=True
    )

    assert result["success"] is True and result["mutation_applied"] is True
    assert all(shape["id"] != STORED_WALL for shape in console.project["shapes"])
    (change,) = console.shape_changes()
    assert change["remove"] == [stored]
    console.assert_csrf()


@pytest.mark.asyncio
async def test_wall_type_create_carries_the_metadata_warnings(tmp_path, connected, console):  # noqa: F811
    _ready(console)
    app, headers, cid = await _app(tmp_path, connected)

    result = await _action(
        app, headers, cid, "innerspace_create_wall_type", WRITES["innerspace_create_wall_type"][2], confirm=True
    )

    assert result["success"] is True and result["mutation_applied"] is True
    assert isinstance(result["warnings"], list) and isinstance(result["effects"], dict)
    (type_id,) = result["created_ids"]
    assert [row["name"] for row in console.project["wallTypes"] if row["id"] == type_id] == ["Brick wall"]


# ---------------------------------------------------------------------------
# Failure shows as failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_write_is_failure_api(tmp_path, connected, console):  # noqa: F811
    _ready(console, applies=2)
    app, headers, cid = await _app(tmp_path, connected)
    # A definite refusal with an unchanged read-back is "not applied" (a lost answer would be unknown).
    console.refuse("POST", SHAPE_CHANGE_PATH)

    not_applied = await _action(
        app,
        headers,
        cid,
        "innerspace_create_walls",
        {"plan_id": PLAN_A, "walls": [WALL], "unit": "metric"},
        confirm=True,
    )
    console.mixed_batch(keep=1)
    second = {**WALL, "y1": 2.0, "y2": 2.0}
    unknown = await _action(
        app,
        headers,
        cid,
        "innerspace_create_walls",
        {"plan_id": PLAN_A, "walls": [WALL, second], "unit": "metric"},
        confirm=True,
    )

    assert not_applied["success"] is False and not_applied["mutation_applied"] is False
    assert not_applied["error"].endswith("the read-back shows no change; nothing was applied.")
    assert len(console.shape_changes()) == 2  # one per call, never replayed
    assert unknown["success"] is False and unknown["mutation_applied"] is None
    assert "read before retrying" in unknown["error"].lower()
    outcomes = [row.outcome for row in await _audit(app)]
    assert outcomes == ["error", "error"]


def test_an_unknown_outcome_is_never_a_success():
    from unifi_api.serializers.innerspace.writes import InnerSpaceWriteSerializer
    from unifi_core.write_verification import WriteVerificationResult

    result = WriteVerificationResult(success=True, mutation_applied=None, operation="create InnerSpace walls")

    shaped = InnerSpaceWriteSerializer().serialize_action(result, tool_name="innerspace_create_walls")

    assert shaped["success"] is False and shaped["mutation_applied"] is None


@pytest.mark.asyncio
async def test_a_stopped_app_keeps_the_generic_error_contract(tmp_path, connected, console):  # noqa: F811
    console.load_project(_state())
    app_entry = {"name": "innerspace", "isInstalled": True, "isRunning": False, "version": "1.4.3"}
    console.reply("GET", SYSTEM_PATH, {"apps": {"controllers": [app_entry]}})
    app, headers, cid = await _app(tmp_path, connected)

    result = await _action(
        app,
        headers,
        cid,
        "innerspace_create_walls",
        {"plan_id": PLAN_A, "walls": [WALL], "unit": "metric"},
        confirm=True,
    )

    assert result == {"success": False, "error": "Failed to execute action. Check the server audit log for details."}
    assert console.writes() == []
    (row,) = await _audit(app)
    assert row.error_kind == "InnerSpaceUnavailableError"
    assert "not running" in row.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["other-version", "no-version", "two-sites"])
async def test_a_confirmed_write_runs_on_any_version_and_site_layout(tmp_path, connected, console, case):  # noqa: F811
    console.load_project(_state())
    rows = _rows()
    if case == "two-sites":
        rows[1]["site_id"] = "00000000-0000-4000-8000-0000000000ff"
    console.script_write(version={"other-version": "1.5.0", "no-version": None}.get(case, "1.4.3"), floor_plans=rows)
    app, headers, cid = await _app(tmp_path, connected)

    result = await _action(
        app,
        headers,
        cid,
        "innerspace_create_walls",
        {"plan_id": PLAN_A, "walls": [WALL], "unit": "metric"},
        confirm=True,
    )

    assert result["success"] is True and result["mutation_applied"] is True
    (wall_id,) = result["created_ids"]
    assert any(shape["id"] == wall_id for shape in console.project["shapes"])


@pytest.mark.asyncio
async def test_a_confirmed_plan_scale_runs_on_an_imperial_project(tmp_path, connected, console):  # noqa: F811
    console.load_project(_state())
    console.project["project"]["unit"] = "imperial"
    console.script_write(floor_plans=_rows())
    # The read-back: 200 plan units over 2.5 m, as the console computes it.
    rows = _rows()
    rows[0]["ppm"] = 80.0
    console.reply("GET", f"{INTEGRATION_PREFIX}/floor_plans", {"floor_plans": rows})
    app, headers, cid = await _app(tmp_path, connected)
    args = {"plan_id": PLAN_A, "x1": 1.0, "y1": 1.0, "x2": 3.0, "y2": 1.0, "length": 2.5, "unit": "metric"}

    result = await _action(app, headers, cid, "innerspace_set_plan_scale", args, confirm=True)

    assert result["success"] is True and result["mutation_applied"] is True
    ((line,),) = [body["create"] for body in console.shape_changes()]
    assert line["scale"] == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# Gates and caps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("variable", ["UNIFI_READ_ONLY", "UNIFI_INNERSPACE_READ_ONLY"])
@pytest.mark.parametrize("confirm", [False, True])
async def test_read_only_blocks_previews_and_writes(tmp_path, monkeypatch, variable, confirm):
    monkeypatch.setenv(variable, "true")
    cm = console_cm()
    app, headers, cid = await _app(tmp_path, cm)

    response = await _post(
        app, headers, cid, "innerspace_create_walls", WRITES["innerspace_create_walls"][2], confirm=confirm
    )
    read = await _post(app, headers, cid, "innerspace_get_status", {})

    assert response.status_code == 403
    assert "read-only mode" in response.json()["detail"]
    assert read.status_code == 200 and read.json()["success"] is True
    assert [call.args[1] for call in cm.request.await_args_list] == [SYSTEM_PATH]
    denied = [row for row in await _audit(app) if row.outcome == "denied"]
    assert [row.error_kind for row in denied] == ["read_only_mode"]


@pytest.mark.asyncio
@pytest.mark.parametrize("variable", ["UNIFI_POLICY_INNERSPACE_WALLS_DELETE", "UNIFI_POLICY_DELETE"])
@pytest.mark.parametrize("confirm", [False, True])
async def test_a_delete_gate_blocks_removal_but_not_creation(tmp_path, monkeypatch, variable, confirm):
    monkeypatch.setenv(variable, "false")
    cm = console_cm()
    app, headers, cid = await _app(tmp_path, cm)

    removal = await _post(
        app, headers, cid, "innerspace_remove_walls", WRITES["innerspace_remove_walls"][2], confirm=confirm
    )
    creation = await _action(app, headers, cid, "innerspace_create_walls", WRITES["innerspace_create_walls"][2])

    assert removal.status_code == 403
    assert removal.json()["detail"].startswith("Delete is disabled by policy for walls.")
    assert creation["requires_confirmation"] is True
    assert cm.request.await_count == 0
    denied = [row for row in await _audit(app) if row.outcome == "denied"]
    assert [row.error_kind for row in denied] == ["policy_gate"]


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [False, True])
async def test_a_server_wide_action_gate_blocks_that_action_in_every_category(tmp_path, monkeypatch, confirm):
    """UNIFI_POLICY_INNERSPACE_<ACTION> sits between the category gate and the global one, as on MCP."""
    monkeypatch.setenv("UNIFI_POLICY_INNERSPACE_CREATE", "false")
    cm = console_cm()
    app, headers, cid = await _app(tmp_path, cm)

    for tool, (category, action, args) in WRITES.items():
        response = await _post(app, headers, cid, tool, args, confirm=confirm)
        if action == "create":
            assert response.status_code == 403, tool
            assert f"Create is disabled by policy for {category}." in response.json()["detail"], tool
        else:
            assert response.status_code != 403, tool


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,args",
    [
        ("innerspace_create_walls", {"plan_id": PLAN, "walls": [WALL] * 101, "unit": "metric"}),
        (
            "innerspace_update_walls",
            {"plan_id": PLAN, "walls": [{"id": "w", "variant": "glass"}] * 101, "unit": "metric"},
        ),
        ("innerspace_remove_walls", {"plan_id": PLAN, "wall_ids": [f"w{i}" for i in range(51)]}),
        ("innerspace_remove_attenuation_objects", {"plan_id": PLAN, "object_ids": [f"o{i}" for i in range(51)]}),
        ("innerspace_create_walls", {"plan_id": PLAN, "walls": [{**WALL, "variant": "cardboard"}], "unit": "metric"}),
        ("innerspace_create_walls", {"plan_id": PLAN, "walls": [WALL], "unit": "furlongs"}),
    ],
)
async def test_caps_and_refusals_before_any_request(tmp_path, tool, args):
    cm = console_cm()
    app, headers, cid = await _app(tmp_path, cm)

    for confirm in (False, True):
        result = await _action(app, headers, cid, tool, args, confirm=confirm)
        assert result == {
            "success": False,
            "error": "Failed to execute action. Check the server audit log for details.",
        }
    assert cm.request.await_count == 0
    assert {row.error_kind for row in await _audit(app)} == {"ValueError"}


@pytest.mark.asyncio
async def test_core_validation_refusal_echoes_no_value(tmp_path):
    """The schema accepts any string id; the core model refuses this one, and its text carries no input."""
    cm = console_cm()
    app, headers, cid = await _app(tmp_path, cm)
    wall = {**WALL, "variant": "custom", "wall_type_id": f"{REJECTED} /x"}

    result = await _action(
        app, headers, cid, "innerspace_create_walls", {"plan_id": PLAN, "walls": [wall], "unit": "metric"}, confirm=True
    )

    assert result == {"success": False, "error": "Failed to execute action. Check the server audit log for details."}
    (row,) = await _audit(app)
    assert row.error_kind == "ValidationError"
    assert REJECTED not in (row.detail or "")
    assert cm.request.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [False, True])
async def test_each_gate_blocks_its_write_action_and_read_only_blocks_them_all(tmp_path, monkeypatch, confirm):
    cm = console_cm()
    app, headers, cid = await _app(tmp_path, cm)

    for tool, (category, action, args) in WRITES.items():
        variable = f"UNIFI_POLICY_INNERSPACE_{category.upper()}_{action.upper()}"
        for env, expected in (
            ({variable: "false"}, f"{action.capitalize()} is disabled by policy for {category}."),
            ({"UNIFI_INNERSPACE_READ_ONLY": "true"}, "read-only mode"),
        ):
            with monkeypatch.context() as scoped:
                for key, value in env.items():
                    scoped.setenv(key, value)
                response = await _post(app, headers, cid, tool, args, confirm=confirm)
            assert response.status_code == 403, (tool, env)
            assert expected in response.json()["detail"], (tool, env)

    assert cm.request.await_count == 0
    assert {row.error_kind for row in await _audit(app)} == {"policy_gate", "read_only_mode"}


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["network", "protect", "access"])
async def test_policy_gates_apply_to_innerspace_actions_only(monkeypatch, product):
    """Negative control: the other products' catalog categories are not their gate categories, so no gate applies."""
    monkeypatch.setenv("UNIFI_POLICY_DELETE", "false")
    monkeypatch.setenv(f"UNIFI_POLICY_{product.upper()}_TEST_DELETE", "false")
    tool_name = f"{product}_delete_test_resource"
    entry = ToolEntry(
        name=tool_name,
        product=product,
        category="test",
        manager="test_manager",
        method="apply_action",
        permission_action="delete",
        read_only_hint=False,
    )
    product_manager = MagicMock(apply_action=AsyncMock(return_value={"success": True}))
    factory = MagicMock(get_domain_manager=AsyncMock(return_value=product_manager))

    result = await dispatch_action(
        registry=ManifestRegistry({tool_name: entry}),
        factory=factory,
        session=MagicMock(),
        tool_name=tool_name,
        controller_id="cid",
        controller_products=[product],
        site="default",
        args={"resource_id": "r-1"},
        confirm=True,
        dispatch_table={tool_name: DispatchEntry(manager_attr="test_manager", method="apply_action")},
    )

    assert result == {"success": True}
    product_manager.apply_action.assert_awaited_once_with(resource_id="r-1")


@pytest.fixture
def fresh_gates():
    from unifi_core.operation_gate import reset_gate_registry_for_tests

    reset_gate_registry_for_tests()
    yield
    reset_gate_registry_for_tests()


@pytest.mark.asyncio
async def test_a_confirmed_action_holds_the_consoles_write_turn(tmp_path, connected, console, monkeypatch, fresh_gates):  # noqa: F811
    """The action endpoint runs a confirmed InnerSpace write as the gate's write, like the other products."""
    from unifi_api.services.operation_gate import gate_for
    from unifi_core.innerspace.managers.wall_manager import InnerSpaceWallManager

    _ready(console)
    app, headers, cid = await _app(tmp_path, connected)
    held: list[bool] = []
    real = InnerSpaceWallManager.apply_create_walls

    async def observed(self, *args, **kwargs):
        held.append(gate_for(cid, "innerspace").holds_write())
        return await real(self, *args, **kwargs)

    monkeypatch.setattr(InnerSpaceWallManager, "apply_create_walls", observed)

    applied = await _action(
        app,
        headers,
        cid,
        "innerspace_create_walls",
        {"plan_id": PLAN_A, "walls": [WALL], "unit": "metric"},
        confirm=True,
    )

    assert applied["success"] is True
    assert held == [True]
    assert gate_for(cid, "innerspace").snapshot()["counters"]["writes_granted"] == 1


class _GateClock:
    """The gate's clock, set by hand: it decides how much of a write's hold budget is left."""

    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "spent_at, applied, text, posts",
    [
        ("turn_start", False, "time budget ran out before the change was sent", 0),
        ("before_the_write", False, "time budget ran out before the change was sent", 0),
        ("after_the_post", None, "Read before retrying", 1),
    ],
)
async def test_an_action_cut_off_at_its_hold_budget_reports_its_outcome(
    tmp_path,
    connected,  # noqa: F811
    console,  # noqa: F811
    monkeypatch,
    fresh_gates,
    spent_at,
    applied,
    text,
    posts,
):
    """The action carries the write layer's outcome: false when nothing was sent, unknown once the POST went out."""
    from unifi_api.services.operation_gate import gate_for

    _ready(console)
    late = spent_at == "after_the_post"
    if late:
        console.reply("POST", SHAPE_CHANGE_PATH, {"data": {}}, delay=0.5)
    app, headers, cid = await _app(tmp_path, connected)
    gate = gate_for(cid, "innerspace")
    gate.clock = clock = _GateClock()
    budget = gate.settings.hold_budget_seconds
    real_apply = InnerSpaceWallManager.apply_create_walls
    real_request = connected.request

    async def spend_first(self, *args, **kwargs):
        clock.value += 10_000
        return await real_apply(self, *args, **kwargs)

    async def spend_at_the_post(method, path, **kwargs):
        if method == "POST":
            # A fifth of a second left, so the slow answer is cut off after the send; otherwise out of time before it.
            clock.value = budget - 0.2 if late else clock.value + 10_000
        return await real_request(method, path, **kwargs)

    if spent_at == "turn_start":
        monkeypatch.setattr(InnerSpaceWallManager, "apply_create_walls", spend_first)
    else:
        monkeypatch.setattr(connected, "request", spend_at_the_post)

    result = await _action(
        app,
        headers,
        cid,
        "innerspace_create_walls",
        {"plan_id": PLAN_A, "walls": [WALL], "unit": "metric"},
        confirm=True,
    )

    assert result["success"] is False
    assert result["mutation_applied"] is applied
    assert text in json.dumps(result)
    assert len(console.calls("POST", SHAPE_CHANGE_PATH)) == posts


@pytest.mark.asyncio
async def test_a_refused_write_answers_the_generic_error_and_audits_its_class(tmp_path, monkeypatch):
    """A refusal before any send (an identical earlier create partly in place) is audited by class, value-free."""
    from unifi_core.innerspace.managers._writes import InnerSpaceWriteRefusedError

    cm = console_cm()
    app, headers, cid = await _app(tmp_path, cm)
    monkeypatch.setattr(
        InnerSpaceWallManager,
        "apply_create_walls",
        AsyncMock(side_effect=InnerSpaceWriteRefusedError("create InnerSpace walls: refused")),
    )

    result = await _action(
        app, headers, cid, "innerspace_create_walls", {"plan_id": PLAN, "walls": [WALL], "unit": "metric"}, confirm=True
    )

    assert result == {"success": False, "error": "Failed to execute action. Check the server audit log for details."}
    (row,) = await _audit(app)
    assert row.error_kind == "InnerSpaceWriteRefusedError"
    assert cm.request.await_count == 0
