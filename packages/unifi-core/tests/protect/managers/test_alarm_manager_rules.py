"""Tests for AlarmManager rule CRUD methods.

Covers the ``/proxy/protect/api/automations`` endpoints wrapped by
``AlarmManager.list_rules`` / ``get_rule`` / ``update_rule`` /
``create_rule`` / ``delete_rule``. Manager methods stay close to the
raw payload (returning ``Dict[str, Any]`` or ``List[Dict]``); the tool
layer is responsible for coercing into the pydantic ``AlarmRule`` shapes
via ``rule_from_controller`` / ``rule_list_from_controller``.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.managers.alarm_manager import AlarmManager


def _make_manager() -> AlarmManager:
    return AlarmManager(MagicMock())


def _raw_rule(
    rule_id: str = "rule-001",
    name: str = "Test Rule",
    enable: bool = True,
) -> Dict[str, Any]:
    """Minimal raw automation payload matching the Protect schema."""
    return {
        "id": rule_id,
        "name": name,
        "enable": enable,
        "isCreatedBySystem": False,
        "sources": [{"device": "AABBCCDDEEFF", "type": "include"}],
        "conditions": [{"condition": {"source": "smartDetectLine", "type": "is", "value": "Arrival"}}],
        "historyConditions": [],
        "schedules": [],
        "actions": [
            {
                "type": "HTTP_REQUEST",
                "order": -1,
                "metadata": {
                    "url": "https://example.test/webhook",
                    "method": "POST",
                    "headers": [],
                    "timeout": 30000,
                    "useThumbnail": True,
                },
            }
        ],
        "cooldown": {"enable": False, "timeout": 600000},
    }


# -- list_rules -------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_rules_returns_raw_dicts_from_get_automations() -> None:
    mgr = _make_manager()
    raw: List[Dict[str, Any]] = [_raw_rule("r-1"), _raw_rule("r-2", "Other")]
    mgr._cm.client.api_request = AsyncMock(return_value=raw)

    rules = await mgr.list_rules()

    mgr._cm.client.api_request.assert_awaited_once_with("automations", method="get")
    assert isinstance(rules, list)
    assert len(rules) == 2
    assert rules[0]["id"] == "r-1"
    assert rules[1]["name"] == "Other"


@pytest.mark.asyncio
async def test_list_rules_non_list_response_returns_empty_list() -> None:
    """A non-list response (controller error / unexpected shape) coalesces to []."""
    mgr = _make_manager()
    mgr._cm.client.api_request = AsyncMock(return_value={"error": "oops"})

    rules = await mgr.list_rules()

    assert rules == []


@pytest.mark.asyncio
async def test_list_rules_skips_non_dict_entries() -> None:
    mgr = _make_manager()
    mgr._cm.client.api_request = AsyncMock(return_value=[_raw_rule("r-1"), "garbage", 42, None])

    rules = await mgr.list_rules()

    assert len(rules) == 1
    assert rules[0]["id"] == "r-1"


# -- get_rule ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_rule_filters_from_list() -> None:
    """The controller has no per-rule GET endpoint (``GET automations/{id}``
    404s); get_rule fetches the full list (``GET automations``) and filters
    by id."""
    mgr = _make_manager()
    raw = [_raw_rule("r-1", "First"), _raw_rule("rule-uuid-abc", "Test Vehicle Arrival")]
    mgr._cm.client.api_request = AsyncMock(return_value=raw)

    rule = await mgr.get_rule("rule-uuid-abc")

    mgr._cm.client.api_request.assert_awaited_once_with("automations", method="get")
    assert rule["id"] == "rule-uuid-abc"
    assert rule["name"] == "Test Vehicle Arrival"


@pytest.mark.asyncio
async def test_get_rule_strips_padded_id() -> None:
    """A padded id (`" rule-uuid-abc "`) is stripped before list filtering so it
    matches the controller's id instead of silently missing."""
    mgr = _make_manager()
    raw = [_raw_rule("r-1", "First"), _raw_rule("rule-uuid-abc", "Test Vehicle Arrival")]
    mgr._cm.client.api_request = AsyncMock(return_value=raw)

    rule = await mgr.get_rule("  rule-uuid-abc  ")

    assert rule["id"] == "rule-uuid-abc"


@pytest.mark.asyncio
async def test_get_rule_empty_id_rejected() -> None:
    mgr = _make_manager()
    mgr._cm.client.api_request = AsyncMock()

    with pytest.raises(ValueError, match="rule_id"):
        await mgr.get_rule("")

    mgr._cm.client.api_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_rule_not_found_raises() -> None:
    """An id absent from the list raises UniFiNotFoundError."""
    mgr = _make_manager()
    mgr._cm.client.api_request = AsyncMock(return_value=[_raw_rule("r-1"), _raw_rule("r-2")])

    with pytest.raises(UniFiNotFoundError):
        await mgr.get_rule("does-not-exist")


@pytest.mark.asyncio
async def test_get_rule_non_list_response_treated_as_not_found() -> None:
    """A non-list response coalesces to an empty list (via list_rules), so the
    id is simply not found."""
    mgr = _make_manager()
    mgr._cm.client.api_request = AsyncMock(return_value={"error": "oops"})

    with pytest.raises(UniFiNotFoundError):
        await mgr.get_rule("rule-001")


# -- update_rule ------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_rule_patches_with_full_body() -> None:
    """PATCH expects the full rule body per JeffSteinbok's implementation."""
    mgr = _make_manager()
    body = _raw_rule("rule-001", enable=False)
    mgr._cm.client.api_request = AsyncMock(return_value=body)

    updated = await mgr.update_rule("rule-001", body)

    mgr._cm.client.api_request.assert_awaited_once_with("automations/rule-001", method="patch", json=body)
    assert updated["enable"] is False


@pytest.mark.asyncio
async def test_update_rule_empty_id_rejected() -> None:
    mgr = _make_manager()
    mgr._cm.client.api_request = AsyncMock()

    with pytest.raises(ValueError, match="rule_id"):
        await mgr.update_rule("", _raw_rule())

    mgr._cm.client.api_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_rule_non_dict_body_rejected() -> None:
    mgr = _make_manager()
    mgr._cm.client.api_request = AsyncMock()

    with pytest.raises(TypeError, match="dict"):
        await mgr.update_rule("rule-001", "not-a-dict")  # type: ignore[arg-type]

    mgr._cm.client.api_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_rule_whitespace_only_id_rejected() -> None:
    """``_require_rule_id`` strips whitespace before checking for empty —
    confirm that '   ' is still rejected.
    """
    mgr = _make_manager()
    mgr._cm.client.api_request = AsyncMock()

    with pytest.raises(ValueError, match="rule_id"):
        await mgr.update_rule("   ", _raw_rule())

    mgr._cm.client.api_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_rule_non_dict_patch_response_coerces_to_empty_dict() -> None:
    """PATCH normally echoes the rule body, but if the controller returns
    something else (None / list / str) coerce to {} rather than crashing
    callers that expect a dict.
    """
    mgr = _make_manager()
    mgr._cm.client.api_request = AsyncMock(return_value=None)

    result = await mgr.update_rule("rule-001", _raw_rule())

    assert result == {}


# -- create_rule ------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_rule_posts_body_and_returns_created_dict() -> None:
    mgr = _make_manager()
    new_body = _raw_rule("ignored-by-server", "New Rule")
    # POST returns the server-assigned id
    server_response = {**new_body, "id": "server-assigned-uuid"}
    mgr._cm.client.api_request = AsyncMock(return_value=server_response)

    created = await mgr.create_rule(new_body)

    mgr._cm.client.api_request.assert_awaited_once_with("automations", method="post", json=new_body)
    assert created["id"] == "server-assigned-uuid"
    assert created["name"] == "New Rule"


@pytest.mark.asyncio
async def test_create_rule_non_dict_body_rejected() -> None:
    mgr = _make_manager()
    mgr._cm.client.api_request = AsyncMock()

    with pytest.raises(TypeError, match="dict"):
        await mgr.create_rule(["not", "a", "dict"])  # type: ignore[arg-type]


# -- delete_rule ------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_rule_calls_delete_endpoint() -> None:
    """The controller returns an empty body on a successful delete, so
    delete_rule uses api_request_raw (no JSON decode) to avoid a spurious
    'Could not decode JSON' error."""
    mgr = _make_manager()
    mgr._cm.client.api_request_raw = AsyncMock(return_value=None)

    result = await mgr.delete_rule("rule-001")

    mgr._cm.client.api_request_raw.assert_awaited_once_with("automations/rule-001", method="delete")
    assert result == {"deleted": True, "rule_id": "rule-001"}


@pytest.mark.asyncio
async def test_delete_rule_empty_id_rejected() -> None:
    mgr = _make_manager()
    mgr._cm.client.api_request_raw = AsyncMock()

    with pytest.raises(ValueError, match="rule_id"):
        await mgr.delete_rule("")

    mgr._cm.client.api_request_raw.assert_not_awaited()


# -- preview helpers --------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_update_rule_shows_diff() -> None:
    """Preview should fetch current rule and report what would change."""
    mgr = _make_manager()
    current = _raw_rule("rule-001", "Old Name", enable=True)
    # get_rule now fetches the list and filters, so mock the list response.
    mgr._cm.client.api_request = AsyncMock(return_value=[current])

    new_body = {**current, "name": "New Name", "enable": False}
    preview = await mgr.preview_update_rule("rule-001", new_body)

    assert preview["rule_id"] == "rule-001"
    assert preview["current"]["name"] == "Old Name"
    assert preview["current"]["enable"] is True
    assert preview["proposed"]["name"] == "New Name"
    assert preview["proposed"]["enable"] is False


@pytest.mark.asyncio
async def test_preview_delete_rule_shows_target() -> None:
    mgr = _make_manager()
    current = _raw_rule("rule-001", "To Be Deleted")
    # get_rule now fetches the list and filters, so mock the list response.
    mgr._cm.client.api_request = AsyncMock(return_value=[current])

    preview = await mgr.preview_delete_rule("rule-001")

    assert preview["rule_id"] == "rule-001"
    assert preview["current_name"] == "To Be Deleted"
    assert preview["proposed_changes"] == {"deleted": True}
