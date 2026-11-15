"""Teleport API projection and action payload parity."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_api.graphql.types.network.teleport import TeleportSettings
from unifi_api.serializers.network.vpn import VpnMutationAckSerializer
from unifi_api.services.actions import MutationPreview, dispatch_action
from unifi_api.services.dispatch_overrides import DISPATCH_ARG_TRANSLATORS, DISPATCH_OVERRIDES
from unifi_api.services.manifest import ManifestRegistry, ToolEntry
from unifi_core.network.models.teleport import teleport_from_controller
from unifi_core.write_verification import failed_write, noop_write

RECORD = {
    "_id": "teleport-id",
    "key": "teleport",
    "site_id": "site-id",
    "enabled": True,
    "subnet_cidr": "192.168.2.1/24",
    "unrelated_secret": "synthetic-secret",
}


def test_typed_projection_and_ack_redact_unknown_record_fields():
    projected = TeleportSettings.from_manager_output(teleport_from_controller(RECORD)).to_dict()
    assert projected == {
        "enabled": True,
        "subnet_cidr": "192.168.2.1/24",
        "id": "teleport-id",
        "site_id": "site-id",
    }
    assert "synthetic-secret" not in repr(projected)
    ack = VpnMutationAckSerializer().serialize_action(
        noop_write(operation="update_teleport_settings", resource=projected),
        tool_name="unifi_update_teleport_settings",
    )
    assert ack["success"] and not ack["mutation_applied"]


def test_uncertain_action_ack_does_not_claim_no_mutation():
    result = failed_write(
        "Teleport write outcome uncertain; inspect settings before another update",
        operation="update_teleport_settings",
        mutation_applied=None,
        metadata={"outcome_uncertain": True},
    )
    ack = VpnMutationAckSerializer().serialize_action(result, tool_name="unifi_update_teleport_settings")
    assert ack["success"] is False
    assert ack["mutation_applied"] is None
    assert ack["outcome_uncertain"] is True


def test_action_override_and_translator():
    assert DISPATCH_OVERRIDES["unifi_update_teleport_settings"] == ("vpn_manager", "update_teleport_settings")
    translator = DISPATCH_ARG_TRANSLATORS["unifi_update_teleport_settings"]
    positional, keyword = translator({"subnet_cidr": " 10.201.0.1/24 "})
    assert positional == ()
    assert keyword == {"update_data": {"subnet_cidr": "10.201.0.1/24"}}
    for value in ("10.201.0.77", "8.8.8.1/24", "10.201.0.0/24", "10.201.0.1/30", "not-a-range"):
        with pytest.raises(ValueError) as exc:
            translator({"subnet_cidr": value})
        assert value not in str(exc.value)


@pytest.mark.asyncio
async def test_action_preview_and_confirm_share_core_validation():
    entry = ToolEntry(
        name="unifi_update_teleport_settings",
        product="network",
        category="vpn",
        manager="vpn_manager",
        method="update_teleport_settings",
        permission_action="update",
        read_only_hint=False,
    )
    registry = ManifestRegistry({entry.name: entry})
    manager = MagicMock()
    manager.update_teleport_settings = AsyncMock(
        return_value=noop_write(operation="update_teleport_settings", resource={"subnet_cidr": "10.201.0.1/24"})
    )
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    common = dict(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name=entry.name,
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"subnet_cidr": "10.201.0.1/24"},
    )
    preview = await dispatch_action(**common, confirm=False)
    assert isinstance(preview, MutationPreview)
    factory.get_domain_manager.assert_not_awaited()
    result = await dispatch_action(**common, confirm=True)
    assert result.success
    manager.update_teleport_settings.assert_awaited_once_with(update_data={"subnet_cidr": "10.201.0.1/24"})
    for confirm in (False, True):
        with pytest.raises(ValueError, match="private") as exc:
            await dispatch_action(**{**common, "args": {"subnet_cidr": "8.8.8.1/24"}}, confirm=confirm)
        assert "8.8.8.1" not in str(exc.value)
    assert manager.update_teleport_settings.await_count == 1
