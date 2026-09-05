"""Tests for backup management tools in SystemManager.

Tests list, create, delete backups and auto-backup settings.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from unifi_core.redaction import REDACTED


class TestBackupTools:
    """Tests for backup-related SystemManager methods."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock ConnectionManager."""
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        conn._invalidate_cache = MagicMock()
        conn.ensure_connected = AsyncMock(return_value=True)
        return conn

    @pytest.fixture
    def system_manager(self, mock_connection):
        """Create a SystemManager with mocked connection."""
        from unifi_core.network.managers.system_manager import SystemManager

        mgr = SystemManager(mock_connection)
        return mgr

    # ---- Create Backup ----

    @pytest.mark.asyncio
    async def test_create_backup_list_response(self, system_manager, mock_connection):
        """Test create_backup handles list response with URL."""
        mock_connection.request.return_value = [{"url": "/dl/backup/10.1.89.unf"}]

        result = await system_manager.create_backup()

        assert result is not None
        assert result["url"] == "/dl/backup/10.1.89.unf"

    @pytest.mark.asyncio
    async def test_create_backup_dict_response(self, system_manager, mock_connection):
        """Test create_backup handles dict response with URL."""
        mock_connection.request.return_value = {"url": "/dl/backup/10.1.89.unf"}

        result = await system_manager.create_backup()

        assert result is not None
        assert result["url"] == "/dl/backup/10.1.89.unf"

    @pytest.mark.asyncio
    async def test_create_backup_unexpected_response(self, system_manager, mock_connection):
        """Test create_backup returns None on unexpected response."""
        mock_connection.request.return_value = {"no_url": True}

        result = await system_manager.create_backup()

        assert result is None

    @pytest.mark.asyncio
    async def test_create_backup_handles_error(self, system_manager, mock_connection):
        """Test create_backup returns None on error."""
        mock_connection.request.side_effect = Exception("Connection failed")

        with pytest.raises(Exception):
            await system_manager.create_backup()

    # ---- List Backups ----

    @pytest.mark.asyncio
    async def test_list_backups_returns_list(self, system_manager, mock_connection):
        """Test list_backups returns list of backup dicts."""
        backups = [
            {"filename": "autobackup_1.unf", "datetime": "2026-03-28", "size": 28000000},
            {"filename": "autobackup_2.unf", "datetime": "2026-03-27", "size": 27500000},
        ]
        mock_connection.request.return_value = backups

        result = await system_manager.list_backups()

        assert len(result) == 2
        assert result[0]["filename"] == "autobackup_1.unf"

    @pytest.mark.asyncio
    async def test_list_backups_handles_dict_response(self, system_manager, mock_connection):
        """Test list_backups handles dict with data key."""
        mock_connection.request.return_value = {"data": [{"filename": "backup.unf"}]}

        result = await system_manager.list_backups()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_list_backups_handles_error(self, system_manager, mock_connection):
        """Test list_backups returns empty list on error."""
        mock_connection.request.side_effect = Exception("Connection failed")

        with pytest.raises(Exception):
            await system_manager.list_backups()

    # ---- Delete Backup ----

    @pytest.mark.asyncio
    async def test_delete_backup_success(self, system_manager, mock_connection):
        """Test delete_backup sends correct command."""
        mock_connection.request.return_value = {}

        result = await system_manager.delete_backup("autobackup_1.unf")

        assert result is True
        call_args = mock_connection.request.call_args
        api_req = call_args[0][0]
        assert api_req.path == "/cmd/backup"
        assert api_req.data["cmd"] == "delete-backup"
        assert api_req.data["filename"] == "autobackup_1.unf"

    @pytest.mark.asyncio
    async def test_delete_backup_handles_error(self, system_manager, mock_connection):
        """Test delete_backup returns False on error."""
        mock_connection.request.side_effect = Exception("Failed")

        with pytest.raises(Exception):
            await system_manager.delete_backup("nonexistent.unf")

    # ---- Auto-Backup Settings ----

    @pytest.mark.asyncio
    async def test_get_autobackup_settings(self, system_manager, mock_connection):
        """Test get_autobackup_settings returns filtered settings."""
        mock_connection.request.return_value = [
            {
                "_id": "abc123",
                "autobackup_enabled": True,
                "autobackup_cron_expr": "0 2 * * *",
                "autobackup_days": 30,
                "autobackup_max_files": 10,
                "autobackup_timezone": "America/Denver",
                "autobackup_cloud_enabled": True,
                "other_field": "ignored",
            }
        ]

        result = await system_manager.get_autobackup_settings()

        assert result["autobackup_enabled"] is True
        assert result["autobackup_cron_expr"] == "0 2 * * *"
        assert result["autobackup_max_files"] == 10
        assert result["autobackup_cloud_enabled"] is True
        assert "other_field" not in result

    @pytest.mark.asyncio
    async def test_get_autobackup_settings_empty(self, system_manager, mock_connection):
        """Test get_autobackup_settings returns empty dict when no settings."""
        mock_connection.request.return_value = []

        result = await system_manager.get_autobackup_settings()

        assert result == {}

    @pytest.mark.asyncio
    async def test_update_autobackup_settings_success(self, system_manager, mock_connection):
        """Test update_autobackup_settings calls update_settings."""
        # First call: get_settings (for update_settings internal fetch-merge)
        # Second call: the actual PUT (returns list = success)
        mock_connection.request.side_effect = [
            [{"_id": "abc123", "autobackup_enabled": False}],
            [{"_id": "abc123", "autobackup_enabled": True}],
        ]

        result = await system_manager.update_autobackup_settings({"autobackup_enabled": True})

        assert result is True

    @pytest.mark.asyncio
    async def test_update_autobackup_settings_error(self, system_manager, mock_connection):
        """Test update_autobackup_settings returns False on error."""
        mock_connection.request.side_effect = Exception("Failed")

        with pytest.raises(Exception):
            await system_manager.update_autobackup_settings({"autobackup_enabled": True})

    # ---- API Path Verification ----

    @pytest.mark.asyncio
    async def test_list_backups_uses_correct_path(self, system_manager, mock_connection):
        """Test list_backups uses POST /cmd/backup with list-backups command."""
        mock_connection.request.return_value = []

        await system_manager.list_backups()

        call_args = mock_connection.request.call_args
        api_req = call_args[0][0]
        assert api_req.path == "/cmd/backup"
        assert api_req.method == "post"
        assert api_req.data["cmd"] == "list-backups"


class TestSnmpTools:
    """Tests for SNMP tool response redaction."""

    @pytest.mark.asyncio
    async def test_get_snmp_settings_redacts_community(self, monkeypatch):
        from unifi_network_mcp.tools import system

        mock_mgr = MagicMock()
        mock_mgr._connection.site = "default"
        mock_mgr.get_settings = AsyncMock(return_value=[{"enabled": True, "community": "public", "port": 161}])
        monkeypatch.setattr(system, "system_manager", mock_mgr)

        result = await system.get_snmp_settings()

        assert result["success"] is True
        assert result["snmp_settings"]["community"] == REDACTED

    @pytest.mark.asyncio
    async def test_update_snmp_settings_preview_redacts_community(self, monkeypatch):
        from unifi_network_mcp.tools import system

        mock_mgr = MagicMock()
        mock_mgr._connection.site = "default"
        mock_mgr.get_settings = AsyncMock(return_value=[{"enabled": False, "community": "public", "port": 161}])
        monkeypatch.setattr(system, "system_manager", mock_mgr)

        result = await system.update_snmp_settings(enabled=True, community="private", confirm=False)

        assert result["success"] is True
        assert result["preview"]["current"]["enabled"] is False
        assert result["preview"]["current"]["community"] == REDACTED
        assert result["preview"]["proposed"]["community"] == REDACTED

    @pytest.mark.asyncio
    async def test_get_snmp_settings_policy_disabled_returns_community(self, monkeypatch):
        from unifi_network_mcp.tools import system

        mock_mgr = MagicMock()
        mock_mgr._connection.site = "default"
        mock_mgr.get_settings = AsyncMock(return_value=[{"enabled": True, "community": "public", "port": 161}])
        monkeypatch.setattr(system, "system_manager", mock_mgr)
        monkeypatch.setenv("UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS", "false")

        result = await system.get_snmp_settings()

        assert result["snmp_settings"]["community"] == "public"

    # Redaction-marker write-back (community="***REDACTED***") is rejected
    # centrally at the MCP dispatch boundary (StrictKwargFastMCP.call_tool),
    # covered in the unifi-mcp-shared strict_dispatch tests.

    @pytest.mark.asyncio
    async def test_update_snmp_settings_confirm_redacts_community(self, monkeypatch):
        from unifi_network_mcp.tools import system

        mock_mgr = MagicMock()
        mock_mgr._connection.site = "default"
        mock_mgr.update_settings = AsyncMock(return_value=True)
        monkeypatch.setattr(system, "system_manager", mock_mgr)

        result = await system.update_snmp_settings(enabled=True, community="private", confirm=True)

        assert result["success"] is True
        assert result["snmp_settings"]["community"] == REDACTED


class TestMgmtTools:
    RECORD = [
        {
            "_id": "m1",
            "key": "mgmt",
            "x_ssh_enabled": True,
            "x_ssh_username": "ubnt",
            "x_ssh_auth_password_enabled": True,
            "x_ssh_password": "clear",
            "x_ssh_sha512passwd": "$6$hash",
            "x_ssh_keys": [{"name": "laptop", "type": "ssh-ed25519", "key": "AAAA"}],
            "x_ssh_bcrypt_passwd": "$2y$unknown-spelling",
            "debug_tools_enabled": False,
            "auto_upgrade": True,
            "auto_upgrade_hour": 3,
            "x_api_token": "tok-3f9a",
            "x_mgmt_key": "0123456789abcdef",
        }
    ]

    def _manager(self, monkeypatch, *, update_ok=True):
        from unifi_network_mcp.tools import system

        mgr = MagicMock()
        mgr._connection.site = "default"
        mgr.get_settings = AsyncMock(return_value=self.RECORD)
        mgr.update_settings = AsyncMock(return_value=update_ok)
        monkeypatch.setattr(system, "system_manager", mgr)
        return system, mgr

    @pytest.mark.asyncio
    async def test_get_redacts_secrets_and_keeps_flags_and_keys(self, monkeypatch):
        system, _ = self._manager(monkeypatch)

        result = await system.get_mgmt_settings()

        settings = result["mgmt_settings"]
        assert result["success"] is True
        assert settings["x_ssh_enabled"] is True
        assert settings["x_ssh_auth_password_enabled"] is True
        assert settings["x_ssh_password"] == REDACTED
        assert settings["x_ssh_keys"] == [{"name": "laptop", "type": "ssh-ed25519", "key": "AAAA"}]
        assert settings["ssh_password_hash_set"] is True and settings["mgmt_key_set"] is True
        for secret in ("$6$hash", "0123456789abcdef", "tok-3f9a", "clear", "$2y$unknown-spelling"):
            assert secret not in repr(result)

    @pytest.mark.asyncio
    async def test_get_policy_disabled_still_never_returns_stored_secrets(self, monkeypatch):
        system, _ = self._manager(monkeypatch)
        monkeypatch.setenv("UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS", "false")

        result = await system.get_mgmt_settings()

        assert result["mgmt_settings"]["x_ssh_password"] == "clear"
        for secret in ("$6$hash", "0123456789abcdef", "tok-3f9a", "$2y$unknown-spelling"):
            assert secret not in repr(result)

    @pytest.mark.asyncio
    async def test_preview_uses_live_state_redacts_and_warns_on_ssh_changes(self, monkeypatch):
        system, _ = self._manager(monkeypatch)

        result = await system.update_mgmt_settings(
            update_data={"x_ssh_enabled": False, "x_ssh_password": "new"}, confirm=False
        )

        assert result["requires_confirmation"] is True
        assert result["preview"]["current"]["x_ssh_enabled"] is True
        assert result["preview"]["current"]["x_ssh_password"] == REDACTED
        assert result["preview"]["proposed"] == {"x_ssh_enabled": False, "x_ssh_password": REDACTED}
        assert any("every adopted device" in w for w in result["warnings"])
        assert "new" not in repr(result["preview"]) and "$6$hash" not in repr(result)

    @pytest.mark.asyncio
    async def test_confirm_sends_only_the_supplied_fields(self, monkeypatch):
        system, mgr = self._manager(monkeypatch)

        result = await system.update_mgmt_settings(update_data={"auto_upgrade_hour": 4}, confirm=True)

        mgr.update_settings.assert_awaited_once_with("mgmt", {"auto_upgrade_hour": 4})
        assert result["success"] is True
        assert result["mgmt_settings"] == {"auto_upgrade_hour": 4}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "update_data,named",
        [
            ({}, ""),
            ({"x_mgmt_key": "k"}, "x_mgmt_key"),
            ({"unknown": 1}, "unknown"),
            ({"x_ssh_enabled": True, "x_ssh_userame": "admin"}, "x_ssh_userame"),
            ({"x_ssh_username": None}, "Updatable keys"),
        ],
    )
    async def test_empty_unknown_or_read_only_updates_are_rejected_by_name(self, monkeypatch, update_data, named):
        system, mgr = self._manager(monkeypatch)

        result = await system.update_mgmt_settings(update_data=update_data, confirm=True)

        assert result["success"] is False and named in result["error"]
        mgr.update_settings.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_hour_is_reported_without_a_write(self, monkeypatch):
        system, mgr = self._manager(monkeypatch)

        result = await system.update_mgmt_settings(update_data={"auto_upgrade_hour": 25}, confirm=True)

        assert result["success"] is False and "auto_upgrade_hour" in result["error"]
        mgr.update_settings.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failures_report_class_or_code_only(self, monkeypatch, caplog):
        import logging

        system, mgr = self._manager(monkeypatch)
        mgr.update_settings = AsyncMock(side_effect=RuntimeError("rejected x_ssh_password=hunter2"))

        with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
            result = await system.update_mgmt_settings(update_data={"x_ssh_password": "hunter2"}, confirm=True)

        assert result["success"] is False and "RuntimeError" in result["error"]
        assert "hunter2" not in result["error"] and "hunter2" not in caplog.text
        assert all(r.exc_info is None for r in caplog.records)

    @pytest.mark.asyncio
    async def test_controller_error_code_is_reported_and_message_shaped_codes_are_not(self, monkeypatch):
        from aiounifi.errors import AiounifiException

        system, mgr = self._manager(monkeypatch)
        mgr.update_settings = AsyncMock(
            side_effect=AiounifiException({"meta": {"rc": "error", "msg": "api.err.InvalidPayload"}, "data": []})
        )
        result = await system.update_mgmt_settings(update_data={"x_ssh_password": "hunter2"}, confirm=True)
        assert result["error"] == "Failed to update management settings: api.err.InvalidPayload"

        mgr.update_settings = AsyncMock(
            side_effect=AiounifiException({"meta": {"rc": "error", "msg": "api.err.Invalid x_ssh_password=hunter2"}})
        )
        result = await system.update_mgmt_settings(update_data={"x_ssh_password": "hunter2"}, confirm=True)
        assert result["error"] == "Failed to update management settings: AiounifiException"

    @pytest.mark.asyncio
    async def test_get_and_preview_failures_leak_nothing(self, monkeypatch, caplog):
        import logging

        system, mgr = self._manager(monkeypatch)
        mgr.get_settings = AsyncMock(side_effect=RuntimeError("x_ssh_password=hunter2"))

        with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
            got = await system.get_mgmt_settings()
            previewed = await system.update_mgmt_settings(update_data={"auto_upgrade": True}, confirm=False)

        for result in (got, previewed):
            assert result["success"] is False and "RuntimeError" in result["error"]
            assert "hunter2" not in result["error"]
        assert "hunter2" not in caplog.text
        mgr.update_settings.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_controller_rejecting_the_write_is_reported(self, monkeypatch):
        system, _ = self._manager(monkeypatch, update_ok=False)

        result = await system.update_mgmt_settings(update_data={"auto_upgrade": True}, confirm=True)

        assert result == {"success": False, "error": "Failed to update management settings."}

    @pytest.mark.asyncio
    async def test_rejected_update_names_the_key_and_the_allowed_ones(self, monkeypatch):
        system, _ = self._manager(monkeypatch)

        result = await system.update_mgmt_settings(update_data={"led_enabled": True}, confirm=True)

        assert "led_enabled" in result["error"] and "x_ssh_enabled" in result["error"]

    @pytest.mark.asyncio
    async def test_confirm_echo_excludes_the_ids_the_manager_adds(self, monkeypatch):
        """The real manager adds _id and key to the dict it is given."""
        system, mgr = self._manager(monkeypatch)

        async def _mutating_update(section, data):
            data["_id"], data["key"] = "m1", section
            return True

        mgr.update_settings = AsyncMock(side_effect=_mutating_update)

        result = await system.update_mgmt_settings(update_data={"auto_upgrade": True}, confirm=True)

        assert result["mgmt_settings"] == {"auto_upgrade": True}

    @pytest.mark.asyncio
    async def test_ssh_keys_write_is_warned(self, monkeypatch):
        system, _ = self._manager(monkeypatch)

        result = await system.update_mgmt_settings(update_data={"x_ssh_keys": []}, confirm=False)

        assert any("authorised-key list" in w for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_malformed_field_is_named_without_its_value(self, monkeypatch):
        system, mgr = self._manager(monkeypatch)

        result = await system.update_mgmt_settings(update_data={"x_ssh_keys": "not-a-list"}, confirm=True)

        assert result["success"] is False and "x_ssh_keys" in result["error"] and "not-a-list" not in result["error"]
        mgr.update_settings.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ssh_keys_round_trip_unredacted(self, monkeypatch):
        system, mgr = self._manager(monkeypatch)
        keys = [{"name": "laptop", "type": "ssh-ed25519", "key": "AAAA"}]

        preview = await system.update_mgmt_settings(update_data={"x_ssh_keys": keys}, confirm=False)
        await system.update_mgmt_settings(update_data={"x_ssh_keys": keys}, confirm=True)

        assert preview["preview"]["proposed"]["x_ssh_keys"] == keys
        mgr.update_settings.assert_awaited_once_with("mgmt", {"x_ssh_keys": keys})
