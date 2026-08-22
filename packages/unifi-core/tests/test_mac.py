"""Tests for MAC address normalization.

The UniFi controller reports MAC addresses in lowercase. Callers - humans
typing into an agent, values copy-pasted out of a vendor label or another
tool's output - routinely supply uppercase. Comparing the two forms with a
raw `==` silently reports "not found" for a device that plainly exists.
"""

from unifi_core.mac import mac_equal, normalize_mac


def test_uppercase_is_lowercased() -> None:
    assert normalize_mac("AA:BB:CC:DD:EE:FF") == "aa:bb:cc:dd:ee:ff"


def test_mixed_case_is_lowercased() -> None:
    assert normalize_mac("Aa:bB:Cc:dD:Ee:fF") == "aa:bb:cc:dd:ee:ff"


def test_lowercase_is_unchanged() -> None:
    assert normalize_mac("aa:bb:cc:dd:ee:ff") == "aa:bb:cc:dd:ee:ff"


def test_surrounding_whitespace_is_stripped() -> None:
    assert normalize_mac("  AA:BB:CC:DD:EE:FF\n") == "aa:bb:cc:dd:ee:ff"


def test_separators_are_left_alone() -> None:
    """Deliberately NOT reformatted. Case is the defect being fixed; silently
    rewriting separators would change which strings match on a guess about
    what the caller meant."""
    assert normalize_mac("AA-BB-CC-DD-EE-FF") == "aa-bb-cc-dd-ee-ff"


def test_empty_and_blank_become_none() -> None:
    assert normalize_mac("") is None
    assert normalize_mac("   ") is None


def test_non_string_becomes_none() -> None:
    assert normalize_mac(None) is None
    assert normalize_mac(1234) is None


def test_mac_equal_matches_across_case() -> None:
    assert mac_equal("AA:BB:CC:DD:EE:FF", "aa:bb:cc:dd:ee:ff")
    assert mac_equal("aa:bb:cc:dd:ee:ff", "AA:BB:CC:DD:EE:FF")


def test_mac_equal_rejects_different_addresses() -> None:
    assert not mac_equal("AA:BB:CC:DD:EE:FF", "aa:bb:cc:dd:ee:00")


def test_mac_equal_is_false_when_either_side_is_missing() -> None:
    """A record with no `mac` field must never match, and an empty query must
    never match a record with no `mac` field. Both normalize to None, and
    None == None would otherwise be a spurious hit."""
    assert not mac_equal(None, None)
    assert not mac_equal("", None)
    assert not mac_equal("aa:bb:cc:dd:ee:ff", None)
    assert not mac_equal(None, "aa:bb:cc:dd:ee:ff")


# --- Access device manager --------------------------------------------------


# The Access device manager's own behavioural coverage lives in
# tests/access/managers/test_device_manager_mac.py. It matches on `mac` case
# -insensitively while keeping `unique_id` an exact comparison - not because
# unique_ids are non-hex (several Access id classes are hex; see
# access/models/device_configs.py), but because they are opaque controller
# identifiers rather than addresses, so there is no case-equivalence rule to
# apply to them.


# --- Model-boundary normalization -------------------------------------------


def test_acl_mac_side_lowercases_the_caller_supplied_addresses() -> None:
    """The controller stores these lowercase, so a create-then-list round trip
    is case-asymmetric unless the create side normalizes."""
    from unifi_core.network.models.acl import _create_side

    side = _create_side(["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"], None, None)
    assert side["specific_mac_addresses"] == ["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"]


def test_acl_mac_side_leaves_unusable_entries_alone() -> None:
    """Normalization must not silently drop or rewrite something it cannot
    parse - that would hide a bad input rather than surface it."""
    from unifi_core.network.models.acl import _create_side

    assert _create_side([""], None, None)["specific_mac_addresses"] == [""]


def test_traffic_flow_query_lowercases_the_source_mac_filter() -> None:
    """A server-side filter that does not match returns 200 with zero flows -
    the quiet failure mode."""
    from unifi_core.network.models.traffic_flows import TrafficFlowQuery

    q = TrafficFlowQuery(source_mac=["AA:BB:CC:DD:EE:FF"])
    assert q.source_mac == ["aa:bb:cc:dd:ee:ff"]


# --- looks_like_mac ---------------------------------------------------------


def test_looks_like_mac_accepts_the_forms_a_controller_or_a_label_uses() -> None:
    from unifi_core.mac import looks_like_mac

    assert looks_like_mac("aa:bb:cc:dd:ee:ff")
    assert looks_like_mac("AA:BB:CC:DD:EE:FF")
    assert looks_like_mac("aa-bb-cc-dd-ee-ff")
    assert looks_like_mac("aabbccddeeff")


def test_looks_like_mac_rejects_opaque_identifiers() -> None:
    """The case this exists for: an Access unique_id contains a separator
    (`dev-1`) or is hex of the wrong length, and must not be mistaken for an
    address and sent off for resolution."""
    from unifi_core.mac import looks_like_mac

    assert not looks_like_mac("dev-1")
    assert not looks_like_mac("0123456789abcdef01234567")  # 24-hex Access unique_id
    assert not looks_like_mac("aa:bb:cc:dd:ee")  # too short
    assert not looks_like_mac("aa:bb-cc:dd:ee:ff")  # mixed separators
    assert not looks_like_mac(None)
    assert not looks_like_mac("")


def test_oon_targets_of_type_mac_are_lowercased() -> None:
    """`normalize_oon_create_payload` names itself for this and did not do it.

    The parameter is called `targets`, not `*_mac`, so a sweep for MAC-typed
    parameters cannot find it - but the tool layer documents it as a list of
    target MAC addresses.
    """
    from unifi_core.network.managers.oon_manager import _normalize_oon_targets

    assert _normalize_oon_targets("CLIENTS", ["AA:BB:CC:DD:EE:FF"]) == [{"type": "MAC", "value": "aa:bb:cc:dd:ee:ff"}]
    assert _normalize_oon_targets("CLIENTS", [{"mac": "AA:BB:CC:DD:EE:FF"}]) == [
        {"type": "MAC", "value": "aa:bb:cc:dd:ee:ff"}
    ]


def test_oon_targets_of_other_types_are_left_alone() -> None:
    """A NETWORK_GROUP_ID is not an address and must not be case-folded."""
    from unifi_core.network.managers.oon_manager import _normalize_oon_targets

    assert _normalize_oon_targets("GROUPS", ["GroupID-ABC"]) == [{"type": "NETWORK_GROUP_ID", "value": "GroupID-ABC"}]


def test_client_wifi_details_cache_key_is_case_stable() -> None:
    """A process-lifetime cache keyed on the raw MAC fetches /stat/sta twice
    for the same client."""
    import inspect

    from unifi_core.network.managers.stats_manager import StatsManager

    src = inspect.getsource(StatsManager.get_client_wifi_details)
    normalize_at = src.index("normalize_mac(client_mac)")
    cache_at = src.index("cache_key =")
    assert normalize_at < cache_at, "the cache key is built before the MAC is normalized"


# --- Config payloads carrying MAC lists -------------------------------------
#
# Same round-trip asymmetry that justified normalizing the ACL side: the
# controller stores these lowercase, so an uppercase create does not match a
# later list.


def test_wlan_mac_filter_list_is_lowercased() -> None:
    from unifi_core.network.models.wlans import Wlan

    w = Wlan(mac_filter_list=["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"])
    assert w.mac_filter_list == ["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"]


def test_content_filter_client_macs_are_lowercased() -> None:
    from unifi_core.network.models.content_filter import ContentFilter

    c = ContentFilter(client_macs=["AA:BB:CC:DD:EE:FF"])
    assert c.client_macs == ["aa:bb:cc:dd:ee:ff"]


def test_ap_group_device_macs_are_lowercased() -> None:
    from unifi_core.network.models.ap_group import ApGroup

    g = ApGroup(device_macs=["AA:BB:CC:DD:EE:FF"])
    assert g.device_macs == ["aa:bb:cc:dd:ee:ff"]


def test_config_mac_lists_leave_unusable_entries_alone() -> None:
    """Normalization must not drop or rewrite what it cannot parse."""
    from unifi_core.network.models.ap_group import ApGroup

    assert ApGroup(device_macs=[""]).device_macs == [""]


# --- Update paths bypass the models -----------------------------------------
#
# `to_controller_update` takes the caller's RAW dict and never constructs the
# model, so a field validator does nothing for it. These write paths need the
# normalization applied where the payload is actually built.


def test_ap_group_update_lowercases_device_macs() -> None:
    from unifi_core.network.models.ap_group import to_controller_update

    assert to_controller_update({"device_macs": ["AA:BB:CC:DD:EE:FF"]})["device_macs"] == ["aa:bb:cc:dd:ee:ff"]


def test_content_filter_update_lowercases_client_macs() -> None:
    from unifi_core.network.models.content_filter import to_controller_update

    assert to_controller_update({"client_macs": ["AA:BB:CC:DD:EE:FF"]})["client_macs"] == ["aa:bb:cc:dd:ee:ff"]


def test_client_group_update_lowercases_members() -> None:
    from unifi_core.network.models.client_group import to_controller_update

    assert to_controller_update({"members": ["AA:BB:CC:DD:EE:FF"]})["members"] == ["aa:bb:cc:dd:ee:ff"]


def test_acl_update_lowercases_both_mac_sides() -> None:
    from unifi_core.network.models.acl import to_controller_update

    out = to_controller_update({"source_macs": ["AA:BB:CC:DD:EE:FF"], "destination_macs": ["11:22:33:44:55:AA"]})
    assert out["traffic_source"]["specific_mac_addresses"] == ["aa:bb:cc:dd:ee:ff"]
    assert out["traffic_destination"]["specific_mac_addresses"] == ["11:22:33:44:55:aa"]


def test_firewall_policy_endpoints_lowercase_client_macs() -> None:
    """`source`/`destination` are opaque dicts that carry a client_macs list."""
    from unifi_core.network.models.firewall import normalize_policy_update

    out = normalize_policy_update(
        {"name": "x", "source": {"matching_target": "CLIENT", "client_macs": ["AA:BB:CC:DD:EE:FF"]}}
    )
    assert out["source"]["client_macs"] == ["aa:bb:cc:dd:ee:ff"]


def test_oon_update_normalizes_targets_like_create() -> None:
    """The update path skipped the create normalizer, losing both the case and
    the bare-string -> {type,value} shaping."""
    from unifi_core.network.managers.oon_manager import normalize_oon_update_payload

    out = normalize_oon_update_payload({"target_type": "CLIENTS", "targets": ["AA:BB:CC:DD:EE:FF"]})
    assert out["targets"] == [{"type": "MAC", "value": "aa:bb:cc:dd:ee:ff"}]


def test_oon_update_takes_target_type_from_the_existing_policy() -> None:
    """A partial update need not restate target_type, and the shaping depends
    on it. GROUPS is the case that bites: the MAC default would both mis-type
    the target and case-fold an opaque group id."""
    from unifi_core.network.managers.oon_manager import normalize_oon_update_payload

    out = normalize_oon_update_payload({"targets": ["AbC123XyZ"]}, {"target_type": "GROUPS"})
    assert out["targets"] == [{"type": "NETWORK_GROUP_ID", "value": "AbC123XyZ"}]


def test_oon_update_leaves_targets_alone_when_target_type_is_unknowable() -> None:
    """Guessing is worse than doing nothing: the default is MAC, which would
    lowercase an opaque group id and rename the object it points at."""
    from unifi_core.network.managers.oon_manager import normalize_oon_update_payload

    out = normalize_oon_update_payload({"targets": ["AbC123XyZ"]}, {})
    assert out["targets"] == ["AbC123XyZ"]


def test_oon_update_normalizes_secure_even_without_targets() -> None:
    """The secure block must not be gated behind an unrelated key."""
    from unifi_core.network.managers.oon_manager import normalize_oon_update_payload

    out = normalize_oon_update_payload({"secure": {"apps": ["facebook"]}}, {"target_type": "CLIENTS"})
    assert out["secure"] != {"apps": ["facebook"]}, "secure was passed through unshaped"


def test_oon_update_is_wired_into_update_oon_policy() -> None:
    """Removing the call restores the original bug with a green suite, so the
    wiring itself needs a test."""
    import inspect

    from unifi_core.network.managers.oon_manager import OonManager

    src = inspect.getsource(OonManager.update_oon_policy)
    assert "normalize_oon_update_payload(" in src


def test_normalize_mac_list_never_yields_none() -> None:
    """Dropping the `or v` would put a literal None into a PUT payload."""
    from unifi_core.mac import normalize_mac_list

    assert normalize_mac_list(["", "  ", "AA:BB:CC:DD:EE:FF"]) == ["", "  ", "aa:bb:cc:dd:ee:ff"]


def test_normalize_mac_list_passes_a_non_list_through() -> None:
    """Without the isinstance guard a bare string is shredded per character."""
    from unifi_core.mac import normalize_mac_list

    assert normalize_mac_list("AA:BB:CC:DD:EE:FF") == "AA:BB:CC:DD:EE:FF"
    assert normalize_mac_list(None) is None


# --- Create paths, normalized at the manager boundary ------------------------
#
# The MCP tool layer and the apps/api dispatch each assemble these payloads
# themselves, so neither a model validator nor a to_controller_* builder is on
# the path. The manager is the one boundary they share.


def test_client_group_create_normalizes_members_at_the_manager() -> None:
    import inspect

    from unifi_core.network.managers.client_group_manager import ClientGroupManager

    src = inspect.getsource(ClientGroupManager.create_client_group)
    assert "normalize_mac_list" in src
    assert src.index("normalize_mac_list") < src.index("ApiRequestV2")


def test_ap_group_create_and_update_normalize_at_the_manager() -> None:
    import inspect

    from unifi_core.network.managers.network_manager import NetworkManager

    create_src = inspect.getsource(NetworkManager.create_ap_group)
    assert "normalize_mac_list" in create_src
    assert create_src.index("normalize_mac_list") < create_src.index("ApiRequestV2")

    update_src = inspect.getsource(NetworkManager.update_ap_group)
    # Must precede deep_merge AND _unpersisted_fields, or an uppercase
    # restatement reads as a stuck field and reports a false failure.
    assert update_src.index("normalize_mac_list") < update_src.index("deep_merge")


def test_firewall_create_normalizes_endpoint_macs_at_the_manager() -> None:
    import inspect

    from unifi_core.network.managers.firewall_manager import FirewallManager

    src = inspect.getsource(FirewallManager.create_firewall_policy)
    assert "_normalize_endpoint_macs" in src
    assert src.index("_normalize_endpoint_macs") < src.index("ApiRequestV2")
