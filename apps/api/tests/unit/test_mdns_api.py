"""mDNS API projection and action payload parity."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_api.graphql.types.network.mdns import MdnsSettings
from unifi_api.serializers.network.mdns import MdnsMutationAckSerializer
from unifi_api.services.actions import MutationPreview, dispatch_action
from unifi_api.services.dispatch_overrides import DISPATCH_ARG_TRANSLATORS, DISPATCH_OVERRIDES
from unifi_api.services.manifest import ManifestRegistry, ToolEntry
from unifi_core.network.models.mdns import mdns_from_controller
from unifi_core.write_verification import failed_write, noop_write

RECORD = {
    "_id": "mdns-id",
    "mode": "all",
    "predefined_services": [{"code": "shelly"}],
    "custom_services": [{"name": "Web", "address": "_http._tcp"}],
    "enabled_for": "some",
    "enabled_for_network_ids": ["n1"],
    "unrelated_secret": "synthetic-secret",
}


def test_typed_projection_and_ack_redact_unknown_record_fields():
    projected = MdnsSettings.from_manager_output(mdns_from_controller(RECORD)).to_dict()
    assert projected["mode"] == "all"
    assert projected["predefined_services"] == [{"code": "shelly"}]
    assert projected["enabled_for_network_ids"] == ["n1"]
    assert "synthetic-secret" not in repr(projected)
    ack = MdnsMutationAckSerializer().serialize_action(
        noop_write(operation="update_mdns_settings", resource=projected),
        tool_name="unifi_update_mdns_settings",
    )
    assert ack["success"] and not ack["mutation_applied"]


def test_typed_read_accepts_legacy_custom_and_new_nested_keys():
    record = {
        **RECORD,
        "predefined_services": [{"code": "printers", "enabled": True}],
        "custom_services": [{"name": "_hap._tcp"}],
    }
    projected = MdnsSettings.from_manager_output(mdns_from_controller(record)).to_dict()
    assert projected["predefined_services"] == [{"code": "printers"}]
    assert projected["custom_services"] == [{"name": "_hap._tcp", "address": None}]


def test_uncertain_action_ack_does_not_claim_no_mutation():
    result = failed_write(
        "mDNS write outcome uncertain",
        operation="update_mdns_settings",
        mutation_applied=None,
        metadata={"outcome_uncertain": True},
    )
    ack = MdnsMutationAckSerializer().serialize_action(result, tool_name="unifi_update_mdns_settings")
    assert ack["success"] is False
    assert ack["mutation_applied"] is None
    assert ack["outcome_uncertain"] is True


def test_action_override_and_translator():
    assert DISPATCH_OVERRIDES["unifi_update_mdns_settings"] == ("system_manager", "update_mdns_settings")
    translator = DISPATCH_ARG_TRANSLATORS["unifi_update_mdns_settings"]
    positional, keyword = translator({"update_data": {"mode": "custom", "custom_services": []}})
    assert positional == ()
    assert keyword == {"update_data": {"mode": "custom", "custom_services": []}}
    for update in ({"enabled_for": "all"}, {"mode": "off"}, {"custom_services": "secret-value"}):
        with pytest.raises(ValueError) as exc:
            translator({"update_data": update})
        assert "secret-value" not in str(exc.value)


@pytest.mark.asyncio
async def test_action_preview_and_confirm_share_core_validation():
    entry = ToolEntry(
        name="unifi_update_mdns_settings",
        product="network",
        category="system",
        manager="system_manager",
        method="update_mdns_settings",
        permission_action="update",
        read_only_hint=False,
    )
    registry = ManifestRegistry({entry.name: entry})
    manager = MagicMock()
    manager.update_mdns_settings = AsyncMock(return_value=noop_write(resource={"mode": "custom"}))
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
        args={"update_data": {"mode": "custom"}},
    )
    preview = await dispatch_action(**common, confirm=False)
    assert isinstance(preview, MutationPreview)
    factory.get_domain_manager.assert_not_awaited()
    result = await dispatch_action(**common, confirm=True)
    assert result.success
    manager.update_mdns_settings.assert_awaited_once_with(update_data={"mode": "custom"})
    for confirm in (False, True):
        with pytest.raises(ValueError, match="enabled_for"):
            await dispatch_action(**{**common, "args": {"update_data": {"enabled_for": "all"}}}, confirm=confirm)
    assert manager.update_mdns_settings.await_count == 1
