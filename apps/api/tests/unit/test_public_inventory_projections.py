"""Typed API inventory preserves public ID provenance and unknown values."""

import pytest
from unifi_api.graphql.types.network.client import Client
from unifi_api.graphql.types.network.device import Device
from unifi_api.graphql.types.network.network import Network
from unifi_api.graphql.types.network.wlan import Wlan
from unifi_core.network.models.integration import PublicInventoryItem

PUBLIC_ID = "00000000-0000-0000-0000-000000000001"


def test_controller_creation_accepts_key_only_configuration():
    from unifi_api.routes.controllers import ControllerIn

    payload = ControllerIn(
        name="Synthetic", base_url="https://controller.test", api_token="synthetic", product_kinds=["network"]
    )
    assert payload.username == payload.password == ""


@pytest.mark.parametrize(
    "domain,model", [("clients", Client), ("devices", Device), ("networks", Network), ("wlans", Wlan)]
)
def test_typed_public_inventory_preserves_ids_and_unknown_fields(domain, model):
    raw = PublicInventoryItem(id=PUBLIC_ID, type="VPN").inventory_record(domain)
    result = model.from_manager_output(raw).to_dict()
    assert result["source_api"] == "integration"
    assert result["integration_id"] == PUBLIC_ID
    if domain in {"networks", "wlans"}:
        assert result["id"] is None
        assert result["enabled"] is None
    elif domain == "clients":
        assert result["is_wired"] is None
        assert result["is_guest"] is None
        assert result["last_seen"] is None
    else:
        assert result["uptime"] is None
        assert result["ports"] is None
