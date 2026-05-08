"""Network filtering cluster serializer unit tests (Phase 4A PR1 Cluster 4).

Covers firewall groups + zones + mutation acks, QoS rules, DPI applications/
categories, content filters, ACL rules, and OON policies.
"""

from unifi_api.serializers._registry import (
    discover_serializers,
    serializer_registry_singleton,
)


def _registry():
    discover_serializers(manifest_tool_names=set())
    return serializer_registry_singleton()


# ---- Firewall groups ----


def test_firewall_group_list_serializer_shape() -> None:
    """Phase 6 PR2 Task 22 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.firewall import FirewallGroup

    sample = {
        "_id": "fg1",
        "name": "Trusted IPs",
        "group_type": "address-group",
        "group_members": ["10.0.0.1", "10.0.0.2"],
    }
    out = FirewallGroup.from_manager_output(sample).to_dict()
    assert out["id"] == "fg1"
    assert out["name"] == "Trusted IPs"
    assert out["group_type"] == "address-group"
    assert out["members"] == ["10.0.0.1", "10.0.0.2"]
    assert FirewallGroup.render_hint("list")["kind"] == "list"


def test_firewall_group_detail_serializer_shape() -> None:
    from unifi_api.graphql.types.network.firewall import FirewallGroup

    sample = {
        "_id": "fg2",
        "name": "Web ports",
        "group_type": "port-group",
        "group_members": ["80", "443"],
    }
    out = FirewallGroup.from_manager_output(sample).to_dict()
    assert out["id"] == "fg2"
    assert out["group_type"] == "port-group"
    assert out["members"] == ["80", "443"]
    assert FirewallGroup.render_hint("detail")["kind"] == "detail"


# ---- Firewall zones ----


def test_firewall_zone_list_serializer_shape() -> None:
    """Phase 6 PR2 Task 22 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.firewall import FirewallZone

    sample = {
        "_id": "z1",
        "name": "Internal",
        "networks": ["net1", "net2"],
        "default_policy": "ALLOW",
    }
    out = FirewallZone.from_manager_output(sample).to_dict()
    assert out["id"] == "z1"
    assert out["name"] == "Internal"
    assert out["networks"] == ["net1", "net2"]
    assert out["default_policy"] == "ALLOW"
    assert FirewallZone.render_hint("list")["kind"] == "list"


# ---- Firewall mutation acks ----


def test_firewall_mutation_ack_dispatches_for_all_mutations() -> None:
    reg = _registry()
    for tool in (
        "unifi_create_firewall_policy",
        "unifi_update_firewall_policy",
        "unifi_delete_firewall_policy",
        "unifi_toggle_firewall_policy",
        "unifi_create_firewall_group",
        "unifi_update_firewall_group",
        "unifi_delete_firewall_group",
    ):
        s = reg.serializer_for_tool(tool)
        out = s.serialize_action(True, tool_name=tool)
        assert out["render_hint"]["kind"] == "detail"


# ---- QoS rules ----


def test_qos_rule_list_serializer_shape() -> None:
    """Phase 6 PR2 Task 22 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.qos import QosRule

    sample = {
        "_id": "qos1",
        "name": "VoIP",
        "enabled": True,
        "rate_max_down": 50000,
        "rate_max_up": 25000,
        "priority": 7,
    }
    out = QosRule.from_manager_output(sample).to_dict()
    assert out["id"] == "qos1"
    assert out["name"] == "VoIP"
    assert out["enabled"] is True
    assert out["rate_max_down"] == 50000
    assert out["rate_max_up"] == 25000
    assert out["priority"] == 7
    assert QosRule.render_hint("list")["kind"] == "list"


def test_qos_rule_detail_serializer_shape() -> None:
    from unifi_api.graphql.types.network.qos import QosRule

    sample = {
        "_id": "qos2",
        "name": "Backup limiter",
        "enabled": False,
        "rate_max_down": 10000,
        "rate_max_up": 5000,
        "priority": 1,
    }
    out = QosRule.from_manager_output(sample).to_dict()
    assert out["id"] == "qos2"
    assert out["enabled"] is False
    assert out["priority"] == 1
    assert QosRule.render_hint("detail")["kind"] == "detail"


def test_qos_mutation_ack_dispatches_for_all_mutations() -> None:
    reg = _registry()
    for tool in (
        "unifi_create_qos_rule",
        "unifi_create_simple_qos_rule",
        "unifi_update_qos_rule",
        "unifi_toggle_qos_rule_enabled",
    ):
        s = reg.serializer_for_tool(tool)
        out = s.serialize_action(True, tool_name=tool)
        assert out["render_hint"]["kind"] == "detail"


# ---- DPI applications + categories ----


def test_dpi_application_list_serializer_shape() -> None:
    """Phase 6 PR2 Task 22 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.dpi import DpiApplication

    sample = {"id": 65537, "name": "Skype", "categoryId": 1}
    out = DpiApplication.from_manager_output(sample).to_dict()
    assert out["id"] == 65537
    assert out["name"] == "Skype"
    assert out["category_id"] == 1
    assert DpiApplication.render_hint("list")["kind"] == "list"


def test_dpi_category_list_serializer_shape() -> None:
    """Phase 6 PR2 Task 22 — projection moved to a Strawberry type. Verifies
    the id=0 case (category 0 = Instant messengers) is preserved through
    the new type's explicit ``is None`` check."""
    from unifi_api.graphql.types.network.dpi import DpiCategory

    sample = {"id": 0, "name": "Instant messengers"}
    out = DpiCategory.from_manager_output(sample).to_dict()
    assert out["id"] == 0
    assert out["name"] == "Instant messengers"
    assert DpiCategory.render_hint("list")["kind"] == "list"


# ---- Content filters ----


def test_content_filter_list_serializer_shape() -> None:
    """Phase 6 PR2 Task 22 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.content_filter import ContentFilter

    sample = {
        "_id": "cf1",
        "name": "Family-safe",
        "enabled": True,
        "profile": "FAMILY",
        "applies_to": ["net1", "net2"],
    }
    out = ContentFilter.from_manager_output(sample).to_dict()
    assert out["id"] == "cf1"
    assert out["name"] == "Family-safe"
    assert out["enabled"] is True
    assert out["profile"] == "FAMILY"
    assert out["applies_to"] == ["net1", "net2"]
    assert ContentFilter.render_hint("list")["kind"] == "list"


def test_content_filter_detail_serializer_shape() -> None:
    from unifi_api.graphql.types.network.content_filter import ContentFilter

    sample = {
        "_id": "cf2",
        "name": "Workplace",
        "enabled": False,
        "profile": "WORK",
    }
    out = ContentFilter.from_manager_output(sample).to_dict()
    assert out["id"] == "cf2"
    assert out["enabled"] is False
    assert ContentFilter.render_hint("detail")["kind"] == "detail"


def test_content_filter_mutation_ack_dispatches_for_all_mutations() -> None:
    reg = _registry()
    for tool in ("unifi_update_content_filter", "unifi_delete_content_filter"):
        s = reg.serializer_for_tool(tool)
        out = s.serialize_action(True, tool_name=tool)
        assert out["render_hint"]["kind"] == "detail"


# ---- ACL rules ----


def test_acl_rule_list_serializer_shape() -> None:
    """Phase 6 PR2 Task 22 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.acl import AclRule

    sample = {
        "_id": "acl1",
        "name": "Block guest IoT",
        "enabled": True,
        "action": "BLOCK",
        "traffic_source": {"type": "MAC", "value": "aa:bb:cc:dd:ee:ff"},
        "traffic_destination": {"type": "ANY"},
    }
    out = AclRule.from_manager_output(sample).to_dict()
    assert out["id"] == "acl1"
    assert out["name"] == "Block guest IoT"
    assert out["enabled"] is True
    assert out["action"] == "BLOCK"
    assert out["source"] == {"type": "MAC", "value": "aa:bb:cc:dd:ee:ff"}
    assert out["destination"] == {"type": "ANY"}
    assert AclRule.render_hint("list")["kind"] == "list"


def test_acl_rule_detail_serializer_shape() -> None:
    from unifi_api.graphql.types.network.acl import AclRule

    sample = {
        "_id": "acl2",
        "name": "Allow staff",
        "enabled": False,
        "action": "ALLOW",
    }
    out = AclRule.from_manager_output(sample).to_dict()
    assert out["id"] == "acl2"
    assert out["action"] == "ALLOW"
    assert out["enabled"] is False
    assert AclRule.render_hint("detail")["kind"] == "detail"


def test_acl_mutation_ack_dispatches_for_all_mutations() -> None:
    reg = _registry()
    for tool in (
        "unifi_create_acl_rule",
        "unifi_update_acl_rule",
        "unifi_delete_acl_rule",
    ):
        s = reg.serializer_for_tool(tool)
        out = s.serialize_action(True, tool_name=tool)
        assert out["render_hint"]["kind"] == "detail"


# ---- OON policies ----


def test_oon_policy_list_serializer_shape() -> None:
    """Phase 6 PR2 Task 22 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.oon import OonPolicy

    sample = {
        "_id": "oon1",
        "name": "Kids weekday curfew",
        "enabled": True,
        "targets": [{"type": "MAC", "value": "aa:bb:cc:dd:ee:ff"}],
        "restriction_level": "STRICT",
    }
    out = OonPolicy.from_manager_output(sample).to_dict()
    assert out["id"] == "oon1"
    assert out["name"] == "Kids weekday curfew"
    assert out["enabled"] is True
    assert out["applies_to"] == [{"type": "MAC", "value": "aa:bb:cc:dd:ee:ff"}]
    assert out["restriction_level"] == "STRICT"
    assert OonPolicy.render_hint("list")["kind"] == "list"


def test_oon_policy_detail_serializer_shape() -> None:
    from unifi_api.graphql.types.network.oon import OonPolicy

    sample = {
        "_id": "oon2",
        "name": "Guest cap",
        "enabled": False,
    }
    out = OonPolicy.from_manager_output(sample).to_dict()
    assert out["id"] == "oon2"
    assert out["enabled"] is False
    assert OonPolicy.render_hint("detail")["kind"] == "detail"


def test_oon_mutation_ack_dispatches_for_all_mutations() -> None:
    reg = _registry()
    for tool in (
        "unifi_create_oon_policy",
        "unifi_update_oon_policy",
        "unifi_delete_oon_policy",
        "unifi_toggle_oon_policy",
    ):
        s = reg.serializer_for_tool(tool)
        out = s.serialize_action(True, tool_name=tool)
        assert out["render_hint"]["kind"] == "detail"
