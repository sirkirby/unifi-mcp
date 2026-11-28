"""Unit tests for the unifi_create_ips_suppression and unifi_delete_ips_suppression MCP tools."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.models.ips_suppression import IpsSuppressionConflict
from unifi_core.write_verification import WriteVerificationResult, failed_write

ENTRY = {
    "signature_id": 2000001,
    "gid": 1,
    "signature": None,
    "category": None,
    "suppression_type": "track",
    "scope": "both",
    "direction": "both",
    "mode": "ip",
    "target": "192.0.2.50",
}


@pytest.fixture
def manager(monkeypatch):
    from unifi_network_mcp.tools import system

    mock = MagicMock()
    mock._connection.site = "branch"
    mock.preview_ips_suppression_change = AsyncMock(return_value={"current": [], "after": [ENTRY]})
    verified = WriteVerificationResult(
        success=True,
        mutation_applied=True,
        operation="create_ips_suppression",
        resource={"suppressions": [ENTRY]},
        persisted_fields=("suppressions",),
    )
    mock.create_ips_suppression = AsyncMock(return_value=verified)
    mock.delete_ips_suppression = AsyncMock(return_value=verified)
    monkeypatch.setattr(system, "system_manager", mock)
    return mock


@pytest.mark.asyncio
async def test_create_previews_the_live_before_and_after_without_writing(manager):
    from unifi_network_mcp.tools.system import create_ips_suppression

    result = await create_ips_suppression(signature_id=2000001, scope="both", target="192.0.2.50")

    assert result["requires_confirmation"] is True
    assert result["resource_id"] == "1:2000001"
    assert result["preview"]["current"] == {"suppressions": []}
    assert result["preview"]["proposed"] == {"suppressions": [ENTRY]}
    assert any("no IPS event" in warning for warning in result["warnings"])
    manager.create_ips_suppression.assert_not_awaited()
    [request] = manager.preview_ips_suppression_change.await_args.args
    assert (request.signature_id, request.scope, request.target) == (2000001, "both", "192.0.2.50")


@pytest.mark.asyncio
async def test_create_applies_with_confirm_and_reports_the_verified_result(manager):
    from unifi_network_mcp.tools.system import create_ips_suppression

    result = await create_ips_suppression(
        signature_id=2000001, scope="source", target="192.0.2.0/28", category="emerging-scan", confirm=True
    )

    assert result["success"] is True and result["site"] == "branch"
    assert result["details"] == {"suppressions": [ENTRY]}
    assert result["message"] == "IPS suppression created and verified."
    [request] = manager.create_ips_suppression.await_args.args
    assert request.tracking_entry() == {"mode": "subnet", "value": "192.0.2.0/28", "direction": "src"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"scope": "both"}, "target is required unless scope is global"),
        ({"scope": "global", "target": "192.0.2.50"}, "a global suppression takes no target"),
        ({"scope": "both", "target": "192.0.2.1/24"}, "no host bits set"),
    ],
)
async def test_create_refuses_bad_input_without_calling_the_controller(manager, arguments, message):
    from unifi_network_mcp.tools.system import create_ips_suppression

    result = await create_ips_suppression(signature_id=2000001, confirm=True, **arguments)

    assert result["success"] is False and message in result["error"]
    assert "192.0.2.1/24" not in result["error"]
    manager.preview_ips_suppression_change.assert_not_awaited()
    manager.create_ips_suppression.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_reports_a_conflict(manager):
    from unifi_network_mcp.tools.system import create_ips_suppression

    manager.create_ips_suppression.side_effect = IpsSuppressionConflict("already suppressed for all traffic")
    result = await create_ips_suppression(signature_id=2000002, scope="both", target="192.0.2.50", confirm=True)

    assert result == {
        "success": False,
        "error": "Failed to create IPS suppression: already suppressed for all traffic",
    }


@pytest.mark.asyncio
async def test_a_rejected_create_passes_the_failed_write_through(manager):
    from unifi_network_mcp.tools.system import create_ips_suppression

    manager.create_ips_suppression.return_value = failed_write(
        "Controller rejected the IPS suppression change (api.err.UnsupportedIpsCategories)",
        operation="create_ips_suppression",
    )
    result = await create_ips_suppression(
        signature_id=2000001, scope="both", target="192.0.2.50", category="nope", confirm=True
    )

    assert (result["success"], result["mutation_applied"]) == (False, False)
    assert "UnsupportedIpsCategories" in result["error"]


@pytest.mark.asyncio
async def test_create_hides_unexpected_errors(manager):
    from unifi_network_mcp.tools.system import create_ips_suppression

    manager.create_ips_suppression.side_effect = RuntimeError("private controller text")
    result = await create_ips_suppression(signature_id=2000001, scope="both", target="192.0.2.50", confirm=True)

    assert result["success"] is False and "private controller text" not in result["error"]


@pytest.mark.asyncio
async def test_delete_previews_then_applies(manager):
    from unifi_network_mcp.tools.system import delete_ips_suppression

    preview = await delete_ips_suppression(signature_id=2000001, target="192.0.2.50", scope="both")
    assert preview["requires_confirmation"] is True
    manager.delete_ips_suppression.assert_not_awaited()

    result = await delete_ips_suppression(signature_id=2000001, confirm=True)
    assert result["success"] is True and result["message"] == "IPS suppression removed and verified."
    [request] = manager.delete_ips_suppression.await_args.args
    assert (request.signature_id, request.target, request.scope) == (2000001, None, None)


@pytest.mark.asyncio
async def test_delete_of_what_is_not_suppressed_is_reported(manager):
    from unifi_network_mcp.tools.system import delete_ips_suppression

    manager.delete_ips_suppression.side_effect = UniFiNotFoundError("IPS suppression", "1:2999999")
    result = await delete_ips_suppression(signature_id=2999999, confirm=True)

    assert result == {"success": False, "error": "Failed to delete IPS suppression: no such suppression or target"}


@pytest.mark.asyncio
async def test_delete_refuses_a_scope_without_a_target(manager):
    from unifi_network_mcp.tools.system import delete_ips_suppression

    result = await delete_ips_suppression(signature_id=2000001, scope="source", confirm=True)

    assert result["success"] is False and "scope applies only with a target" in result["error"]
    manager.delete_ips_suppression.assert_not_awaited()
