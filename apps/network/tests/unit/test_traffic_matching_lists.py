"""Tests for the Integration API traffic matching list tools and manager.

Loopback stubs only: no real controller is contacted. Hosts use TEST-NET
addresses so an accidental live call is impossible.
"""

import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")
os.environ.setdefault("UNIFI_NETWORK_API_KEY", "test-key")

from unifi_core.exceptions import (  # noqa: E402
    UniFiAuthError,
    UniFiMalformedResponseError,
)

PORT_LIST_RAW = {
    "id": "ffcdb32c-6278-4364-8947-df4f77118df8",
    "name": "Allowed port list",
    "type": "PORT",
    "items": [{"type": "number", "value": 443}],
}
PAGE_RAW = {
    "count": 1,
    "data": [PORT_LIST_RAW],
    "limit": 25,
    "offset": 0,
    "totalCount": 1,
}


class TestTrafficMatchingListTools:
    """Test the four tools' preview/confirm and error paths."""

    @pytest.mark.asyncio
    async def test_list_returns_normalized_entries(self):
        from unifi_network_mcp.tools.traffic_matching_lists import list_traffic_matching_lists

        with patch("unifi_network_mcp.tools.traffic_matching_lists.traffic_matching_list_manager") as mock_mgr:
            mock_mgr.list_traffic_matching_lists = AsyncMock(return_value=PAGE_RAW)

            result = await list_traffic_matching_lists()

        assert result["success"] is True
        assert len(result["lists"]) == 1
        entry = result["lists"][0]
        assert entry["name"] == "Allowed port list"
        assert entry["type"] == "PORT"
        assert len(entry["items"]) == 1
        mock_mgr.list_traffic_matching_lists.assert_awaited_once_with(
            offset=0, limit=25, filter_expr=None, site_id=None
        )

    @pytest.mark.asyncio
    async def test_get_requires_list_id(self):
        from unifi_network_mcp.tools.traffic_matching_lists import get_traffic_matching_list

        result = await get_traffic_matching_list(list_id="", site_id=None)

        assert result["success"] is False
        assert "list_id is required" in result["error"]

    @pytest.mark.asyncio
    async def test_get_returns_normalized_list(self):
        from unifi_network_mcp.tools.traffic_matching_lists import get_traffic_matching_list

        with patch("unifi_network_mcp.tools.traffic_matching_lists.traffic_matching_list_manager") as mock_mgr:
            mock_mgr.get_traffic_matching_list = AsyncMock(return_value=PORT_LIST_RAW)

            result = await get_traffic_matching_list(list_id=PORT_LIST_RAW["id"], site_id=None)

        assert result["success"] is True
        assert result["list"]["name"] == "Allowed port list"
        assert result["list"]["type"] == "PORT"
        mock_mgr.get_traffic_matching_list.assert_awaited_once_with(PORT_LIST_RAW["id"], site_id=None)

    @pytest.mark.asyncio
    async def test_typed_transport_errors_surface_their_fixed_text(self):
        from unifi_network_mcp.tools.traffic_matching_lists import list_traffic_matching_lists

        with patch("unifi_network_mcp.tools.traffic_matching_lists.traffic_matching_list_manager") as mock_mgr:
            mock_mgr.list_traffic_matching_lists = AsyncMock(side_effect=UniFiAuthError("remediation text"))

            result = await list_traffic_matching_lists()

        assert result["success"] is False
        assert "remediation text" in result["error"]

    @pytest.mark.asyncio
    async def test_create_requires_name_and_type(self):
        from unifi_network_mcp.tools.traffic_matching_lists import create_traffic_matching_list

        result = await create_traffic_matching_list(name="", type="PORT", confirm=True)
        assert result["success"] is False
        assert "name is required" in result["error"]

        result = await create_traffic_matching_list(name="Allowed", type=" ", confirm=True)
        assert result["success"] is False
        assert "type is required" in result["error"]

    @pytest.mark.asyncio
    async def test_create_preview_does_not_call_controller(self):
        from unifi_network_mcp.tools.traffic_matching_lists import create_traffic_matching_list

        with patch("unifi_network_mcp.tools.traffic_matching_lists.traffic_matching_list_manager") as mock_mgr:
            result = await create_traffic_matching_list(
                name="Allowed port list", type="PORT", items=[{"type": "number", "value": 443}], confirm=False
            )

        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["preview"]["will_create"]["name"] == "Allowed port list"
        assert result["preview"]["will_create"]["items"] == [{"type": "number", "value": 443}]
        mock_mgr.create_traffic_matching_list.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_preview_rejects_invalid_items(self):
        from unifi_network_mcp.tools.traffic_matching_lists import create_traffic_matching_list

        result = await create_traffic_matching_list(
            name="Allowed port list", type="PORTS", items="not-a-list", confirm=False
        )

        assert result["success"] is False
        assert "items must be a list of objects" in result["error"]

    @pytest.mark.asyncio
    async def test_create_preview_redacts_passthrough_fields(self):
        from unifi_network_mcp.tools import traffic_matching_lists as tools

        with patch.object(tools, "should_redact_sensitive_fields", return_value=True):
            result = await tools.create_traffic_matching_list(
                name="Allowed port list",
                type="PORTS",
                items=[{"value": 443, "api_key": "controller-only-secret"}],
                confirm=False,
            )

        assert result["preview"]["will_create"]["items"][0]["api_key"] == "***REDACTED***"

    @pytest.mark.asyncio
    async def test_create_confirm_sends_documented_payload_with_items(self):
        from unifi_network_mcp.tools.traffic_matching_lists import create_traffic_matching_list

        with patch("unifi_network_mcp.tools.traffic_matching_lists.traffic_matching_list_manager") as mock_mgr:
            mock_mgr.create_traffic_matching_list = AsyncMock(return_value=PORT_LIST_RAW)

            result = await create_traffic_matching_list(
                name="Allowed port list", type="PORT", items=[{"type": "number", "value": 443}], confirm=True
            )

        assert result["success"] is True
        mock_mgr.create_traffic_matching_list.assert_awaited_once_with(
            "Allowed port list", "PORT", items=[{"type": "number", "value": 443}], site_id=None
        )

    @pytest.mark.asyncio
    async def test_delete_preview_reads_live_state_and_does_not_delete(self):
        from unifi_network_mcp.tools.traffic_matching_lists import delete_traffic_matching_list

        with patch("unifi_network_mcp.tools.traffic_matching_lists.traffic_matching_list_manager") as mock_mgr:
            mock_mgr.get_traffic_matching_list = AsyncMock(return_value=PORT_LIST_RAW)
            mock_mgr.delete_traffic_matching_list = AsyncMock()

            result = await delete_traffic_matching_list(list_id=PORT_LIST_RAW["id"], confirm=False)

        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["preview"]["will_delete"]["name"] == "Allowed port list"
        mock_mgr.delete_traffic_matching_list.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_confirm_reports_success(self):
        from unifi_network_mcp.tools.traffic_matching_lists import delete_traffic_matching_list

        with patch("unifi_network_mcp.tools.traffic_matching_lists.traffic_matching_list_manager") as mock_mgr:
            mock_mgr.delete_traffic_matching_list = AsyncMock(return_value=True)

            result = await delete_traffic_matching_list(list_id=PORT_LIST_RAW["id"], confirm=True)

        assert result["success"] is True
        assert "deleted" in result["message"]
        mock_mgr.delete_traffic_matching_list.assert_awaited_once_with(PORT_LIST_RAW["id"], site_id=None)

    @pytest.mark.asyncio
    async def test_error_paths_return_operation_context_without_exception_text(self):
        from unifi_network_mcp.tools.traffic_matching_lists import (
            get_traffic_matching_list,
            list_traffic_matching_lists,
        )

        with patch("unifi_network_mcp.tools.traffic_matching_lists.traffic_matching_list_manager") as mock_mgr:
            mock_mgr.list_traffic_matching_lists = AsyncMock(side_effect=RuntimeError("secret detail"))
            result = await list_traffic_matching_lists()
        assert result["success"] is False
        assert "Failed to list traffic matching lists" in result["error"]
        assert "secret detail" not in result["error"]

        with patch("unifi_network_mcp.tools.traffic_matching_lists.traffic_matching_list_manager") as mock_mgr:
            mock_mgr.get_traffic_matching_list = AsyncMock(side_effect=RuntimeError("secret detail"))
            result = await get_traffic_matching_list(list_id=PORT_LIST_RAW["id"])
        assert result["success"] is False
        assert "Failed to get traffic matching list" in result["error"]
        assert "secret detail" not in result["error"]

    @pytest.mark.asyncio
    async def test_create_surfaces_typed_auth_error(self):
        from unifi_core.exceptions import UniFiAuthError
        from unifi_network_mcp.tools.traffic_matching_lists import create_traffic_matching_list

        with patch("unifi_network_mcp.tools.traffic_matching_lists.traffic_matching_list_manager") as mock_mgr:
            mock_mgr.create_traffic_matching_list = AsyncMock(
                side_effect=UniFiAuthError("Create a Network API token in UniFi Control Plane -> Integrations.")
            )
            result = await create_traffic_matching_list(name="New list", type="PORTS", confirm=True)

        assert result["success"] is False
        assert "Failed to create traffic matching list" in result["error"]
        assert "Network API token" in result["error"]

    @pytest.mark.asyncio
    async def test_mcp_returns_redact_sensitive_payloads(self):
        from unifi_network_mcp.tools import traffic_matching_lists as tools

        raw = {**PORT_LIST_RAW, "items": [{"value": 443, "api_key": "controller-only-secret"}]}
        with (
            patch.object(tools, "should_redact_sensitive_fields", return_value=True),
            patch.object(tools, "traffic_matching_list_manager") as mock_mgr,
        ):
            mock_mgr.get_traffic_matching_list = AsyncMock(return_value=raw)
            result = await tools.get_traffic_matching_list(list_id=raw["id"])

        assert result["list"]["items"][0]["api_key"] == "***REDACTED***"

    @pytest.mark.asyncio
    async def test_error_logs_omit_tracebacks_and_private_text(self, caplog):
        from unifi_network_mcp.tools.traffic_matching_lists import list_traffic_matching_lists

        with patch("unifi_network_mcp.tools.traffic_matching_lists.traffic_matching_list_manager") as mock_mgr:
            mock_mgr.list_traffic_matching_lists = AsyncMock(side_effect=RuntimeError("secret detail"))
            with caplog.at_level(logging.ERROR):
                result = await list_traffic_matching_lists()

        assert result["success"] is False
        assert all(record.exc_info is None for record in caplog.records)
        assert "secret detail" not in caplog.text
        assert "RuntimeError" in caplog.text


class TestTrafficMatchingListManager:
    """Test request construction: paths, params, payload, empty-200 handling."""

    def _manager(self, auth):
        from unifi_core.network.managers.traffic_matching_list_manager import TrafficMatchingListManager

        connection = MagicMock()
        connection.site = "default"
        connection.host = "192.0.2.10"
        connection.port = 443
        connection.tls_env_prefix = None
        return TrafficMatchingListManager(connection, auth)

    @pytest.mark.asyncio
    async def test_missing_api_key_fails_before_any_request(self):
        from unifi_core.exceptions import UniFiAuthError

        manager = self._manager(auth=None)

        with pytest.raises(UniFiAuthError) as exc_info:
            await manager.list_traffic_matching_lists()

        assert "requires a UniFi API key" in str(exc_info.value)
        assert "Control Plane -> Integrations" in str(exc_info.value)

    def _mocked_session(self, auth, payload):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=payload)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        session = AsyncMock()
        session.request = MagicMock(return_value=mock_ctx)
        session.close = AsyncMock()
        auth.get_api_key_session.return_value = session
        return session

    @pytest.mark.asyncio
    async def test_list_sends_pagination_params(self):
        from unifi_core.auth import UniFiAuth

        auth = MagicMock(spec=UniFiAuth)
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock()
        manager = self._manager(auth)
        manager._get_integration_site_id = AsyncMock(return_value="site-uuid")
        session = self._mocked_session(auth, PAGE_RAW)

        result = await manager.list_traffic_matching_lists(offset=10, limit=50, filter_expr="name like 'Allowed'")

        assert result == PAGE_RAW
        method, url = session.request.call_args.args
        assert method == "GET"
        assert url.endswith("/proxy/network/integration/v1/sites/site-uuid/traffic-matching-lists")
        assert session.request.call_args.kwargs["params"] == {
            "offset": "10",
            "limit": "50",
            "filter": "name like 'Allowed'",
        }

    @pytest.mark.asyncio
    async def test_list_all_collects_every_page(self):
        from unifi_core.auth import UniFiAuth

        auth = MagicMock(spec=UniFiAuth)
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock()
        manager = self._manager(auth)
        second = {"id": "second-uuid", "name": "Second list", "type": "PORTS", "items": []}
        first_page = {**PAGE_RAW, "totalCount": 2, "limit": 200, "offset": 0}
        second_page = {"data": [second], "totalCount": 2, "limit": 200, "offset": 1}
        manager.list_traffic_matching_lists = AsyncMock(side_effect=[first_page, second_page])

        result = await manager.list_all_traffic_matching_lists()

        assert [item["id"] for item in result] == [
            "ffcdb32c-6278-4364-8947-df4f77118df8",
            "second-uuid",
        ]
        assert manager.list_traffic_matching_lists.await_count == 2
        assert manager.list_traffic_matching_lists.await_args_list[0].kwargs["offset"] == 0
        assert manager.list_traffic_matching_lists.await_args_list[1].kwargs["offset"] == 1

    @pytest.mark.asyncio
    async def test_create_posts_documented_body(self):
        from unifi_core.auth import UniFiAuth

        auth = MagicMock(spec=UniFiAuth)
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock()
        manager = self._manager(auth)
        manager._get_integration_site_id = AsyncMock(return_value="site-uuid")
        session = self._mocked_session(auth, PORT_LIST_RAW)

        result = await manager.create_traffic_matching_list("Allowed port list", "PORT", items=[{"value": 443}])

        assert result == PORT_LIST_RAW
        method, url = session.request.call_args.args
        assert method == "POST"
        assert session.request.call_args.kwargs["json"] == {
            "name": "Allowed port list",
            "type": "PORT",
            "items": [{"value": 443}],
        }

    @pytest.mark.asyncio
    async def test_delete_treats_empty_200_as_success(self):
        from unifi_core.auth import UniFiAuth

        auth = MagicMock(spec=UniFiAuth)
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock()
        manager = self._manager(auth)
        manager._get_integration_site_id = AsyncMock(return_value="site-uuid")
        session = self._mocked_session(auth, {})

        assert await manager.delete_traffic_matching_list("ffcdb32c-6278-4364-8947-df4f77118df8") is True
        method, url = session.request.call_args.args
        assert method == "DELETE"
        assert url.endswith("/traffic-matching-lists/ffcdb32c-6278-4364-8947-df4f77118df8")

    @pytest.mark.asyncio
    async def test_delete_treats_a_null_json_body_as_success(self):
        # The live controller answers a successful DELETE with a literal JSON
        # null; that is the applied mutation, not a malformed response.
        from unifi_core.auth import UniFiAuth

        auth = MagicMock(spec=UniFiAuth)
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock()
        manager = self._manager(auth)
        manager._get_integration_site_id = AsyncMock(return_value="site-uuid")
        self._mocked_session(auth, None)

        assert await manager.delete_traffic_matching_list("ffcdb32c-6278-4364-8947-df4f77118df8") is True

    @pytest.mark.asyncio
    async def test_malformed_page_raises_instead_of_reporting_empty(self):
        from unifi_core.auth import UniFiAuth

        auth = MagicMock(spec=UniFiAuth)
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock()
        manager = self._manager(auth)
        manager._get_integration_site_id = AsyncMock(return_value="site-uuid")
        self._mocked_session(auth, {"unexpected": True})

        with pytest.raises(UniFiMalformedResponseError) as exc_info:
            await manager.list_traffic_matching_lists()

        assert "invalid traffic matching list page" in str(exc_info.value)


class TestTrafficMatchingListModel:
    def test_field_symmetry_between_model_and_create(self):
        from unifi_core.network.models.traffic_matching_lists import (
            MUTABLE_FIELDS,
            READ_ONLY_FIELDS,
            from_controller,
            to_controller_create,
        )

        model = from_controller(PORT_LIST_RAW)
        dumped = model.model_dump()
        for field in MUTABLE_FIELDS:
            assert field in dumped
        assert "id" in READ_ONLY_FIELDS
        payload = to_controller_create("Allowed port list", "PORT", [{"value": 443}])
        # Every mutable field is a create parameter, and nothing else is sent.
        assert set(payload.keys()) == set(MUTABLE_FIELDS)
        assert payload["type"] == "PORT"
        assert payload["items"] == [{"value": 443}]

    def test_type_is_carried_opaquely(self):
        from unifi_core.network.models.traffic_matching_lists import from_controller

        weird = dict(PORT_LIST_RAW, type="SOME_FUTURE_TYPE")
        assert from_controller(weird).type == "SOME_FUTURE_TYPE"


class TestTrafficMatchingListRegistration:
    def test_tools_are_in_manifest_with_expected_annotations(self):
        import json
        from pathlib import Path

        manifest_path = Path(__file__).resolve().parents[2] / "src" / "unifi_network_mcp" / "tools_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        tools = {tool["name"]: tool for tool in manifest["tools"]}

        expected = {
            "unifi_list_traffic_matching_lists": (True, None),
            "unifi_get_traffic_matching_list": (True, None),
            "unifi_create_traffic_matching_list": (False, False),
            "unifi_delete_traffic_matching_list": (False, True),
        }
        assert set(expected) <= set(tools)
        for name, (read_only, destructive) in expected.items():
            annotations = tools[name]["annotations"]
            assert annotations["readOnlyHint"] is read_only
            if destructive is not None:
                assert annotations["destructiveHint"] is destructive

    def test_traffic_matching_list_policy_gate_denies_write_actions(self, monkeypatch):
        from unifi_core.policy_gate import PolicyGateChecker
        from unifi_network_mcp.categories import NETWORK_CATEGORY_MAP

        checker = PolicyGateChecker("network", NETWORK_CATEGORY_MAP)
        for action in ("create", "delete"):
            name = f"UNIFI_POLICY_NETWORK_TRAFFIC_MATCHING_LISTS_{action.upper()}"
            monkeypatch.setenv(name, "false")
            assert checker.check("traffic_matching_lists", action) is False
            assert name in checker.denial_message("traffic_matching_lists", action)
            monkeypatch.delenv(name)
