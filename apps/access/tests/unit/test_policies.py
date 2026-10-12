"""Tests for PolicyManager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.access.managers.policy_manager import PolicyManager
from unifi_core.exceptions import UniFiConnectionError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cm_proxy():
    cm = AccessConnectionManager(host="192.0.2.1", username="admin", password="secret")
    cm._proxy_available = True
    cm._proxy_session = MagicMock()
    return cm


@pytest.fixture
def cm_none():
    return AccessConnectionManager(host="192.0.2.1", username="", password="")


@pytest.fixture
def policy_mgr(cm_proxy):
    return PolicyManager(cm_proxy)


@pytest.fixture
def policy_mgr_none(cm_none):
    return PolicyManager(cm_none)


# ---------------------------------------------------------------------------
# list_policies
# ---------------------------------------------------------------------------


class TestListPolicies:
    @pytest.mark.asyncio
    async def test_list_policies_success(self, policy_mgr, cm_proxy):
        expected = [{"id": "pol-1", "name": "Default"}]
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": expected}
            result = await policy_mgr.list_policies()
        assert result == expected
        mock_req.assert_awaited_once_with("GET", "access_policies?expand[]=schedule")

    @pytest.mark.asyncio
    async def test_list_policies_no_proxy(self, policy_mgr_none):
        with pytest.raises(UniFiConnectionError, match="No proxy session"):
            await policy_mgr_none.list_policies()


# ---------------------------------------------------------------------------
# get_policy
# ---------------------------------------------------------------------------


class TestGetPolicy:
    @pytest.mark.asyncio
    async def test_get_policy_success(self, policy_mgr, cm_proxy):
        expected = {"id": "pol-1", "name": "Default", "doors": ["d1"]}
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": expected}
            result = await policy_mgr.get_policy("pol-1")
        assert result == expected
        mock_req.assert_awaited_once_with("GET", "access_policy/pol-1")

    @pytest.mark.asyncio
    async def test_get_policy_empty_id(self, policy_mgr):
        with pytest.raises(ValueError, match="policy_id is required"):
            await policy_mgr.get_policy("")

    @pytest.mark.asyncio
    async def test_get_policy_no_proxy(self, policy_mgr_none):
        with pytest.raises(UniFiConnectionError, match="No proxy session"):
            await policy_mgr_none.get_policy("pol-1")


# ---------------------------------------------------------------------------
# list_schedules
# ---------------------------------------------------------------------------


class TestListSchedules:
    @pytest.mark.asyncio
    async def test_list_schedules_success(self, policy_mgr, cm_proxy):
        expected = [{"id": "sched-1", "name": "Business Hours"}]
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": expected}
            result = await policy_mgr.list_schedules()
        assert result == expected
        mock_req.assert_awaited_once_with("GET", "schedules?expand[]=week_schedule")

    @pytest.mark.asyncio
    async def test_list_schedules_no_proxy(self, policy_mgr_none):
        with pytest.raises(UniFiConnectionError, match="No proxy session"):
            await policy_mgr_none.list_schedules()


# ---------------------------------------------------------------------------
# update_policy (preview)
# ---------------------------------------------------------------------------


class TestUpdatePolicy:
    @pytest.mark.asyncio
    async def test_update_policy_preview(self, policy_mgr, cm_proxy):
        current = {"id": "pol-1", "name": "Default", "doors": ["d1"]}
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": current}
            preview = await policy_mgr.update_policy("pol-1", {"name": "Updated"})
        assert preview["policy_id"] == "pol-1"
        assert preview["proposed_changes"] == {"name": "Updated"}

    @pytest.mark.asyncio
    async def test_update_policy_empty_id(self, policy_mgr):
        with pytest.raises(ValueError, match="policy_id is required"):
            await policy_mgr.update_policy("", {"name": "test"})

    @pytest.mark.asyncio
    async def test_update_policy_empty_changes(self, policy_mgr):
        with pytest.raises(ValueError, match="changes dict must not be empty"):
            await policy_mgr.update_policy("pol-1", {})


# ---------------------------------------------------------------------------
# apply_update_policy
# ---------------------------------------------------------------------------


class TestApplyUpdatePolicy:
    @pytest.mark.asyncio
    async def test_apply_update_success(self, policy_mgr, cm_proxy):
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {}
            result = await policy_mgr.apply_update_policy("pol-1", {"name": "Updated"})
        assert result["result"] == "success"
        assert "name" in result["updated_fields"]
        mock_req.assert_awaited_once_with("PUT", "access_policy/pol-1", json={"name": "Updated"})

    @pytest.mark.asyncio
    async def test_apply_update_no_proxy(self, policy_mgr_none):
        with pytest.raises(UniFiConnectionError, match="No proxy session"):
            await policy_mgr_none.apply_update_policy("pol-1", {"name": "test"})
