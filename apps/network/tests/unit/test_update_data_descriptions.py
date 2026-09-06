"""Update tools that take an ``update_data`` dict must describe it as one.

unifi_update_wlan and unifi_update_network list dozens of fields in their
descriptions while their schemas accept three arguments: the id, update_data
and confirm. An agent that reads the field list as parameters calls
``unifi_update_wlan(wlan_id=..., proxy_arp=false)`` and is rejected with
"unknown arguments" after the operator already approved the write. The
description has to say the fields are keys inside update_data, and every
field it names has to be one the validator accepts.
"""

import json
import re
from pathlib import Path

import pytest

MANIFEST = Path("apps/network/src/unifi_network_mcp/tools_manifest.json")

# tool -> (id argument, validator module, prose words that precede a "(" in the text)
CASES = {
    "unifi_update_wlan": ("wlan_id", "wlans", set()),
    "unifi_update_network": ("network_id", "networks", {"network", "delegated"}),
}


@pytest.fixture(scope="module")
def entries() -> dict[str, dict]:
    tools = json.loads(MANIFEST.read_text())["tools"]
    return {t["name"]: t for t in tools if t["name"] in CASES}


@pytest.mark.parametrize("tool", sorted(CASES))
def test_schema_has_only_the_three_real_arguments(entries, tool):
    id_arg = CASES[tool][0]
    assert set(entries[tool]["schema"]["input"]["properties"]) == {id_arg, "update_data", "confirm"}


@pytest.mark.parametrize("tool", sorted(CASES))
def test_description_says_fields_live_inside_update_data(entries, tool):
    description = entries[tool]["description"]
    assert "inside the update_data dict" in description
    assert "update_data={" in description
    # The mandated sentence for update tools stays.
    assert "Pass only the fields you want to change" in description


@pytest.mark.parametrize("tool", sorted(CASES))
def test_every_documented_field_is_one_the_validator_accepts(entries, tool):
    import importlib

    _, module_name, prose = CASES[tool]
    module = importlib.import_module(f"unifi_core.network.models.{module_name}")
    accepted = module.MUTABLE_FIELDS | set(getattr(module, "_CONTROLLER_ALIASES", {})) | prose
    documented = set(re.findall(r"\b([a-z][a-z0-9_]*) \(", entries[tool]["description"]))
    assert documented, "no documented fields found; has the description format changed?"
    assert documented <= accepted, sorted(documented - accepted)


@pytest.mark.parametrize("tool", sorted(CASES))
def test_update_data_field_description_points_at_the_list(entries, tool):
    text = entries[tool]["schema"]["input"]["properties"]["update_data"]["description"]
    assert "keys listed in the tool description" in text
