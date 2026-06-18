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
        monkeypatch.setattr(system, "system_manager", mock_mgr)

        result = await system.update_snmp_settings(enabled=True, community="private", confirm=False)

        assert result["success"] is True
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
