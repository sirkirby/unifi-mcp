"""Exhaustive public-action to Core-manager invocation contract."""

from __future__ import annotations

import dis
import inspect
import json
from pathlib import Path

from unifi_api.services.dispatch_overrides import (
    DISPATCH_ARG_TRANSLATORS,
    DISPATCH_DIRECT_RESULT_ADAPTERS,
    DISPATCH_RESULT_ADAPTERS,
    UNSUPPORTED_ACTION_PARAMETERS,
)
from unifi_api.services.managers import _PRODUCT_BUILDERS

REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCT_PACKAGES = {
    "network": "unifi_network_mcp",
    "protect": "unifi_protect_mcp",
    "access": "unifi_access_mcp",
}


def _manager_types() -> dict[tuple[str, str], type]:
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
    return manager_types


def test_every_catalog_action_can_invoke_its_core_manager_signature() -> None:
    catalog = json.loads((REPO_ROOT / "apps/api/src/unifi_api/action_catalog.json").read_text())
    manifests: dict[str, dict] = {}
    for product, package in PRODUCT_PACKAGES.items():
        payload = json.loads((REPO_ROOT / f"apps/{product}/src/{package}/tools_manifest.json").read_text())
        manifests.update({tool["name"]: tool for tool in payload["tools"]})

    manager_types = _manager_types()
    failures: list[str] = []
    catalog_names = {action["name"] for action in catalog["actions"]}
    stale_translators = sorted(set(DISPATCH_ARG_TRANSLATORS) - catalog_names)
    if stale_translators:
        failures.append(f"stale translators: {stale_translators}")
    for label, mapping in {
        "direct-result adapters": DISPATCH_DIRECT_RESULT_ADAPTERS,
        "result adapters": DISPATCH_RESULT_ADAPTERS,
        "unsupported-parameter declarations": UNSUPPORTED_ACTION_PARAMETERS,
    }.items():
        stale = sorted(set(mapping) - catalog_names)
        if stale:
            failures.append(f"stale {label}: {stale}")

    for action in catalog["actions"]:
        name = action["name"]
        input_schema = manifests[name]["schema"]["input"]
        public_parameters = set(input_schema.get("properties", {})) - {"confirm"}
        public_required = set(input_schema.get("required", [])) - {"confirm"}
        manager_type = manager_types[(action["product"], action["manager_attr"])]
        method = getattr(manager_type, action["manager_method"])
        signature = inspect.signature(method)
        parameters = {key: value for key, value in signature.parameters.items() if key != "self"}
        accepts_kwargs = any(value.kind is inspect.Parameter.VAR_KEYWORD for value in parameters.values())
        accepted = {
            key
            for key, value in parameters.items()
            if value.kind
            in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }
        }
        required = {
            key
            for key, value in parameters.items()
            if value.default is inspect.Parameter.empty
            and value.kind not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
        }

        translator = DISPATCH_ARG_TRANSLATORS.get(name)
        dispatched = set(translator.manager_parameters) if translator is not None else public_parameters
        unexpected = set() if accepts_kwargs else dispatched - accepted
        guaranteed = dispatched if translator is not None else public_required
        missing = required - guaranteed
        if unexpected or missing:
            failures.append(
                f"{name} -> {action['manager_attr']}.{action['manager_method']} "
                f"unexpected={sorted(unexpected)} missing={sorted(missing)}"
            )

    assert failures == []


def test_unsupported_action_parameters_are_real_public_contract_fields() -> None:
    manifests: dict[str, dict] = {}
    for product, package in PRODUCT_PACKAGES.items():
        payload = json.loads((REPO_ROOT / f"apps/{product}/src/{package}/tools_manifest.json").read_text())
        manifests.update({tool["name"]: tool for tool in payload["tools"]})

    failures: list[str] = []
    for tool_name, unsupported in UNSUPPORTED_ACTION_PARAMETERS.items():
        public = set(manifests[tool_name]["schema"]["input"].get("properties", {})) - {"confirm"}
        unknown = unsupported - public
        if unknown:
            failures.append(f"{tool_name}: unknown unsupported parameters {sorted(unknown)}")
    assert failures == []
