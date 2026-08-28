from __future__ import annotations

import ast
import dis
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_api_action_catalog.py"
REPO_ROOT = SCRIPT_PATH.parents[1]


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_api_action_catalog", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_synthetic_repo(root: Path) -> None:
    manifest_path = root / "apps/network/src/unifi_network_mcp/tools_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "count": 2,
                "module_map": {
                    "unifi_list_zebras": "unifi_network_mcp.tools.widgets",
                    "unifi_list_widgets": "unifi_network_mcp.tools.widgets",
                },
                "tools": [
                    {
                        "name": "unifi_list_zebras",
                        "permission_category": "widgets",
                        "annotations": {"readOnlyHint": True},
                        "schema": {
                            "input": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string"},
                                    "confirm": {"type": "boolean"},
                                },
                                "required": ["query", "confirm"],
                            }
                        },
                    },
                    {
                        "name": "unifi_list_widgets",
                        "permission_category": "widgets",
                        "annotations": {"readOnlyHint": True},
                        "schema": {"input": {"type": "object", "properties": {}}},
                    },
                ],
            }
        )
    )
    source_path = root / "apps/network/src/unifi_network_mcp/tools/widgets.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        """
from unifi_network_mcp.runtime import server, widget_manager

@server.tool(name="unifi_list_zebras")
async def list_zebras():
    return await widget_manager.get_zebras()

@server.tool(name="unifi_list_widgets")
async def list_widgets():
    return await widget_manager.get_widgets()
""".lstrip()
    )

    for product, package in (
        ("protect", "unifi_protect_mcp"),
        ("access", "unifi_access_mcp"),
    ):
        empty_manifest = root / f"apps/{product}/src/{package}/tools_manifest.json"
        empty_manifest.parent.mkdir(parents=True)
        empty_manifest.write_text(json.dumps({"count": 0, "module_map": {}, "tools": []}))

    managers_path = root / "apps/api/src/unifi_api/services/managers.py"
    managers_path.parent.mkdir(parents=True)
    managers_path.write_text(
        """
def _build_network_managers():
    return {"widget_manager": lambda cm: object()}

def _build_protect_managers():
    return {}

def _build_access_managers():
    return {}
""".lstrip()
    )


def _manifest(root: Path, product: str = "network") -> tuple[Path, dict]:
    package = f"unifi_{product}_mcp"
    path = root / f"apps/{product}/src/{package}/tools_manifest.json"
    return path, json.loads(path.read_text())


def _replace_manifest(root: Path, transform) -> None:
    path, payload = _manifest(root)
    transform(payload)
    path.write_text(json.dumps(payload))


def test_render_catalog_is_deterministic_and_normalizes_reads(tmp_path: Path) -> None:
    generator = _load_generator()
    _write_synthetic_repo(tmp_path)

    first = generator.render_catalog(
        tmp_path,
        binding_overrides={},
        exclusions={},
    )
    second = generator.render_catalog(
        tmp_path,
        binding_overrides={},
        exclusions={},
    )

    assert first == second
    assert first.endswith("\n")
    assert not first.endswith("\n\n")
    payload = json.loads(first)
    assert payload == {
        "schema_version": 1,
        "generated_by": "scripts/generate_api_action_catalog.py",
        "actions": [
            {
                "name": "unifi_list_widgets",
                "product": "network",
                "category": "widgets",
                "permission_action": "read",
                "read_only_hint": True,
                "manager_attr": "widget_manager",
                "manager_method": "get_widgets",
                "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "unifi_list_zebras",
                "product": "network",
                "category": "widgets",
                "permission_action": "read",
                "read_only_hint": True,
                "manager_attr": "widget_manager",
                "manager_method": "get_zebras",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        ],
        "excluded": [],
    }


def test_generator_meta_tool_suffixes_match_shared_contract() -> None:
    generator = _load_generator()
    source = REPO_ROOT / "packages/unifi-mcp-shared/src/unifi_mcp_shared/meta_tools.py"
    tree = ast.parse(source.read_text(), filename=str(source))
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "META_TOOL_SUFFIXES"
    )

    assert tuple(ast.literal_eval(assignment.value)) == generator.META_TOOL_SUFFIXES


@pytest.mark.parametrize(
    ("permission_action", "read_only_hint", "expected"),
    [
        ("update", True, "conflicting safety metadata"),
        (None, False, "mutation permission_action"),
        ("launch", False, "mutation permission_action"),
        ("read", None, "readOnlyHint must be boolean"),
    ],
)
def test_invalid_safety_metadata_fails_closed(
    tmp_path: Path,
    permission_action: str | None,
    read_only_hint: bool | None,
    expected: str,
) -> None:
    generator = _load_generator()
    _write_synthetic_repo(tmp_path)

    def transform(payload: dict) -> None:
        tool = payload["tools"][0]
        if permission_action is None:
            tool.pop("permission_action", None)
        else:
            tool["permission_action"] = permission_action
        tool["annotations"]["readOnlyHint"] = read_only_hint

    _replace_manifest(tmp_path, transform)

    with pytest.raises(generator.CatalogGenerationError, match=expected):
        generator.render_catalog(tmp_path, binding_overrides={}, exclusions={})


def test_duplicate_action_names_across_products_fail(tmp_path: Path) -> None:
    generator = _load_generator()
    _write_synthetic_repo(tmp_path)
    network_path, network = _manifest(tmp_path)
    protect_path, protect = _manifest(tmp_path, "protect")
    protect["tools"] = [network["tools"][0]]
    protect["module_map"] = {
        network["tools"][0]["name"]: "unifi_protect_mcp.tools.widgets",
    }
    protect_path.write_text(json.dumps(protect))
    source = tmp_path / "apps/protect/src/unifi_protect_mcp/tools/widgets.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from unifi_protect_mcp.runtime import server, widget_manager\n"
        '@server.tool(name="unifi_list_zebras")\n'
        "async def list_zebras():\n"
        "    return await widget_manager.get_zebras()\n"
    )
    managers = tmp_path / "apps/api/src/unifi_api/services/managers.py"
    managers.write_text(
        managers.read_text().replace(
            "def _build_protect_managers():\n    return {}",
            'def _build_protect_managers():\n    return {"widget_manager": lambda cm: object()}',
        )
    )

    with pytest.raises(generator.CatalogGenerationError, match="duplicate action name"):
        generator.render_catalog(tmp_path, binding_overrides={}, exclusions={})


def test_unbound_tool_requires_binding_or_exclusion(tmp_path: Path) -> None:
    generator = _load_generator()
    _write_synthetic_repo(tmp_path)
    source = tmp_path / "apps/network/src/unifi_network_mcp/tools/widgets.py"
    source.write_text(source.read_text().replace("return await widget_manager.get_zebras()", "return {'zebras': []}"))

    with pytest.raises(generator.CatalogGenerationError, match="no Core manager binding"):
        generator.render_catalog(tmp_path, binding_overrides={}, exclusions={})


@pytest.mark.parametrize(
    ("bindings", "exclusions", "expected"),
    [
        ({"unifi_missing": ("widget_manager", "get_widgets")}, {}, "source tool does not exist"),
        ({}, {"unifi_missing": ("network", "not an action")}, "source tool does not exist"),
        (
            {
                "unifi_list_widgets": type(
                    "Override", (), {"manager_attr": "widget_manager", "manager_method": "get_widgets", "reason": ""}
                )()
            },
            {},
            "reason must not be empty",
        ),
        ({}, {"unifi_list_widgets": ("network", "")}, "reason must not be empty"),
    ],
)
def test_stale_or_unexplained_declarations_fail(
    tmp_path: Path,
    bindings: dict,
    exclusions: dict,
    expected: str,
) -> None:
    generator = _load_generator()
    _write_synthetic_repo(tmp_path)

    with pytest.raises(generator.CatalogGenerationError, match=expected):
        generator.render_catalog(tmp_path, binding_overrides=bindings, exclusions=exclusions)


def test_unknown_manager_attribute_fails(tmp_path: Path) -> None:
    generator = _load_generator()
    _write_synthetic_repo(tmp_path)
    override = type(
        "Override",
        (),
        {"manager_attr": "missing_manager", "manager_method": "get_widgets", "reason": "explicit test"},
    )()

    with pytest.raises(generator.CatalogGenerationError, match="not registered by ManagerFactory"):
        generator.render_catalog(
            tmp_path,
            binding_overrides={"unifi_list_widgets": override},
            exclusions={},
        )


def test_check_mode_does_not_write_stale_output(tmp_path: Path) -> None:
    generator = _load_generator()
    _write_synthetic_repo(tmp_path)
    output = tmp_path / "catalog.json"
    output.write_text("stale\n")

    rendered = generator.render_catalog(tmp_path, binding_overrides={}, exclusions={})
    original_render = generator.render_catalog
    generator.render_catalog = lambda _root: rendered
    try:
        with pytest.raises(generator.CatalogGenerationError, match="catalog is stale"):
            generator.generate_catalog(tmp_path, output, check=True)
    finally:
        generator.render_catalog = original_render

    assert output.read_text() == "stale\n"


def test_repository_catalog_is_complete_with_only_streaming_exclusions() -> None:
    generator = _load_generator()

    payload = json.loads(generator.render_catalog(REPO_ROOT))

    assert len(payload["actions"]) == 271
    assert [item["name"] for item in payload["excluded"]] == [
        "access_subscribe_events",
        "protect_subscribe_events",
        "unifi_subscribe_events",
    ]
    by_name = {item["name"]: item for item in payload["actions"]}
    assert (by_name["unifi_list_events"]["manager_attr"], by_name["unifi_list_events"]["manager_method"]) == (
        "event_manager",
        "get_events",
    )
    assert (by_name["unifi_list_alarms"]["manager_attr"], by_name["unifi_list_alarms"]["manager_method"]) == (
        "event_manager",
        "get_alarms",
    )
    assert by_name["unifi_recent_events"]["manager_method"] == "get_recent_from_buffer"
    assert by_name["unifi_get_event_types"]["manager_method"] == "get_event_type_prefixes"
    assert by_name["unifi_archive_alarm"]["manager_method"] == "archive_alarm"
    assert by_name["unifi_archive_all_alarms"]["manager_method"] == "archive_all_alarms"
    assert (
        by_name["unifi_create_firewall_zone"]["manager_attr"],
        by_name["unifi_create_firewall_zone"]["manager_method"],
    ) == (
        "firewall_manager",
        "create_firewall_zone",
    )
    assert by_name["unifi_delete_firewall_zone"]["manager_method"] == "delete_firewall_zone"


def test_repository_catalog_bindings_resolve_to_core_manager_methods() -> None:
    """Keep generated dispatch bindings synchronized with the Core bridge."""
    generator = _load_generator()
    payload = json.loads(generator.render_catalog(REPO_ROOT))

    from unifi_api.services.managers import _PRODUCT_BUILDERS

    manager_types: dict[tuple[str, str], type] = {}
    for product, factory in _PRODUCT_BUILDERS.items():
        for manager_attr, builder in factory().items():
            closure = dict(zip(builder.__code__.co_freevars, builder.__closure__ or (), strict=True))
            target_name = next(
                instruction.argval
                for instruction in dis.get_instructions(builder)
                if instruction.opname == "LOAD_DEREF" and instruction.argval in closure
            )
            manager_types[(product, manager_attr)] = closure[target_name].cell_contents

    missing = [
        f"{action['name']} -> {action['product']}.{action['manager_attr']}.{action['manager_method']}"
        for action in payload["actions"]
        if not hasattr(
            manager_types[(action["product"], action["manager_attr"])],
            action["manager_method"],
        )
    ]

    assert missing == []


def test_makefile_generates_catalog_after_product_manifests_and_checks_drift() -> None:
    manifest = subprocess.run(
        ["make", "-n", "manifest"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    commands = [
        "make -C apps/network manifest",
        "make -C apps/protect manifest",
        "make -C apps/access manifest",
        "scripts/generate_api_action_catalog.py",
        "make skill-references",
        "make server-manifests",
    ]
    positions = [manifest.index(command) for command in commands]
    assert positions == sorted(positions)

    check_generated = subprocess.run(
        ["make", "-n", "check-generated"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "scripts/generate_api_action_catalog.py --check" in check_generated

    pre_commit = subprocess.run(
        ["make", "-n", "-j4", "pre-commit"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    stages = [
        "make format",
        "make generate",
        "make lint",
        "make test",
        "make check-generated",
        "make worker-typecheck",
    ]
    stage_positions = [pre_commit.index(stage) for stage in stages]
    assert stage_positions == sorted(stage_positions)
