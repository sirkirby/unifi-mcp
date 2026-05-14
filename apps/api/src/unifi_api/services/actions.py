"""Action dispatcher.

Resolves an MCP ``tool_name`` to a concrete domain manager method on a
per-controller manager instance and invokes it.

Architectural background
------------------------
``tools_manifest.json`` (loaded by :mod:`unifi_api.services.manifest`) does
not record which manager class / method backs each tool — it only describes
the public tool contract. To bridge the gap without modifying every tool
module or the manifest generator, this module **AST-introspects each tool
module at startup** and records the first awaited ``<runtime_singleton>.<method>(...)``
call inside each ``@server.tool()`` function. The runtime singleton's
attribute name (e.g. ``client_manager``) is then resolved per-request via
:meth:`unifi_api.services.managers.ManagerFactory.get_domain_manager`.

Trade-offs
----------
- Pure AST introspection isn't infallible. Tools that branch through multiple
  managers, or whose first manager call is conditional on ``confirm``, may
  expose only one of multiple methods. For Phase 2 / Task 12 this is
  acceptable — the dispatch surface used by Task 13 will be limited to
  read-only and simple action tools whose body has a single manager call.
- Tools whose call goes through ``await some_helper(client_manager, ...)``
  (i.e. the manager is passed as an argument rather than the receiver) are
  not captured. None of the canonical tool modules use that pattern today.

Public surface
--------------
- :class:`CapabilityMismatch`
- :func:`dispatch_action`
- :func:`build_dispatch_table` (exposed for tests)
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import logging
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from unifi_api.services.dispatch_overrides import (
    DISPATCH_ARG_TRANSLATORS,
    DISPATCH_OVERRIDES,
)
from unifi_api.services.managers import ManagerFactory
from unifi_api.services.manifest import ManifestRegistry, ToolEntry

logger = logging.getLogger(__name__)


_DEFAULT_PRODUCTS: tuple[str, ...] = ("network", "protect", "access")

# Tool category directories under apps/<product>/src/unifi_<product>_mcp/tools/
# are dynamic; we discover them by walking the ``tools`` package at startup.


class CapabilityMismatch(Exception):
    """Raised when the tool's product is not supported by the controller."""


class DispatchEntryMissing(Exception):
    """Raised when a tool has no entry in the AST-derived dispatch table."""


@dataclass(frozen=True)
class DispatchEntry:
    """How to invoke a single tool against a per-request domain manager."""

    manager_attr: str  # e.g. "client_manager"
    method: str  # e.g. "get_clients"


def _iter_tool_modules(products: Iterable[str]) -> Iterable[tuple[str, str]]:
    """Yield (product, module_name) for every tools/* submodule we can locate.

    Resolves the submodules via ``importlib.util.find_spec`` — we never
    actually import the tool modules (they have heavy import-time side
    effects via FastMCP's server singleton).
    """
    import pkgutil

    for product in products:
        pkg_name = f"unifi_{product}_mcp.tools"
        try:
            spec = importlib.util.find_spec(pkg_name)
        except (ModuleNotFoundError, ImportError):
            continue
        if spec is None:
            continue
        # ``submodule_search_locations`` is the package's __path__-equivalent.
        search_paths = getattr(spec, "submodule_search_locations", None)
        if not search_paths:
            continue
        for info in pkgutil.iter_modules(list(search_paths)):
            if info.ispkg:
                continue
            yield product, f"{pkg_name}.{info.name}"


def _module_runtime_singletons(tree: ast.Module) -> set[str]:
    """Names imported from ``unifi_<product>_mcp.runtime`` (e.g. {client_manager, server})."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith(".runtime"):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _tool_decorator_name(decorator: ast.expr) -> str | None:
    """Return the tool name from a ``@server.tool(name=...)`` decorator, if any."""
    if not isinstance(decorator, ast.Call):
        return None
    func = decorator.func
    # Match @server.tool(...) — attribute "tool" on any name.
    if not (isinstance(func, ast.Attribute) and func.attr == "tool"):
        return None
    for kw in decorator.keywords:
        if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return None


def _first_manager_call(
    func: ast.AsyncFunctionDef | ast.FunctionDef, runtime_names: set[str]
) -> tuple[str, str] | None:
    """Find the first ``await <runtime_name>.<method>(...)`` in the function body.

    Returns (attr_name, method_name) or None.
    """

    class Finder(ast.NodeVisitor):
        result: tuple[str, str] | None = None

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            if self.result is not None:
                return
            f = node.func
            if (
                isinstance(f, ast.Attribute)
                and isinstance(f.value, ast.Name)
                and f.value.id in runtime_names
                # Filter out 'server.tool' which is the decorator, plus general
                # builtins. Manager singletons end with '_manager' by
                # convention; permit any non-server name to keep flexibility.
                and f.value.id != "server"
                and f.value.id != "logger"
            ):
                self.result = (f.value.id, f.attr)
                return
            self.generic_visit(node)

    finder = Finder()
    finder.visit(func)
    return finder.result


def build_dispatch_table(
    products: Iterable[str] = _DEFAULT_PRODUCTS,
) -> dict[str, DispatchEntry]:
    """AST-walk every ``unifi_<product>_mcp.tools.*`` module and build the dispatch table.

    Returns a dict mapping tool_name -> DispatchEntry. Tools with no
    discoverable manager call are silently skipped — they fall through to
    :class:`DispatchEntryMissing` at dispatch time, which the API endpoint
    will translate into a 501.
    """
    table: dict[str, DispatchEntry] = {}
    for _product, module_name in _iter_tool_modules(products):
        # Resolve the module's source file *without* importing it — tool
        # modules touch the FastMCP server singleton at import time and pull
        # in heavy MCP/aiounifi machinery we don't need for AST analysis.
        try:
            spec = importlib.util.find_spec(module_name)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("dispatch: find_spec failed for %s (%s)", module_name, exc)
            continue
        if spec is None or not spec.origin:
            continue
        try:
            with open(spec.origin, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=spec.origin)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("dispatch: cannot parse %s (%s)", module_name, exc)
            continue

        runtime_names = _module_runtime_singletons(tree)
        if not runtime_names:
            continue

        for node in tree.body:
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            tool_name: str | None = None
            for dec in node.decorator_list:
                tool_name = _tool_decorator_name(dec)
                if tool_name:
                    break
            if not tool_name:
                continue
            call = _first_manager_call(node, runtime_names)
            if call is None:
                continue
            table[tool_name] = DispatchEntry(manager_attr=call[0], method=call[1])

    # Apply static overrides AFTER the AST walk. Tools whose body has 2+ awaits
    # by design (preview/execute split, lookup-then-act with state-dependent
    # preview, multi-manager compose) need explicit dispatch targets — see
    # ``dispatch_overrides.DISPATCH_OVERRIDES`` for the list and rationale.
    for tool_name, (manager_attr, method) in DISPATCH_OVERRIDES.items():
        table[tool_name] = DispatchEntry(manager_attr=manager_attr, method=method)

    return table


# Module-level cache. Populated lazily on first dispatch (which keeps test
# isolation simple — tests that don't dispatch don't pay the cost).
_DISPATCH_TABLE: dict[str, DispatchEntry] | None = None


def _get_table() -> dict[str, DispatchEntry]:
    global _DISPATCH_TABLE
    if _DISPATCH_TABLE is None:
        _DISPATCH_TABLE = build_dispatch_table()
    return _DISPATCH_TABLE


def reset_dispatch_table_cache() -> None:
    """Test helper: forget the cached table so it gets rebuilt on next call."""
    global _DISPATCH_TABLE
    _DISPATCH_TABLE = None


async def dispatch_action(
    *,
    registry: ManifestRegistry,
    factory: ManagerFactory,
    session: AsyncSession,
    tool_name: str,
    controller_id: str,
    controller_products: list[str],
    site: str,
    args: dict,
    confirm: bool,
    dispatch_table: dict[str, DispatchEntry] | None = None,
) -> Any:
    """Resolve ``tool_name`` to a manager method and invoke it.

    - ``registry.resolve(tool_name)`` raises :class:`unifi_api.services.manifest.ToolNotFound`
      when the tool is unknown — propagated unchanged.
    - ``CapabilityMismatch`` raised when the tool's product is not in
      ``controller_products``.
    - ``DispatchEntryMissing`` raised when the tool was not in the AST-derived
      dispatch table (i.e. its body did not call a ``<singleton>.<method>(...)``).
    - For network controllers, the connection manager's ``site`` is updated
      via ``set_site`` when the requested site differs from the current one.
    - Returns the manager method's response unchanged.

    The method is invoked as ``await method(**args)`` — args are the tool's
    own parameters as defined in ``tools_manifest.json``. ``confirm`` is
    spread in only when the manager method accepts it (best-effort: tools
    today wrap confirm logic at the *tool* layer, not the manager layer, so
    most managers will not accept ``confirm`` and Task 13 will adapt by
    selecting between ``foo`` (preview) and ``apply_foo`` (apply) at the
    routing layer rather than per-method).
    """
    entry: ToolEntry = registry.resolve(tool_name)
    if entry.product not in controller_products:
        raise CapabilityMismatch(
            f"tool '{tool_name}' requires product '{entry.product}', controller supports {controller_products!r}"
        )

    table = dispatch_table if dispatch_table is not None else _get_table()
    binding = table.get(tool_name)
    if binding is None:
        raise DispatchEntryMissing(
            f"no dispatch entry for tool '{tool_name}' (no manager.method() call discovered in tool body)"
        )

    manager = await factory.get_domain_manager(
        session=session,
        controller_id=controller_id,
        product=entry.product,
        attr_name=binding.manager_attr,
    )

    # Network connection managers carry per-site state. Update it before
    # dispatch when caller provided a non-default site that differs from the
    # current value. Other products ignore site.
    if entry.product == "network":
        cm = await factory.get_connection_manager(session, controller_id, "network")
        current_site = getattr(cm, "site", None)
        if site and current_site != site:
            set_site = getattr(cm, "set_site", None)
            if callable(set_site):
                result = set_site(site)
                # set_site is async on the real ConnectionManager.
                if hasattr(result, "__await__"):
                    await result

    method = getattr(manager, binding.method, None)
    if method is None or not callable(method):
        raise DispatchEntryMissing(
            f"manager '{binding.manager_attr}' has no callable method '{binding.method}' for tool '{tool_name}'"
        )

    translator = DISPATCH_ARG_TRANSLATORS.get(tool_name)
    if translator is not None:
        positional, keyword = translator(args)
        return await method(*positional, **keyword)
    return await method(**args)
