"""unifi_get_dpi_stats reads DPI restriction configuration, and says so.

The tool refreshes aiounifi's ``dpi_apps``/``dpi_groups`` handlers
(``rest/dpiapp``, ``rest/dpigroup``): restriction rules and the groups that
bundle them. DPI traffic comes from unifi_get_site_dpi_traffic and
unifi_get_client_dpi_traffic, and the catalog IDs from the integration-API
list tools. A caller choosing a tool by its description must be sent there.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from unifi_core.network.models.stats import DpiStats

MANIFEST = pathlib.Path(__file__).resolve().parents[2] / "src" / "unifi_network_mcp" / "tools_manifest.json"


@pytest.fixture(scope="module")
def descriptions() -> dict[str, str]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {tool["name"]: tool.get("description", "") for tool in data["tools"]}


def test_description_says_restriction_rules_not_statistics(descriptions: dict[str, str]) -> None:
    description = descriptions["unifi_get_dpi_stats"]

    assert "restriction" in description.lower()
    assert "not traffic" in description
    assert not description.startswith("Get Deep Packet Inspection (DPI) statistics")


@pytest.mark.parametrize(
    "tool",
    [
        "unifi_get_site_dpi_traffic",
        "unifi_get_client_dpi_traffic",
        "unifi_list_dpi_applications",
        "unifi_list_dpi_categories",
    ],
)
def test_description_points_at_the_tools_that_hold_statistics_and_ids(descriptions: dict[str, str], tool) -> None:
    assert tool in descriptions["unifi_get_dpi_stats"]
    assert tool in descriptions, f"{tool} is named but not registered"


def test_output_fields_describe_restriction_rules_and_groups() -> None:
    fields = DpiStats.model_fields

    assert "rest/dpiapp" in fields["applications"].description
    assert "rest/dpigroup" in fields["categories"].description
