"""Tests for CredentialManager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.access.managers.credential_manager import CredentialManager
from unifi_core.exceptions import UniFiConnectionError
from unifi_core.redaction import REDACTED

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cm_proxy():
    cm = AccessConnectionManager(host="192.168.1.1", username="admin", password="secret")
    cm._proxy_available = True
    cm._proxy_session = MagicMock()
    return cm


@pytest.fixture
def cm_none():
    return AccessConnectionManager(host="192.168.1.1", username="", password="")


@pytest.fixture
def cred_mgr(cm_proxy):
    return CredentialManager(cm_proxy)


@pytest.fixture
def cred_mgr_none(cm_none):
    return CredentialManager(cm_none)


# ---------------------------------------------------------------------------
# list_credentials
# ---------------------------------------------------------------------------


class TestListCredentials:
    @pytest.mark.asyncio
    async def test_list_credentials_success(self, cred_mgr, cm_proxy):
        expected = [{"id": "cred-1", "type": "nfc", "user_id": "u1"}]
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": expected}
            result = await cred_mgr.list_credentials()
        assert result == expected

    @pytest.mark.asyncio
    async def test_list_credentials_no_proxy(self, cred_mgr_none):
        with pytest.raises(UniFiConnectionError, match="No proxy session"):
            await cred_mgr_none.list_credentials()


# ---------------------------------------------------------------------------
# get_credential
# ---------------------------------------------------------------------------


class TestGetCredential:
    @pytest.mark.asyncio
    async def test_get_credential_success(self, cred_mgr, cm_proxy):
        expected = {"id": "cred-1", "type": "nfc", "status": "active"}
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": expected}
            result = await cred_mgr.get_credential("cred-1")
        assert result == expected

    @pytest.mark.asyncio
    async def test_get_credential_empty_id(self, cred_mgr):
        with pytest.raises(ValueError, match="credential_id is required"):
            await cred_mgr.get_credential("")

    @pytest.mark.asyncio
    async def test_get_credential_no_proxy(self, cred_mgr_none):
        with pytest.raises(UniFiConnectionError, match="No proxy session"):
            await cred_mgr_none.get_credential("cred-1")


# ---------------------------------------------------------------------------
# create_credential (preview)
# ---------------------------------------------------------------------------


class TestCreateCredential:
    @pytest.mark.asyncio
    async def test_create_credential_preview(self, cred_mgr):
        preview = await cred_mgr.create_credential("nfc", {"user_id": "u1", "token": "abc"})
        assert preview["credential_type"] == "nfc"
        assert preview["proposed_changes"]["action"] == "create"
        assert preview["proposed_changes"]["type"] == "nfc"

    @pytest.mark.asyncio
    async def test_create_credential_empty_type(self, cred_mgr):
        with pytest.raises(ValueError, match="credential_type is required"):
            await cred_mgr.create_credential("", {"user_id": "u1"})

    @pytest.mark.asyncio
    async def test_create_credential_empty_data(self, cred_mgr):
        with pytest.raises(ValueError, match="credential data must not be empty"):
            await cred_mgr.create_credential("nfc", {})


# ---------------------------------------------------------------------------
# apply_create_credential
# ---------------------------------------------------------------------------


class TestApplyCreateCredential:
    @pytest.mark.asyncio
    async def test_apply_create_success(self, cred_mgr, cm_proxy):
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": {"id": "cred-new"}}
            result = await cred_mgr.apply_create_credential("nfc", {"user_id": "u1"})
        assert result["result"] == "success"
        assert result["credential_type"] == "nfc"

    @pytest.mark.asyncio
    async def test_apply_create_no_proxy(self, cred_mgr_none):
        with pytest.raises(UniFiConnectionError, match="No proxy session"):
            await cred_mgr_none.apply_create_credential("nfc", {"user_id": "u1"})


# ---------------------------------------------------------------------------
# revoke_credential (preview)
# ---------------------------------------------------------------------------


class TestRevokeCredential:
    @pytest.mark.asyncio
    async def test_revoke_credential_preview(self, cred_mgr, cm_proxy):
        current = {"id": "cred-1", "type": "nfc", "status": "active"}
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": current}
            preview = await cred_mgr.revoke_credential("cred-1")
        assert preview["credential_id"] == "cred-1"
        assert preview["proposed_changes"]["action"] == "revoke"

    @pytest.mark.asyncio
    async def test_revoke_credential_empty_id(self, cred_mgr):
        with pytest.raises(ValueError, match="credential_id is required"):
            await cred_mgr.revoke_credential("")


# ---------------------------------------------------------------------------
# apply_revoke_credential
# ---------------------------------------------------------------------------


class TestApplyRevokeCredential:
    @pytest.mark.asyncio
    async def test_apply_revoke_success(self, cred_mgr, cm_proxy):
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {}
            result = await cred_mgr.apply_revoke_credential("cred-1")
        assert result["result"] == "success"
        assert result["action"] == "revoke"

    @pytest.mark.asyncio
    async def test_apply_revoke_no_proxy(self, cred_mgr_none):
        with pytest.raises(UniFiConnectionError, match="No proxy session"):
            await cred_mgr_none.apply_revoke_credential("cred-1")


# ---------------------------------------------------------------------------
# MCP tool response redaction
# ---------------------------------------------------------------------------


class TestCredentialToolRedaction:
    @pytest.mark.asyncio
    async def test_create_credential_preview_redacts_token_and_pin(self):
        with patch("unifi_access_mcp.tools.credentials.credential_manager") as mock_mgr:
            mock_mgr.create_credential = AsyncMock(
                return_value={
                    "proposed_changes": {
                        "action": "create",
                        "type": "pin",
                        "user_id": "user1",
                        "token": "nfc-token",
                        "pin_code": "123456",
                    }
                }
            )

            from unifi_access_mcp.tools.credentials import access_create_credential

            result = await access_create_credential(
                "pin",
                {"user_id": "user1", "token": "nfc-token", "pin_code": "123456"},
                confirm=False,
            )

        assert result["preview"]["will_create"]["token"] == REDACTED
        assert result["preview"]["will_create"]["pin_code"] == REDACTED

    @pytest.mark.asyncio
    async def test_create_credential_confirm_redacts_result_token_and_pin(self):
        with patch("unifi_access_mcp.tools.credentials.credential_manager") as mock_mgr:
            mock_mgr.apply_create_credential = AsyncMock(
                return_value={"result": "success", "token": "nfc-token", "pin_code": "123456"}
            )

            from unifi_access_mcp.tools.credentials import access_create_credential

            result = await access_create_credential(
                "pin",
                {"user_id": "user1", "token": "nfc-token", "pin_code": "123456"},
                confirm=True,
            )

        assert result["data"]["token"] == REDACTED
        assert result["data"]["pin_code"] == REDACTED

    @pytest.mark.asyncio
    async def test_get_credential_redacts_by_default_and_allows_policy_disable(self, monkeypatch):
        secret = {"id": "cred-1", "type": "nfc", "user_id": "u1", "token": "AABBCCDD", "pin_code": "123456"}
        with patch("unifi_access_mcp.tools.credentials.credential_manager") as mock_mgr:
            mock_mgr.get_credential = AsyncMock(return_value=secret)

            from unifi_access_mcp.tools.credentials import access_get_credential

            default = await access_get_credential("cred-1")
            monkeypatch.setenv("UNIFI_ACCESS_REDACT_SENSITIVE_FIELDS", "false")
            raw = await access_get_credential("cred-1")

        assert default["data"]["token"] == REDACTED
        assert default["data"]["pin_code"] == REDACTED
        assert raw["data"]["token"] == "AABBCCDD"
        assert raw["data"]["pin_code"] == "123456"

    @pytest.mark.asyncio
    async def test_list_credentials_redacts_token_and_pin_by_default(self):
        secret = {"id": "cred-1", "type": "nfc", "user_id": "u1", "token": "AABBCCDD", "pin_code": "123456"}
        with patch("unifi_access_mcp.tools.credentials.credential_manager") as mock_mgr:
            mock_mgr.list_credentials = AsyncMock(return_value=[secret])

            from unifi_access_mcp.tools.credentials import access_list_credentials

            result = await access_list_credentials()

        cred = result["data"]["credentials"][0]
        assert cred["token"] == REDACTED
        assert cred["pin_code"] == REDACTED
