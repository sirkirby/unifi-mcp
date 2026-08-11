"""Tests for port profile tool functions.

Tests tool-layer behavior: which keys reach the controller payload, and the
preview/confirm flow. Manager-level tests live in test_switch_manager.py.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


async def _create_preview(**kwargs):
    """Run create_port_profile in preview mode and return the create payload."""
    from unifi_network_mcp.tools.switch import create_port_profile

    result = await create_port_profile(confirm=False, **kwargs)
    assert result["success"] is True, result
    return result["preview"]["will_create"]


class TestCreatePortProfileDefaults:
    """Defaults the caller accepts must actually be sent.

    These fields were only added to the payload when they *differed* from the
    tool's own documented default, so taking the default sent no key at all and
    the controller applied its own. For poe_mode that means a profile created
    with the documented default 'auto' came back with Auto PoE unchecked —
    de-energising anything wired through a port using it.
    """

    @pytest.mark.asyncio
    async def test_poe_mode_default_is_sent(self) -> None:
        payload = await _create_preview(name="P", forward="native")
        assert payload["poe_mode"] == "auto"

    @pytest.mark.asyncio
    async def test_stp_port_mode_default_is_sent(self) -> None:
        payload = await _create_preview(name="P", forward="native")
        assert payload["stp_port_mode"] is True

    @pytest.mark.asyncio
    async def test_isolation_default_is_sent(self) -> None:
        payload = await _create_preview(name="P", forward="native")
        assert payload["isolation"] is False

    @pytest.mark.asyncio
    async def test_non_default_values_still_sent(self) -> None:
        payload = await _create_preview(name="P", forward="all", poe_mode="off", stp_port_mode=False, isolation=True)
        assert payload["poe_mode"] == "off"
        assert payload["stp_port_mode"] is False
        assert payload["isolation"] is True


class TestCreatePortProfileAccessPort:
    """An access port must be expressible in a single create call."""

    @pytest.mark.asyncio
    async def test_tagged_vlan_mgmt_is_sent(self) -> None:
        payload = await _create_preview(name="Access", forward="native", tagged_vlan_mgmt="block_all")
        assert payload["tagged_vlan_mgmt"] == "block_all"

    @pytest.mark.asyncio
    async def test_tagged_networkconf_ids_reachable_from_create(self) -> None:
        payload = await _create_preview(
            name="Trunk",
            forward="customize",
            tagged_vlan_mgmt="custom",
            tagged_networkconf_ids=["net-1", "net-2"],
        )
        assert payload["tagged_networkconf_ids"] == ["net-1", "net-2"]

    @pytest.mark.asyncio
    async def test_excluded_networkconf_ids_reachable_from_create(self) -> None:
        payload = await _create_preview(
            name="Trunk",
            forward="customize",
            tagged_vlan_mgmt="custom",
            excluded_networkconf_ids=["net-9"],
        )
        assert payload["excluded_networkconf_ids"] == ["net-9"]

    @pytest.mark.asyncio
    async def test_port_mode_edge_fields_reachable_from_create(self) -> None:
        payload = await _create_preview(
            name="Access",
            forward="native",
            tagged_vlan_mgmt="block_all",
            stp_edge_state="enabled",
            stp_bpdu_guard_enabled=True,
            stp_uplink=False,
        )
        assert payload["stp_edge_state"] == "enabled"
        assert payload["stp_bpdu_guard_enabled"] is True
        assert payload["stp_uplink"] is False

    @pytest.mark.asyncio
    async def test_omitted_optional_fields_are_not_sent(self) -> None:
        """Fields the caller never mentions stay absent so the controller keeps its own."""
        payload = await _create_preview(name="P", forward="native")
        for key in (
            "tagged_vlan_mgmt",
            "excluded_networkconf_ids",
            "tagged_networkconf_ids",
            "stp_edge_state",
            "stp_bpdu_guard_enabled",
            "stp_uplink",
        ):
            assert key not in payload, f"{key!r} should not be sent when not requested"


class TestPortProfileWriteVerification:
    """A write the controller rewrote must not be reported as a plain success.

    The controller silently normalizes some values — asking for an access port
    (`forward: 'native'`) without `tagged_vlan_mgmt` produced a trunk
    (`forward: 'all'`) and still returned "created/updated successfully". The
    tools now compare what was requested against what the controller stored.
    """

    @pytest.mark.asyncio
    async def test_update_surfaces_manager_verification_failure(self) -> None:
        """The manager verifies the write; the tool surfaces its verdict."""
        with patch("unifi_network_mcp.tools.switch.switch_manager") as mock_mgr:
            mock_mgr.update_port_profile = AsyncMock(return_value=(False, "stored different value(s): forward ..."))

            from unifi_network_mcp.tools.switch import update_port_profile

            result = await update_port_profile(
                profile_id="pp1",
                profile_data={"forward": "native"},
                confirm=True,
            )

        assert result["success"] is False, result
        assert "forward" in result["error"]

    @pytest.mark.asyncio
    async def test_update_success_when_manager_verifies(self) -> None:
        with patch("unifi_network_mcp.tools.switch.switch_manager") as mock_mgr:
            mock_mgr.update_port_profile = AsyncMock(return_value=(True, None))

            from unifi_network_mcp.tools.switch import update_port_profile

            result = await update_port_profile(
                profile_id="pp1",
                profile_data={"forward": "native", "tagged_vlan_mgmt": "block_all"},
                confirm=True,
            )

        assert result["success"] is True, result

    @pytest.mark.asyncio
    async def test_create_reports_coerced_field(self) -> None:
        created = {
            "_id": "pp2",
            "name": "Access",
            "forward": "all",
            "poe_mode": "auto",
            "isolation": False,
            "stp_port_mode": True,
        }
        with patch("unifi_network_mcp.tools.switch.switch_manager") as mock_mgr:
            mock_mgr.create_port_profile = AsyncMock(return_value=created)

            from unifi_network_mcp.tools.switch import create_port_profile

            result = await create_port_profile(
                name="Access",
                forward="native",
                stp_port_mode=True,
                confirm=True,
            )

        assert result["success"] is False, result
        assert set(result["coerced_fields"]) == {"forward"}, result["coerced_fields"]
        assert result["coerced_fields"]["forward"]["requested"] == "native"
        assert result["coerced_fields"]["forward"]["stored"] == "all"

    @pytest.mark.asyncio
    async def test_create_success_path_reports_no_coercion(self) -> None:
        """The happy path: everything requested came back as requested."""
        created = {
            "_id": "pp3",
            "name": "Access",
            "forward": "native",
            "tagged_vlan_mgmt": "block_all",
            "poe_mode": "auto",
            "isolation": False,
            "stp_port_mode": True,
        }
        with patch("unifi_network_mcp.tools.switch.switch_manager") as mock_mgr:
            mock_mgr.create_port_profile = AsyncMock(return_value=created)

            from unifi_network_mcp.tools.switch import create_port_profile

            result = await create_port_profile(
                name="Access",
                forward="native",
                tagged_vlan_mgmt="block_all",
                confirm=True,
            )

        assert result["success"] is True, result
        assert "coerced_fields" not in result

    @pytest.mark.asyncio
    async def test_create_does_not_flag_keys_the_controller_omits(self) -> None:
        """An access profile carries no tagged_networkconf_ids key at all.

        Treating an absent key as a rewritten value reported a correct create as
        a failure — and create is not idempotent, so a caller retrying on that
        false negative would make a duplicate profile.
        """
        created = {
            "_id": "pp4",
            "name": "Access",
            "forward": "native",
            "tagged_vlan_mgmt": "block_all",
            "poe_mode": "auto",
            "isolation": False,
            "stp_port_mode": True,
        }
        with patch("unifi_network_mcp.tools.switch.switch_manager") as mock_mgr:
            mock_mgr.create_port_profile = AsyncMock(return_value=created)

            from unifi_network_mcp.tools.switch import create_port_profile

            result = await create_port_profile(
                name="Access",
                forward="native",
                tagged_vlan_mgmt="block_all",
                tagged_networkconf_ids=[],
                confirm=True,
            )

        assert result["success"] is True, result


class TestUpdatePortProfilePreview:
    @pytest.mark.asyncio
    async def test_preview_warns_about_ignored_fields(self) -> None:
        """The preview is where the caller decides whether to commit, so the
        fields that will be dropped must be visible there too."""
        from unifi_network_mcp.tools.switch import update_port_profile

        result = await update_port_profile(
            profile_id="pp1",
            profile_data={"forward": "native", "stormctrl_bcast_enabled": True},
            confirm=False,
        )

        warnings = result.get("warnings") or []
        assert any("stormctrl_bcast_enabled" in w for w in warnings), result

    @pytest.mark.asyncio
    async def test_fully_unsupported_payload_names_the_fields(self) -> None:
        from unifi_network_mcp.tools.switch import update_port_profile

        result = await update_port_profile(
            profile_id="pp1",
            profile_data={"stormctrl_bcast_enabled": True},
            confirm=True,
        )

        assert result["success"] is False
        assert "stormctrl_bcast_enabled" in result["error"]
        assert "not supported" in result["error"]
