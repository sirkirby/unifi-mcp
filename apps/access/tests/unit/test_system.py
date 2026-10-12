"""Tests for SystemManager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.access.managers.system_manager import SystemManager
from unifi_core.exceptions import UniFiConnectionError


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
def sys_mgr_proxy(cm_proxy):
    return SystemManager(cm_proxy)


@pytest.fixture
def sys_mgr_none(cm_none):
    return SystemManager(cm_none)


class TestListUsers:
    @pytest.mark.asyncio
    async def test_list_users_proxy(self, sys_mgr_proxy, cm_proxy):
        """list_users returns user list via users proxy."""
        expected = [{"unique_id": "u1", "full_name": "Test User", "status": "ACTIVE"}]
        with patch.object(cm_proxy, "proxy_request_users", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": expected}
            users = await sys_mgr_proxy.list_users()
        assert len(users) == 1
        assert users[0]["full_name"] == "Test User"

    @pytest.mark.asyncio
    async def test_list_users_no_proxy(self, sys_mgr_none):
        with pytest.raises(UniFiConnectionError, match="No auth path"):
            await sys_mgr_none.list_users()

    @pytest.mark.asyncio
    async def test_list_users_compact(self, sys_mgr_proxy, cm_proxy):
        """compact=True strips scopes, permissions, groups, roles, resources."""
        raw_users = [
            {
                "unique_id": "u1",
                "full_name": "Chris Kirby",
                "first_name": "Chris",
                "last_name": "Kirby",
                "email": "chris@example.com",
                "user_email": "chris@example.com",
                "status": "ACTIVE",
                "nfc_display_id": "100003",
                "nfc_card_type": "ua_card",
                "create_time": 1662941769,
                "last_activity_time": 1773950134,
                # Fields that should be stripped:
                "scopes": ["scope1"] * 300,
                "permissions": {"access.management": ["admin"]},
                "groups": [{"name": "Group1", "unique_id": "g1"}],
                "roles": [{"name": "Owner", "unique_id": "r1"}],
                "resources": {"wifi": False, "vpn": False},
                "assignments": [{"id": "a1"}],
                "_id": 4,
                "alias": "",
                "radius_username": "",
                "avatar_relative_path": "",
                "avatar_rpath2": "",
                "employee_number": "",
                "sso_account": "chris@example.com",
                "sso_uuid": "some-uuid",
                "sso_username": "sirkirby",
                "sso_picture": "",
                "uid_sso_id": "",
                "uid_sso_account": "",
                "uid_account_status": "",
                "password_revision": 0,
                "login_time": 1773950134,
                "email_status": "VERIFIED",
                "email_is_null": False,
                "phone": "",
                "username": "",
                "local_account_exist": False,
                "only_ui_account": False,
                "only_local_account": False,
                "from_org": False,
                "org_role": "",
                "org_user_id": "",
                "previous_full_name": ["Old Name"],
                "cloud_access_granted": True,
                "update_time": 12345,
                "need_popup_ids_introduce": False,
                "avatar": "",
                "nfc_token": "",
                "nfc_card_status": "",
                "api_keys": [],
                "invalid_wg_ip": False,
                "invitation": None,
                "source_name": "UI",
                "user_status": "ACTIVE",
                "ucs_user_id": "",
                "extras": {"nfc_card_type": "ua_card", "nfc_display_id": "100003"},
                "permission_resources": [],
            }
        ]
        with patch.object(cm_proxy, "proxy_request_users", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": raw_users}
            users = await sys_mgr_proxy.list_users(compact=True)

        assert len(users) == 1
        user = users[0]
        # Essential fields kept
        assert user["unique_id"] == "u1"
        assert user["full_name"] == "Chris Kirby"
        assert user["email"] == "chris@example.com"
        assert user["status"] == "ACTIVE"
        assert user["nfc_display_id"] == "100003"
        assert user["nfc_card_type"] == "ua_card"
        assert user["create_time"] == 1662941769
        assert user["last_activity_time"] == 1773950134
        # Bloat fields stripped
        assert "scopes" not in user
        assert "permissions" not in user
        assert "groups" not in user
        assert "roles" not in user
        assert "resources" not in user
        assert "assignments" not in user
        assert "_id" not in user
        assert "sso_uuid" not in user
        assert "password_revision" not in user
        assert "avatar_relative_path" not in user
        assert "extras" not in user
