"""Tests for the network references tool.

The aggregation itself is covered with the Core manager; these tests cover the
tool's response shape, argument handling and failure paths.
"""

import logging
import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


SAMPLE_REFERENCES = {
    "network_id": "net-1",
    "name": "Corporate",
    "references": {
        "wlans": [{"id": "wlan-1", "name": "Office"}],
        "port_profiles": [{"id": "pp-1", "name": "All", "role": "native"}],
        "device_port_overrides": [{"device_id": "dev-1", "port_idx": 3, "role": "native"}],
        "firewall_policies": [{"id": "fp-1", "name": "Block", "direction": "source"}],
        "clients": [{"hostname": "laptop"}],
    },
    "counts": {
        "wlans": 1,
        "port_profiles": 1,
        "device_port_overrides": 1,
        "firewall_policies": 1,
        "clients": 1,
    },
    "unavailable": [],
}


@pytest.mark.asyncio
async def test_returns_every_family_with_counts():
    from unifi_network_mcp.tools.network import get_network_references

    with patch("unifi_network_mcp.tools.network.network_reference_manager") as mock_mgr:
        mock_mgr.get_network_references = AsyncMock(return_value=SAMPLE_REFERENCES)

        result = await get_network_references(network_id="net-1")

    assert result["success"] is True
    assert result["network_id"] == "net-1"
    assert result["name"] == "Corporate"
    assert result["references"]["firewall_policies"][0]["direction"] == "source"
    assert result["counts"]["device_port_overrides"] == 1
    assert result["unavailable"] == []
    mock_mgr.get_network_references.assert_awaited_once_with("net-1", include_clients=True)


@pytest.mark.asyncio
async def test_include_clients_is_forwarded():
    from unifi_network_mcp.tools.network import get_network_references

    with patch("unifi_network_mcp.tools.network.network_reference_manager") as mock_mgr:
        mock_mgr.get_network_references = AsyncMock(return_value={**SAMPLE_REFERENCES, "clients": None})

        await get_network_references(network_id="net-1", include_clients=False)

    mock_mgr.get_network_references.assert_awaited_once_with("net-1", include_clients=False)


@pytest.mark.asyncio
async def test_missing_network_id_is_rejected():
    from unifi_network_mcp.tools.network import get_network_references

    result = await get_network_references(network_id="")

    assert result == {"success": False, "error": "network_id is required"}


@pytest.mark.asyncio
async def test_unknown_network_reports_the_not_found_text():
    from unifi_core.exceptions import UniFiNotFoundError
    from unifi_network_mcp.tools.network import get_network_references

    with patch("unifi_network_mcp.tools.network.network_reference_manager") as mock_mgr:
        mock_mgr.get_network_references = AsyncMock(side_effect=UniFiNotFoundError("network", "net-x"))

        result = await get_network_references(network_id="net-x")

    assert result["success"] is False
    assert "net-x" in result["error"]


@pytest.mark.asyncio
async def test_unexpected_failure_returns_only_the_exception_class():
    from unifi_network_mcp.tools.network import get_network_references

    with patch("unifi_network_mcp.tools.network.network_reference_manager") as mock_mgr:
        mock_mgr.get_network_references = AsyncMock(side_effect=RuntimeError("secret detail"))

        result = await get_network_references(network_id="net-1")

    assert result["success"] is False
    assert "Failed to get network references" in result["error"]
    assert "RuntimeError" in result["error"]
    assert "secret detail" not in result["error"]


@pytest.mark.asyncio
async def test_failure_logging_omits_tracebacks_and_private_text(caplog):
    from unifi_network_mcp.tools.network import get_network_references

    with patch("unifi_network_mcp.tools.network.network_reference_manager") as mock_mgr:
        mock_mgr.get_network_references = AsyncMock(side_effect=RuntimeError("secret detail"))
        with caplog.at_level(logging.ERROR):
            await get_network_references(network_id="net-1")

    assert all(record.exc_info is None for record in caplog.records)
    assert "secret detail" not in caplog.text
    assert "RuntimeError" in caplog.text
