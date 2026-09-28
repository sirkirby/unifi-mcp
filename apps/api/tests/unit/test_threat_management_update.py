"""Threat management action validation, permission and outcome preservation."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_api.serializers.network.threat_management import ThreatManagementMutationAckSerializer
from unifi_api.services.actions import MutationPreview, dispatch_action
from unifi_api.services.dispatch_overrides import DISPATCH_ARG_TRANSLATORS
from unifi_api.services.manifest import ManifestRegistry, ToolEntry
from unifi_core.write_verification import failed_write, noop_write

TOOL = "unifi_update_threat_management_settings"


def test_action_validation_and_uncertain_ack():
    translator = DISPATCH_ARG_TRANSLATORS[TOOL]
    assert translator({"update_data": {"device_fingerprinting_enabled": False}}) == (
        (),
        {"update_data": {"device_fingerprinting_enabled": False}},
    )
    for update in [
        {"unknown": "private-canary"},
        {"ips_mode": None},
        {"ips_mode": "ids", "traffic_identification_enabled": False},
    ]:
        with pytest.raises(ValueError) as error:
            translator({"update_data": update})
        assert "private-canary" not in str(error.value)
    ack = ThreatManagementMutationAckSerializer().serialize_action(
        failed_write("Readback failed", mutation_applied=None, metadata={"outcome_uncertain": True}), tool_name=TOOL
    )
    assert not ack["success"] and ack["mutation_applied"] is None and ack["outcome_uncertain"]


@pytest.mark.asyncio
async def test_preview_has_no_manager_access_and_confirm_delegates():
    entry = ToolEntry(
        name=TOOL,
        product="network",
        category="system",
        manager="system_manager",
        method="update_threat_management_settings",
        permission_action="update",
        read_only_hint=False,
    )
    manager = MagicMock()
    manager.update_threat_management_settings = AsyncMock(return_value=noop_write())
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    common = dict(
        registry=ManifestRegistry({TOOL: entry}),
        factory=factory,
        session=MagicMock(),
        tool_name=TOOL,
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"update_data": {"ips_mode": "ids"}},
    )
    result = await dispatch_action(**common, confirm=False)
    assert isinstance(result, MutationPreview)
    factory.get_domain_manager.assert_not_awaited()
    result = await dispatch_action(**common, confirm=True)
    assert result.success and result.mutation_applied is False
    manager.update_threat_management_settings.assert_awaited_once_with(update_data={"ips_mode": "ids"})
