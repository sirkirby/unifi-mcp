#!/usr/bin/env python3
"""Generate the API-owned action catalog from product MCP source artifacts."""

from __future__ import annotations

import argparse
import ast
import copy
import difflib
import dis
import inspect
import json
import sys
from pathlib import Path
from typing import Any, Mapping

PRODUCTS: tuple[tuple[str, str], ...] = (
    ("network", "unifi_network_mcp"),
    ("protect", "unifi_protect_mcp"),
    ("access", "unifi_access_mcp"),
)
SCHEMA_VERSION = 1
GENERATED_BY = "scripts/generate_api_action_catalog.py"
DEFAULT_OUTPUT = Path("apps/api/src/unifi_api/action_catalog.json")
MUTATION_ACTIONS = frozenset({"create", "update", "delete"})
# Kept local so the drift checker remains runnable after the standalone API
# test target removes MCP packages from the workspace environment. A contract
# test keeps this tuple synchronized with unifi_mcp_shared.meta_tools.
META_TOOL_SUFFIXES: tuple[str, ...] = (
    "_tool_index",
    "_execute",
    "_batch",
    "_batch_status",
    "_load_tools",
    "_get_support_bundle",
)


class CatalogGenerationError(ValueError):
    """Raised when source metadata cannot produce a safe complete catalog."""


def _is_meta_tool(name: str) -> bool:
    return name.endswith(META_TOOL_SUFFIXES)


def _load_api_configuration(repo_root: Path) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    api_src = repo_root / "apps/api/src"
    sys.path.insert(0, str(api_src))
    try:
        from unifi_api.services import dispatch_overrides

        bindings = getattr(
            dispatch_overrides,
            "DISPATCH_BINDING_OVERRIDES",
            getattr(dispatch_overrides, "DISPATCH_OVERRIDES", {}),
        )
        exclusions = getattr(dispatch_overrides, "API_ACTION_EXCLUSIONS", {})
        translators = getattr(dispatch_overrides, "DISPATCH_ARG_TRANSLATORS", {})
        return bindings, exclusions, translators
    finally:
        sys.path.remove(str(api_src))


def _manager_types(repo_root: Path) -> dict[tuple[str, str], type]:
    """Resolve registered Core manager classes without constructing managers."""
    api_src = repo_root / "apps/api/src"
    sys.path.insert(0, str(api_src))
    try:
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
        return manager_types
    finally:
        sys.path.remove(str(api_src))


def _manager_attributes(repo_root: Path) -> dict[str, set[str]]:
    path = repo_root / "apps/api/src/unifi_api/services/managers.py"
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise CatalogGenerationError(f"cannot parse API manager registry {path}: {exc}") from exc

    managers: dict[str, set[str]] = {}
    for product, _package in PRODUCTS:
        function_name = f"_build_{product}_managers"
        function = next(
            (
                node
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
            ),
            None,
        )
        if function is None:
            raise CatalogGenerationError(f"missing {function_name} in API manager registry {path}")
        returned = next((node.value for node in ast.walk(function) if isinstance(node, ast.Return)), None)
        if not isinstance(returned, ast.Dict):
            raise CatalogGenerationError(f"{function_name} in {path} must return a literal manager mapping")
        keys = {
            key.value
            for key in returned.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value
        }
        managers[product] = keys
    return managers


def _runtime_names(tree: ast.Module, package: str) -> set[str]:
    names: set[str] = set()
    runtime_module = f"{package}.runtime"
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == runtime_module:
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _tool_name(decorator: ast.expr) -> str | None:
    if not isinstance(decorator, ast.Call):
        return None
    if not isinstance(decorator.func, ast.Attribute) or decorator.func.attr != "tool":
        return None
    for keyword in decorator.keywords:
        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
            return keyword.value.value if isinstance(keyword.value.value, str) else None
    return None


def _first_manager_call(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_names: set[str],
) -> tuple[str, str] | None:
    calls = sorted(
        (node for node in ast.walk(function) if isinstance(node, ast.Call)),
        key=lambda node: (node.lineno, node.col_offset),
    )
    for call in calls:
        target = call.func
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id in runtime_names
            and target.value.id not in {"server", "logger"}
        ):
            return target.value.id, target.attr
    return None


def _source_bindings(path: Path, package: str) -> dict[str, tuple[str, str]]:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise CatalogGenerationError(f"cannot parse product tool source {path}: {exc}") from exc
    runtime_names = _runtime_names(tree, package)
    bindings: dict[str, tuple[str, str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = next((name for dec in node.decorator_list if (name := _tool_name(dec))), None)
        if not name:
            continue
        binding = _first_manager_call(node, runtime_names)
        if binding is not None:
            bindings[name] = binding
    return bindings


def _override_fields(value: Any) -> tuple[str, str, str]:
    if isinstance(value, tuple) and len(value) == 2:
        return value[0], value[1], "legacy explicit dispatch override"
    manager_attr = getattr(value, "manager_attr", None)
    manager_method = getattr(value, "manager_method", None)
    reason = getattr(value, "reason", None)
    if not all(isinstance(item, str) for item in (manager_attr, manager_method, reason)):
        raise CatalogGenerationError(f"invalid binding override record: {value!r}")
    return manager_attr, manager_method, reason


def _exclusion_fields(value: Any) -> tuple[str, str]:
    if isinstance(value, tuple) and len(value) == 2:
        return value
    product = getattr(value, "product", None)
    reason = getattr(value, "reason", None)
    if not isinstance(product, str) or not isinstance(reason, str):
        raise CatalogGenerationError(f"invalid action exclusion record: {value!r}")
    return product, reason


def _source_path(repo_root: Path, product: str, package: str, module: str) -> Path:
    prefix = f"{package}."
    if not module.startswith(prefix):
        raise CatalogGenerationError(f"{product}: module {module!r} is outside package {package!r}")
    relative = Path(*module[len(prefix) :].split(".")).with_suffix(".py")
    return repo_root / f"apps/{product}/src/{package}" / relative


def _api_input_schema(tool: dict[str, Any], *, product: str, name: str, path: Path) -> dict[str, Any]:
    """Return the strict action-args schema derived from one MCP tool schema.

    The REST action envelope carries ``confirm`` separately, so it is removed
    from the generated args schema. Unknown top-level kwargs are rejected to
    preserve the MCP server's strict-dispatch contract.
    """
    raw = tool.get("schema", {}).get("input")
    if not isinstance(raw, dict) or raw.get("type") != "object":
        raise CatalogGenerationError(f"{product}:{name} in {path}: schema.input must be an object schema")
    properties = raw.get("properties")
    if not isinstance(properties, dict):
        raise CatalogGenerationError(f"{product}:{name} in {path}: schema.input.properties must be an object")

    schema = copy.deepcopy(raw)
    schema["properties"].pop("confirm", None)
    required = schema.get("required")
    if required is not None:
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise CatalogGenerationError(f"{product}:{name} in {path}: schema.input.required must be a string array")
        filtered_required = [item for item in required if item != "confirm"]
        if filtered_required:
            schema["required"] = filtered_required
        else:
            schema.pop("required", None)
    schema["additionalProperties"] = False
    return schema


def render_catalog(
    repo_root: Path,
    *,
    binding_overrides: Mapping[str, Any] | None = None,
    exclusions: Mapping[str, Any] | None = None,
) -> str:
    """Render a deterministic catalog from manifests and product tool source."""
    repo_root = repo_root.resolve()
    validate_invocations = binding_overrides is None and exclusions is None
    translator_specs: Mapping[str, Any] = {}
    if binding_overrides is None or exclusions is None:
        defaults = _load_api_configuration(repo_root)
        binding_overrides = defaults[0] if binding_overrides is None else binding_overrides
        exclusions = defaults[1] if exclusions is None else exclusions
        translator_specs = defaults[2]

    registered_managers = _manager_attributes(repo_root)
    manager_types = _manager_types(repo_root) if validate_invocations else {}
    source_tools: dict[str, tuple[str, dict[str, Any], Path]] = {}
    discovered_bindings: dict[str, tuple[str, str]] = {}

    for product, package in PRODUCTS:
        manifest_path = repo_root / f"apps/{product}/src/{package}/tools_manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogGenerationError(f"cannot read {product} manifest {manifest_path}: {exc}") from exc
        tools = manifest.get("tools")
        module_map = manifest.get("module_map")
        if not isinstance(tools, list) or not isinstance(module_map, dict):
            raise CatalogGenerationError(f"{product}: malformed manifest {manifest_path}")

        module_bindings: dict[Path, dict[str, tuple[str, str]]] = {}
        for raw_tool in tools:
            if not isinstance(raw_tool, dict) or not isinstance(raw_tool.get("name"), str):
                raise CatalogGenerationError(f"{product}: malformed tool entry in {manifest_path}")
            name = raw_tool["name"]
            if _is_meta_tool(name):
                continue
            if name in source_tools:
                previous_product = source_tools[name][0]
                raise CatalogGenerationError(
                    f"{product}:{name}: duplicate action name already declared by {previous_product} in {manifest_path}"
                )
            module = module_map.get(name)
            if not isinstance(module, str) or not module:
                raise CatalogGenerationError(f"{product}:{name}: missing module_map entry in {manifest_path}")
            path = _source_path(repo_root, product, package, module)
            source_tools[name] = (product, raw_tool, path)
            if path not in module_bindings:
                module_bindings[path] = _source_bindings(path, package)
            binding = module_bindings[path].get(name)
            if binding is not None:
                discovered_bindings[name] = binding

    normalized_overrides: dict[str, tuple[str, str, str]] = {}
    for name, value in binding_overrides.items():
        if name not in source_tools:
            raise CatalogGenerationError(f"override:{name}: source tool does not exist")
        manager_attr, manager_method, reason = _override_fields(value)
        if not reason.strip():
            raise CatalogGenerationError(f"override:{name}: reason must not be empty")
        normalized_overrides[name] = (manager_attr, manager_method, reason)

    normalized_exclusions: dict[str, tuple[str, str]] = {}
    for name, value in exclusions.items():
        if name not in source_tools:
            raise CatalogGenerationError(f"exclusion:{name}: source tool does not exist")
        product, reason = _exclusion_fields(value)
        source_product = source_tools[name][0]
        if product != source_product:
            raise CatalogGenerationError(
                f"exclusion:{name}: product {product!r} does not match source product {source_product!r}"
            )
        if not reason.strip():
            raise CatalogGenerationError(f"exclusion:{name}: reason must not be empty")
        normalized_exclusions[name] = (product, reason)

    actions: list[dict[str, Any]] = []
    for name, (product, tool, path) in source_tools.items():
        if name in normalized_exclusions:
            continue
        annotations = tool.get("annotations")
        read_only_hint = annotations.get("readOnlyHint") if isinstance(annotations, dict) else None
        if not isinstance(read_only_hint, bool):
            raise CatalogGenerationError(f"{product}:{name} in {path}: annotations.readOnlyHint must be boolean")
        permission_action = tool.get("permission_action")
        if read_only_hint:
            if permission_action not in (None, "", "read"):
                raise CatalogGenerationError(
                    f"{product}:{name} in {path}: conflicting safety metadata permission_action={permission_action!r}"
                )
            permission_action = "read"
        elif permission_action not in MUTATION_ACTIONS:
            raise CatalogGenerationError(
                f"{product}:{name} in {path}: mutation permission_action must be create, update, or delete"
            )

        if name in normalized_overrides:
            manager_attr, manager_method, _reason = normalized_overrides[name]
        else:
            binding = discovered_bindings.get(name)
            if binding is None:
                raise CatalogGenerationError(f"{product}:{name} in {path}: no Core manager binding discovered")
            manager_attr, manager_method = binding
        if manager_attr not in registered_managers[product]:
            raise CatalogGenerationError(
                f"{product}:{name} in {path}: manager attribute {manager_attr!r} is not registered by ManagerFactory"
            )

        if validate_invocations:
            manager_type = manager_types[(product, manager_attr)]
            method = getattr(manager_type, manager_method, None)
            if method is None or not callable(method):
                raise CatalogGenerationError(
                    f"{product}:{name} in {path}: manager method {manager_attr}.{manager_method} does not exist"
                )
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
            input_schema = tool.get("schema", {}).get("input", {})
            public_parameters = set(input_schema.get("properties", {})) - {"confirm"}
            public_required = set(input_schema.get("required", [])) - {"confirm"}
            translator = translator_specs.get(name)
            dispatched = set(translator.manager_parameters) if translator is not None else public_parameters
            unexpected = set() if accepts_kwargs else dispatched - accepted
            guaranteed = dispatched if translator is not None else public_required
            missing = required - guaranteed
            if unexpected or missing:
                raise CatalogGenerationError(
                    f"{product}:{name} in {path}: invocation contract for {manager_attr}.{manager_method} "
                    f"has unexpected={sorted(unexpected)} missing={sorted(missing)}; add a tested argument translator"
                )

        category = tool.get("permission_category")
        if not isinstance(category, str) or not category:
            module = path.stem
            category = module
        actions.append(
            {
                "name": name,
                "product": product,
                "category": category,
                "permission_action": permission_action,
                "read_only_hint": read_only_hint,
                "manager_attr": manager_attr,
                "manager_method": manager_method,
                "input_schema": _api_input_schema(tool, product=product, name=name, path=path),
            }
        )

    excluded = [
        {"name": name, "product": product, "reason": reason}
        for name, (product, reason) in normalized_exclusions.items()
    ]
    stale_translators = sorted(set(translator_specs) - set(source_tools))
    if stale_translators:
        raise CatalogGenerationError(f"argument translators reference missing source tools: {stale_translators}")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": GENERATED_BY,
        "actions": sorted(actions, key=lambda item: item["name"]),
        "excluded": sorted(excluded, key=lambda item: item["name"]),
    }
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"


def generate_catalog(repo_root: Path, output_path: Path, *, check: bool) -> bool:
    rendered = render_catalog(repo_root)
    output_path = output_path if output_path.is_absolute() else repo_root / output_path
    existing = output_path.read_text() if output_path.exists() else ""
    if existing == rendered:
        return True
    if check:
        diff = "".join(
            difflib.unified_diff(
                existing.splitlines(keepends=True),
                rendered.splitlines(keepends=True),
                fromfile=str(output_path),
                tofile="generated",
            )
        )
        raise CatalogGenerationError(f"generated API action catalog is stale:\n{diff}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        generate_catalog(args.repo_root, args.output, check=args.check)
    except CatalogGenerationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
