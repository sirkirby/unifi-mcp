"""Every tool with a ``confirm`` parameter returns a standard preview.

Preview-token mode mints a token only for a successful preview that sets
``requires_confirmation``, so a tool whose preview omits it can never execute
in that mode. The ``unifi_core.confirmation`` helpers set it; a hand-built
preview dict has to set it itself.

The check reads each tool module's source: the preview path is the body of
``if not confirm:``, or what follows an ``if confirm:`` that has no ``else``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL_MODULES = sorted(ROOT.glob("apps/*/src/*/tools/*.py"))
PREVIEW_HELPERS = frozenset(
    (
        "preview_response",
        "create_preview",
        "update_preview",
        "delete_preview",
        "toggle_preview",
        # InnerSpace's response helper, which sets requires_confirmation on a core preview.
        "write_preview",
    )
)

# Tools whose every path returns a failure, so they have no preview to tokenise.
NO_PREVIEW_TOOLS = {
    # uiprotect cannot create or delete liveviews; both tools validate and return success=False.
    "protect_create_liveview",
    "protect_delete_liveview",
    # uiprotect cannot delete individual recordings; the tool always returns success=False.
    "protect_delete_recording",
}


def _tool_name(fn: ast.AsyncFunctionDef | ast.FunctionDef) -> str | None:
    for decorator in fn.decorator_list:
        if isinstance(decorator, ast.Call):
            for keyword in decorator.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    return keyword.value.value
    return None


def _confirm_tools() -> dict[str, tuple[Path, ast.AsyncFunctionDef | ast.FunctionDef]]:
    tools = {}
    for path in TOOL_MODULES:
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            if "confirm" not in {a.arg for a in node.args.args + node.args.kwonlyargs}:
                continue
            name = _tool_name(node)
            if name is not None:
                tools[name] = (path, node)
    return tools


def _is_confirm(test: ast.expr) -> bool:
    return isinstance(test, ast.Name) and test.id == "confirm"


def _is_not_confirm(test: ast.expr) -> bool:
    return isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and _is_confirm(test.operand)


def _preview_paths(fn: ast.AST) -> list[list[ast.stmt]]:
    paths = []
    for node in ast.walk(fn):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if not isinstance(block, list):
                continue
            for index, stmt in enumerate(block):
                if not isinstance(stmt, ast.If):
                    continue
                if _is_not_confirm(stmt.test):
                    paths.append(stmt.body)
                elif _is_confirm(stmt.test):
                    paths.append(stmt.orelse or block[index + 1 :])
    return paths


def _is_standard_preview(path: list[ast.stmt]) -> bool:
    for stmt in path:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                func = node.func
                called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                if called in PREVIEW_HELPERS:
                    return True
            if isinstance(node, ast.Constant) and node.value == "requires_confirmation":
                return True
    return False


TOOLS = _confirm_tools()


def test_scan_finds_confirm_tools_on_every_server():
    servers = {path.relative_to(ROOT).parts[1] for path, _ in TOOLS.values()}
    assert servers == {"network", "protect", "access", "innerspace", "drive"}
    assert NO_PREVIEW_TOOLS <= TOOLS.keys()


@pytest.mark.parametrize("tool_name", sorted(TOOLS.keys() - NO_PREVIEW_TOOLS))
def test_preview_path_sets_requires_confirmation(tool_name):
    path, fn = TOOLS[tool_name]
    previews = _preview_paths(fn)

    assert previews, f"{tool_name} ({path.relative_to(ROOT)}:{fn.lineno}) has no recognisable preview branch"
    missing = [p[0].lineno for p in previews if p and not _is_standard_preview(p)]
    assert missing == [], (
        f"{tool_name} ({path.relative_to(ROOT)}) builds a preview without requires_confirmation at lines {missing}; "
        "use a unifi_core.confirmation helper"
    )


@pytest.mark.parametrize("tool_name", sorted(NO_PREVIEW_TOOLS))
def test_no_preview_tools_have_no_preview_branch(tool_name):
    _, fn = TOOLS[tool_name]

    assert _preview_paths(fn) == []
