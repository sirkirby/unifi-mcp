"""Tests for the relay-only support-bundle exclusion contract."""

from types import SimpleNamespace

from unifi_mcp_relay.policy import (
    RELAY_EXCLUDED_ERROR,
    RELAY_EXCLUDED_TOOL_SUFFIXES,
    RELAY_NESTED_META_ERROR,
    filter_relay_tools,
    filter_tool_index_result,
    is_relay_excluded_tool,
    relay_call_rejection,
)


def test_exclusion_contract_is_narrow_and_prefix_independent():
    assert RELAY_EXCLUDED_TOOL_SUFFIXES == ("_get_support_bundle",)
    assert is_relay_excluded_tool("unifi_get_support_bundle")
    assert is_relay_excluded_tool("protect_get_support_bundle")
    assert is_relay_excluded_tool("access_get_support_bundle")
    assert not is_relay_excluded_tool("unifi_tool_index")
    assert not is_relay_excluded_tool("unifi_get_system_info")


def test_catalog_and_tool_index_filters_remove_only_support_tools():
    catalog = [
        SimpleNamespace(name="unifi_tool_index"),
        SimpleNamespace(name="unifi_get_support_bundle"),
        SimpleNamespace(name="unifi_list_devices"),
    ]
    assert [tool.name for tool in filter_relay_tools(catalog)] == ["unifi_tool_index", "unifi_list_devices"]

    result = filter_tool_index_result(
        {
            "tools": [
                {"name": "protect_tool_index"},
                {"name": "protect_get_support_bundle"},
                {"name": "protect_list_cameras"},
            ],
            "count": 3,
            "categories": ["devices"],
        }
    )
    assert result == {
        "tools": [{"name": "protect_tool_index"}, {"name": "protect_list_cameras"}],
        "count": 2,
        "categories": ["devices"],
    }


def test_direct_execute_and_every_batch_item_are_rejected():
    assert relay_call_rejection("access_get_support_bundle", {}) == RELAY_EXCLUDED_ERROR
    assert (
        relay_call_rejection(
            "unifi_execute",
            {"tool": "unifi_get_support_bundle", "arguments": {"probe": "summary"}},
        )
        == RELAY_EXCLUDED_ERROR
    )
    assert (
        relay_call_rejection(
            "protect_batch",
            {
                "operations": [
                    {"tool": "protect_list_cameras", "arguments": {}},
                    {"tool": "protect_get_support_bundle", "arguments": {}},
                ]
            },
        )
        == RELAY_EXCLUDED_ERROR
    )
    assert relay_call_rejection("unifi_tool_index", {"include_schemas": True}) is None
    assert relay_call_rejection("unifi_batch", {"operations": [{"tool": "unifi_list_devices"}]}) is None


def test_nested_meta_tool_composition_is_rejected_while_direct_meta_calls_remain_available():
    nested_calls = [
        (
            "unifi_execute",
            {
                "tool": "unifi_execute",
                "arguments": {"tool": "unifi_get_support_bundle", "arguments": {"probe": "summary"}},
            },
        ),
        (
            "unifi_execute",
            {
                "tool": "unifi_batch",
                "arguments": {"operations": [{"tool": "unifi_get_support_bundle", "arguments": {}}]},
            },
        ),
        (
            "unifi_batch",
            {
                "operations": [
                    {
                        "tool": "unifi_execute",
                        "arguments": {"tool": "unifi_get_support_bundle", "arguments": {}},
                    }
                ]
            },
        ),
        ("unifi_execute", {"tool": "unifi_tool_index", "arguments": {"include_schemas": True}}),
        ("unifi_batch", {"operations": [{"tool": "unifi_batch_status", "arguments": {"jobId": "job"}}]}),
    ]

    for tool_name, arguments in nested_calls:
        assert relay_call_rejection(tool_name, arguments) == RELAY_NESTED_META_ERROR

    assert relay_call_rejection("unifi_tool_index", {}) is None
    assert relay_call_rejection("unifi_batch_status", {"jobId": "job"}) is None
