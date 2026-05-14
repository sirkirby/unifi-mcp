"""Client + usergroup cluster serializer unit tests (Phase 4A PR1 Cluster 2)."""

from unifi_api.serializers._registry import (
    discover_serializers,
    serializer_registry_singleton,
)


def _registry():
    discover_serializers(manifest_tool_names=set())
    return serializer_registry_singleton()


# ---- client_groups.py ----


def test_client_group_list_serializer_shape() -> None:
    """Phase 6 PR2 Task 24 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.client_group import ClientGroup

    sample = {
        "_id": "cg1",
        "name": "Engineering",
        "qos_rate_max_down": 100000,
        "qos_rate_max_up": 50000,
    }
    out = ClientGroup.from_manager_output(sample).to_dict()
    assert out["id"] == "cg1"
    assert out["name"] == "Engineering"
    assert out["qos_rate_max_down"] == 100000
    assert ClientGroup.render_hint("list")["kind"] == "list"


def test_client_group_detail_serializer_shape() -> None:
    """Phase 6 PR2 Task 24 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.client_group import ClientGroup

    sample = {"_id": "cg2", "name": "Guests", "qos_rate_max_down": -1, "qos_rate_max_up": -1}
    out = ClientGroup.from_manager_output(sample).to_dict()
    assert out["id"] == "cg2"
    assert out["name"] == "Guests"
    assert ClientGroup.render_hint("detail")["kind"] == "detail"


def test_usergroup_list_serializer_shape() -> None:
    """Phase 6 PR2 Task 24 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.client_group import UserGroup

    sample = {"_id": "ug2", "name": "Limited", "qos_rate_max_down": 5000, "qos_rate_max_up": 1000}
    out = UserGroup.from_manager_output(sample).to_dict()
    assert out["id"] == "ug2"
    assert out["qos_rate_max_down"] == 5000
    assert UserGroup.render_hint("list")["kind"] == "list"


def test_usergroup_detail_serializer_shape() -> None:
    """Phase 6 PR2 Task 24 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.client_group import UserGroup

    sample = {"_id": "ug3", "name": "VIP", "qos_rate_max_down": 1000000, "qos_rate_max_up": 500000}
    out = UserGroup.from_manager_output(sample).to_dict()
    assert out["id"] == "ug3"
    assert out["name"] == "VIP"
    assert UserGroup.render_hint("detail")["kind"] == "detail"


def test_client_group_mutation_ack_bool() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("unifi_update_client_group")
    out = s.serialize_action(True, tool_name="unifi_update_client_group")
    assert out["success"] is True
    assert out["data"] == {"success": True}
    assert out["render_hint"]["kind"] == "detail"


def test_client_group_mutation_ack_dict_passthrough() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("unifi_create_client_group")
    out = s.serialize_action({"_id": "cg9", "name": "NewGroup"}, tool_name="unifi_create_client_group")
    assert out["success"] is True
    assert out["data"]["_id"] == "cg9"
    assert out["render_hint"]["kind"] == "detail"


def test_client_group_mutation_ack_dispatches_for_all_mutations() -> None:
    reg = _registry()
    for tool in (
        "unifi_create_client_group",
        "unifi_update_client_group",
        "unifi_delete_client_group",
        "unifi_create_usergroup",
        "unifi_update_usergroup",
    ):
        s = reg.serializer_for_tool(tool)
        out = s.serialize_action(True, tool_name=tool)
        assert out["render_hint"]["kind"] == "detail"


# ---- clients.py extensions ----


def test_blocked_client_list_serializer_shape() -> None:
    """Phase 6 PR2 Task 19 — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.network.client import BlockedClient

    sample = {
        "mac": "aa:bb:cc:dd:ee:ff",
        "hostname": "BadGuy",
        "name": None,
        "last_seen": 1700000000,
        "blocked": True,
    }
    item = BlockedClient.from_manager_output(sample).to_dict()
    assert item["mac"] == "aa:bb:cc:dd:ee:ff"
    assert item["hostname"] == "BadGuy"
    assert item["blocked"] is True
    assert item["last_seen"] is not None
    assert BlockedClient.render_hint("list")["kind"] == "list"


def test_client_lookup_serializer_shape() -> None:
    """Phase 6 PR2 Task 19 — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.network.client import ClientLookup

    sample = {
        "mac": "11:22:33:44:55:66",
        "last_ip": "192.168.1.50",
        "hostname": "laptop",
        "is_online": True,
        "last_seen": 1700000000,
    }
    out = ClientLookup.from_manager_output(sample).to_dict()
    assert out["mac"] == "11:22:33:44:55:66"
    assert out["ip"] == "192.168.1.50"
    assert out["hostname"] == "laptop"
    assert out["is_online"] is True
    assert ClientLookup.render_hint("detail")["kind"] == "detail"


def test_client_mutation_ack_bool() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("unifi_block_client")
    out = s.serialize_action(True, tool_name="unifi_block_client")
    assert out["success"] is True
    assert out["data"] == {"success": True}
    assert out["render_hint"]["kind"] == "detail"


def test_client_mutation_ack_dispatches_for_all_mutations() -> None:
    reg = _registry()
    for tool in (
        "unifi_block_client",
        "unifi_unblock_client",
        "unifi_forget_client",
        "unifi_rename_client",
        "unifi_force_reconnect_client",
        "unifi_set_client_ip_settings",
        "unifi_authorize_guest",
        "unifi_unauthorize_guest",
    ):
        s = reg.serializer_for_tool(tool)
        out = s.serialize_action(True, tool_name=tool)
        assert out["render_hint"]["kind"] == "detail"
