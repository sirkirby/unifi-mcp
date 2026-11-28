"""IPS suppression create and delete actions: validation, dispatch and outcome preservation."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_api.serializers.network.threat_management import ThreatManagementMutationAckSerializer
from unifi_api.services.actions import MutationPreview, dispatch_action
from unifi_api.services.dispatch_overrides import DISPATCH_ARG_TRANSLATORS
from unifi_api.services.manifest import ManifestRegistry, ToolEntry
from unifi_core.network.models.ips_suppression import IpsSuppressionCreate, IpsSuppressionDelete
from unifi_core.write_verification import failed_write, noop_write

CREATE = "unifi_create_ips_suppression"
DELETE = "unifi_delete_ips_suppression"


def test_the_translators_build_the_core_requests():
    _, kwargs = DISPATCH_ARG_TRANSLATORS[CREATE](
        {"signature_id": 2000001, "scope": "destination", "target": "192.0.2.0/28", "category": "emerging-scan"}
    )
    assert kwargs == {
        "request": IpsSuppressionCreate(
            signature_id=2000001, scope="destination", target="192.0.2.0/28", category="emerging-scan"
        )
    }
    _, kwargs = DISPATCH_ARG_TRANSLATORS[DELETE]({"signature_id": 2000001, "gid": 3})
    assert kwargs == {"request": IpsSuppressionDelete(signature_id=2000001, gid=3)}


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        (CREATE, {"signature_id": 2000001, "scope": "both"}),
        (CREATE, {"signature_id": 2000001, "scope": "both", "target": "private-canary"}),
        (CREATE, {"signature_id": 2000001, "scope": "global", "target": "192.0.2.1"}),
        (DELETE, {"signature_id": 2000001, "scope": "source"}),
        (DELETE, {"signature_id": 2000001, "target": "private-canary"}),
    ],
)
def test_bad_arguments_are_refused_without_echoing_them(tool, args):
    with pytest.raises(ValueError) as error:
        DISPATCH_ARG_TRANSLATORS[tool](args)
    assert "private-canary" not in str(error.value)


@pytest.mark.parametrize("tool", [CREATE, DELETE])
def test_an_uncertain_outcome_survives_the_ack(tool):
    ack = ThreatManagementMutationAckSerializer().serialize_action(
        failed_write("Readback failed", mutation_applied=None, metadata={"outcome_uncertain": True}), tool_name=tool
    )
    assert not ack["success"] and ack["mutation_applied"] is None and ack["outcome_uncertain"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "method", "action", "args", "request_model"),
    [
        (
            CREATE,
            "create_ips_suppression",
            "create",
            {"signature_id": 2000001, "scope": "both", "target": "192.0.2.50"},
            IpsSuppressionCreate(signature_id=2000001, scope="both", target="192.0.2.50"),
        ),
        (
            DELETE,
            "delete_ips_suppression",
            "delete",
            {"signature_id": 2000001, "target": "192.0.2.50"},
            IpsSuppressionDelete(signature_id=2000001, target="192.0.2.50"),
        ),
    ],
)
async def test_preview_has_no_manager_access_and_confirm_delegates(tool, method, action, args, request_model):
    entry = ToolEntry(
        name=tool,
        product="network",
        category="system",
        manager="system_manager",
        method=method,
        permission_action=action,
        read_only_hint=False,
    )
    manager = MagicMock()
    setattr(manager, method, AsyncMock(return_value=noop_write()))
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    common = dict(
        registry=ManifestRegistry({tool: entry}),
        factory=factory,
        session=MagicMock(),
        tool_name=tool,
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args=args,
    )
    assert isinstance(await dispatch_action(**common, confirm=False), MutationPreview)
    factory.get_domain_manager.assert_not_awaited()
    result = await dispatch_action(**common, confirm=True)
    assert result.success and result.mutation_applied is False
    getattr(manager, method).assert_awaited_once_with(request=request_model)
