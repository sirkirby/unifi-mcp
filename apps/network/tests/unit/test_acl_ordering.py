"""Tests for the Integration API ACL rule ordering tools.

Covers the tool layer (preview/confirm, error paths) and the manager's
Integration API request construction, including the manager-side stale-set
revalidation that also protects the REST/GraphQL dispatch surface. The V2
MAC ACL rule CRUD has its own suite in test_acl_manager.py; these two
resources are disjoint.
"""

import copy
import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")
os.environ.setdefault("UNIFI_NETWORK_API_KEY", "test-key")

CURRENT_ORDERING = [
    "11111111-1111-1111-1111-111111111111",
    "22222222-2222-2222-2222-222222222222",
    "33333333-3333-3333-3333-333333333333",
]
REVERSED_ORDERING = list(reversed(CURRENT_ORDERING))

SAMPLE_RULES_PAGE = {
    "count": 1,
    "data": [
        {
            "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "name": "Block guest",
            "index": 2000,
            "action": "BLOCK",
            "enabled": True,
            "type": "MAC",
            "networkIdFilter": {"type": "ANY"},
            "metadata": {},
        }
    ],
    "limit": 25,
    "offset": 0,
    "totalCount": 1,
}

RULE_ID = "11111111-1111-1111-1111-111111111111"


class TestListIntegrationAclRulesTool:
    @pytest.mark.asyncio
    async def test_list_integration_acl_rules_normalizes_entries(self):
        from unifi_network_mcp.tools.acl import list_integration_acl_rules

        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.list_integration_acl_rules = AsyncMock(return_value=SAMPLE_RULES_PAGE["data"])
            mock_mgr._connection.site = "default"

            result = await list_integration_acl_rules(site_id=None)

        assert result["success"] is True
        assert result["count"] == 1
        rule = result["rules"][0]
        assert rule["id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert rule["name"] == "Block guest"
        assert rule["index"] == 2000
        assert rule["action"] == "BLOCK"
        assert rule["network_id_filter"] == {"type": "ANY"}
        assert set(rule["raw"].keys()) == {"metadata"}
        mock_mgr.list_integration_acl_rules.assert_awaited_once_with(site_id=None)

    @pytest.mark.asyncio
    async def test_list_integration_acl_rules_error_path(self):
        from unifi_network_mcp.tools.acl import list_integration_acl_rules

        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.list_integration_acl_rules = AsyncMock(side_effect=RuntimeError("secret detail"))

            result = await list_integration_acl_rules(site_id=None)

        assert result["success"] is False
        assert "Failed to list Integration ACL rules" in result["error"]
        assert "secret detail" not in result["error"]

    @pytest.mark.asyncio
    async def test_list_tool_redacts_passthrough_fields(self):
        from unifi_network_mcp.tools import acl as acl_tools

        raw_rule = {
            **copy.deepcopy(SAMPLE_RULES_PAGE["data"][0]),
            "api_key": "controller-only-secret",
        }
        with (
            patch.object(acl_tools, "should_redact_sensitive_fields", return_value=True),
            patch.object(acl_tools, "acl_manager") as mock_mgr,
        ):
            mock_mgr.list_integration_acl_rules = AsyncMock(return_value=[raw_rule])
            mock_mgr._connection.site = "default"
            result = await acl_tools.list_integration_acl_rules(site_id=None)

        assert result["rules"][0]["raw"]["api_key"] == "***REDACTED***"

    @pytest.mark.asyncio
    async def test_error_logs_omit_tracebacks_and_private_text(self, caplog):
        from unifi_network_mcp.tools.acl import list_integration_acl_rules

        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.list_integration_acl_rules = AsyncMock(side_effect=RuntimeError("secret detail"))
            with caplog.at_level(logging.ERROR):
                result = await list_integration_acl_rules(site_id=None)

        assert result["success"] is False
        assert all(record.exc_info is None for record in caplog.records)
        assert "secret detail" not in caplog.text
        assert "RuntimeError" in caplog.text


class TestGetAclRuleOrderingTool:
    @pytest.mark.asyncio
    async def test_returns_ordering_from_manager(self):
        from unifi_network_mcp.tools.acl import get_acl_rule_ordering

        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.get_acl_rule_ordering = AsyncMock(return_value=CURRENT_ORDERING)

            result = await get_acl_rule_ordering(site_id=None)

        assert result["success"] is True
        assert result["ordered_acl_rule_ids"] == CURRENT_ORDERING
        mock_mgr.get_acl_rule_ordering.assert_awaited_once_with(site_id=None)

    @pytest.mark.asyncio
    async def test_typed_transport_errors_surface_their_fixed_text(self):
        from unifi_core.exceptions import UniFiAuthError
        from unifi_network_mcp.tools.acl import get_acl_rule_ordering

        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.get_acl_rule_ordering = AsyncMock(side_effect=UniFiAuthError("remediation text"))

            result = await get_acl_rule_ordering(site_id=None)

        assert result["success"] is False
        assert "remediation text" in result["error"]

    @pytest.mark.asyncio
    async def test_untyped_errors_stay_class_only(self):
        from unifi_network_mcp.tools.acl import get_acl_rule_ordering

        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.get_acl_rule_ordering = AsyncMock(side_effect=RuntimeError("secret detail"))

            result = await get_acl_rule_ordering(site_id=None)

        assert result["success"] is False
        assert "Failed to get ACL rule ordering" in result["error"]
        assert "secret detail" not in result["error"]


class TestReorderAclRulesTool:
    @pytest.mark.asyncio
    async def test_empty_payload_refused_before_any_call(self):
        from unifi_network_mcp.tools.acl import reorder_acl_rules

        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            result = await reorder_acl_rules(ordered_acl_rule_ids=[], confirm=True)

        assert result["success"] is False
        assert "non-empty list" in result["error"]
        mock_mgr.get_acl_rule_ordering.assert_not_called()
        mock_mgr.reorder_acl_rules.assert_not_called()

    @pytest.mark.asyncio
    async def test_duplicate_ids_refused_before_any_call(self):
        from unifi_network_mcp.tools.acl import reorder_acl_rules

        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            result = await reorder_acl_rules(
                ordered_acl_rule_ids=[CURRENT_ORDERING[0], CURRENT_ORDERING[0]], confirm=True
            )

        assert result["success"] is False
        assert "duplicate" in result["error"]
        mock_mgr.reorder_acl_rules.assert_not_called()

    @pytest.mark.asyncio
    async def test_preview_does_not_apply(self):
        from unifi_network_mcp.tools.acl import reorder_acl_rules

        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.get_acl_rule_ordering = AsyncMock(return_value=CURRENT_ORDERING)
            mock_mgr._connection.site = "default"

            result = await reorder_acl_rules(ordered_acl_rule_ids=copy.deepcopy(REVERSED_ORDERING), confirm=False)

        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["preview"]["proposed"]["orderedAclRuleIds"] == REVERSED_ORDERING
        mock_mgr.reorder_acl_rules.assert_not_called()

    @pytest.mark.asyncio
    async def test_confirm_applies_reorder(self):
        from unifi_network_mcp.tools.acl import reorder_acl_rules

        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.reorder_acl_rules = AsyncMock(return_value=REVERSED_ORDERING)

            result = await reorder_acl_rules(ordered_acl_rule_ids=copy.deepcopy(REVERSED_ORDERING), confirm=True)

        assert result["success"] is True
        assert result["ordered_acl_rule_ids"] == REVERSED_ORDERING
        # Confirm goes straight to the manager; the manager owns the fresh
        # ordering read and the multiset revalidation.
        mock_mgr.get_acl_rule_ordering.assert_not_called()
        mock_mgr.reorder_acl_rules.assert_awaited_once_with(REVERSED_ORDERING, site_id=None)

    @pytest.mark.asyncio
    async def test_manager_stale_set_refusal_surfaces(self):
        from unifi_network_mcp.tools.acl import reorder_acl_rules

        refusal = (
            "Reorder payload must preserve the exact current ACL rule ID set. "
            "Missing: 11111111-1111-1111-1111-111111111111; unexpected: none"
        )
        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.reorder_acl_rules = AsyncMock(side_effect=ValueError(refusal))

            result = await reorder_acl_rules(ordered_acl_rule_ids=copy.deepcopy(REVERSED_ORDERING), confirm=True)

        assert result["success"] is False
        assert "must preserve the exact current ACL rule ID set" in result["error"]


class TestIntegrationAclRuleModel:
    def test_integration_acl_rule_normalization(self):
        from unifi_core.network.models.acl_ordering import (
            MUTABLE_FIELDS,
            READ_ONLY_FIELDS,
            integration_acl_rule_from_controller,
        )

        rule = integration_acl_rule_from_controller(SAMPLE_RULES_PAGE["data"][0])
        assert rule.id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert rule.name == "Block guest"
        assert rule.index == 2000
        assert rule.action == "BLOCK"
        assert rule.network_id_filter == {"type": "ANY"}
        assert rule.raw is not None and set(rule.raw.keys()) == {"metadata"}
        # Read-only domain: nothing is mutable, the Integration UUID is the
        # only controller-assigned field.
        assert MUTABLE_FIELDS == frozenset()
        assert "id" in READ_ONLY_FIELDS

    def test_rule_without_an_id_is_refused(self):
        from unifi_core.network.models.acl_ordering import integration_acl_rule_from_controller

        with pytest.raises(ValueError, match="without an id"):
            integration_acl_rule_from_controller({"name": "Block guest"})


class TestAclOrderingManager:
    """Test AclManager Integration API request construction."""

    def _manager(self, auth):
        from unifi_core.network.managers.acl_manager import AclManager

        connection = MagicMock()
        connection.site = "default"
        connection.host = "192.0.2.10"
        connection.port = 443
        connection.tls_env_prefix = None
        return AclManager(connection, auth)

    @staticmethod
    def _page(payload, offset=0, total=None):
        page = MagicMock()
        page.status = 200
        page.json = AsyncMock(return_value=payload)
        return page

    def _session_with_responses(self, auth, payloads):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(side_effect=[self._page(payload) for payload in payloads])
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        session = AsyncMock()
        session.request = MagicMock(return_value=mock_ctx)
        session.close = AsyncMock()
        auth.get_api_key_session.return_value = session
        return session

    def _session_with_response(self, auth, payload):
        return self._session_with_responses(auth, [payload])

    @pytest.mark.asyncio
    async def test_missing_api_key_fails_before_any_request(self):
        from unifi_core.exceptions import UniFiAuthError

        manager = self._manager(auth=None)

        with pytest.raises(UniFiAuthError) as exc_info:
            await manager.get_acl_rule_ordering()

        message = str(exc_info.value)
        assert "requires a UniFi API key" in message
        assert "Control Plane -> Integrations" in message

    def test_reorder_rejects_empty_and_duplicate_payloads(self):
        from unifi_core.network.managers.acl_manager import AclManager

        with pytest.raises(ValueError):
            AclManager._normalise_ordered_acl_rule_ids([])
        with pytest.raises(ValueError):
            AclManager._normalise_ordered_acl_rule_ids([CURRENT_ORDERING[0], CURRENT_ORDERING[0]])
        assert AclManager._normalise_ordered_acl_rule_ids(CURRENT_ORDERING) == CURRENT_ORDERING

    @pytest.mark.asyncio
    async def test_get_sends_ordering_path_and_returns_ids(self):
        from unifi_core.auth import UniFiAuth

        auth = MagicMock(spec=UniFiAuth)
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock()
        manager = self._manager(auth)
        manager._get_integration_site_id = AsyncMock(return_value="site-uuid")
        session = self._session_with_response(auth, {"orderedAclRuleIds": CURRENT_ORDERING})

        result = await manager.get_acl_rule_ordering()

        assert result == CURRENT_ORDERING
        method, url = session.request.call_args.args
        assert method == "GET"
        assert url.endswith("/proxy/network/integration/v1/sites/site-uuid/acl-rules/ordering")
        assert session.request.call_args.kwargs["allow_redirects"] is False
        session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reorder_fresh_reads_then_puts_exact_body(self):
        from unifi_core.auth import UniFiAuth

        auth = MagicMock(spec=UniFiAuth)
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock()
        manager = self._manager(auth)
        manager._get_integration_site_id = AsyncMock(return_value="site-uuid")
        session = self._session_with_responses(
            auth,
            [
                {"orderedAclRuleIds": CURRENT_ORDERING},
                {"orderedAclRuleIds": REVERSED_ORDERING},
            ],
        )

        result = await manager.reorder_acl_rules(REVERSED_ORDERING)

        assert result == REVERSED_ORDERING
        assert session.request.call_count == 2
        first_method, first_url = session.request.call_args_list[0].args
        second_method, second_url = session.request.call_args_list[1].args
        assert first_method == "GET" and second_method == "PUT"
        assert first_url == second_url
        assert session.request.call_args_list[1].kwargs["json"] == {"orderedAclRuleIds": REVERSED_ORDERING}

    @pytest.mark.asyncio
    async def test_reorder_refuses_a_stale_set_after_the_fresh_read(self):
        from unifi_core.auth import UniFiAuth

        auth = MagicMock(spec=UniFiAuth)
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock()
        manager = self._manager(auth)
        manager._get_integration_site_id = AsyncMock(return_value="site-uuid")
        # The controller lost a rule between preview and confirm; the payload
        # still lists all three, so the fresh multiset check must refuse it.
        session = self._session_with_responses(
            auth,
            [{"orderedAclRuleIds": CURRENT_ORDERING[:2]}],
        )

        with pytest.raises(ValueError) as exc_info:
            await manager.reorder_acl_rules(REVERSED_ORDERING)

        message = str(exc_info.value)
        assert "must preserve the exact current ACL rule ID set" in message
        assert CURRENT_ORDERING[2] in message
        # Only the fresh GET happened; the PUT was never sent.
        assert session.request.call_count == 1
        assert session.request.call_args.args[0] == "GET"

    @pytest.mark.asyncio
    async def test_reorder_refuses_a_partial_payload_after_the_fresh_read(self):
        from unifi_core.auth import UniFiAuth

        auth = MagicMock(spec=UniFiAuth)
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock()
        manager = self._manager(auth)
        manager._get_integration_site_id = AsyncMock(return_value="site-uuid")
        session = self._session_with_responses(
            auth,
            [{"orderedAclRuleIds": CURRENT_ORDERING}],
        )

        with pytest.raises(ValueError) as exc_info:
            await manager.reorder_acl_rules([RULE_ID])

        assert "must preserve the exact current ACL rule ID set" in str(exc_info.value)
        assert session.request.call_count == 1

    @pytest.mark.asyncio
    async def test_list_integration_acl_rules_requests_the_list_path(self):
        from unifi_core.auth import UniFiAuth

        auth = MagicMock(spec=UniFiAuth)
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock()
        manager = self._manager(auth)
        manager._get_integration_site_id = AsyncMock(return_value="site-uuid")
        session = self._session_with_response(auth, SAMPLE_RULES_PAGE)

        result = await manager.list_integration_acl_rules()

        assert len(result) == 1
        assert result[0]["id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        method, url = session.request.call_args.args
        assert method == "GET"
        assert url.endswith("/proxy/network/integration/v1/sites/site-uuid/acl-rules")
        params = session.request.call_args.kwargs["params"]
        assert params == {"limit": "200", "offset": "0"}

    @pytest.mark.asyncio
    async def test_list_integration_acl_rules_paginates_until_total_count(self):
        from unifi_core.auth import UniFiAuth

        auth = MagicMock(spec=UniFiAuth)
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock()
        manager = self._manager(auth)
        manager._get_integration_site_id = AsyncMock(return_value="site-uuid")
        page_one = {"data": [{"id": "rule-one"}], "limit": 200, "offset": 0, "totalCount": 2}
        page_two = {"data": [{"id": "rule-two"}], "limit": 200, "offset": 1, "totalCount": 2}
        session = self._session_with_responses(auth, [page_one, page_two])

        result = await manager.list_integration_acl_rules()

        assert [rule["id"] for rule in result] == ["rule-one", "rule-two"]
        assert session.request.call_count == 2
        assert session.request.call_args_list[1].kwargs["params"] == {"limit": "200", "offset": "1"}

    @pytest.mark.asyncio
    async def test_malformed_ordering_response_raises(self):
        from unifi_core.auth import UniFiAuth
        from unifi_core.exceptions import UniFiMalformedResponseError

        auth = MagicMock(spec=UniFiAuth)
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock()
        manager = self._manager(auth)
        manager._get_integration_site_id = AsyncMock(return_value="site-uuid")
        self._session_with_response(auth, {"unexpected": True})

        with pytest.raises(UniFiMalformedResponseError) as exc_info:
            await manager.get_acl_rule_ordering()

        assert "invalid ACL rule ordering response" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_empty_2xx_body_raises_a_typed_error(self):
        from unifi_core.auth import UniFiAuth
        from unifi_core.exceptions import UniFiMalformedResponseError

        auth = MagicMock(spec=UniFiAuth)
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock()
        manager = self._manager(auth)
        manager._get_integration_site_id = AsyncMock(return_value="site-uuid")
        page = self._page({})
        page.json = AsyncMock(side_effect=ValueError("not json"))
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=page)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        session = AsyncMock()
        session.request = MagicMock(return_value=mock_ctx)
        session.close = AsyncMock()
        auth.get_api_key_session.return_value = session

        with pytest.raises(UniFiMalformedResponseError) as exc_info:
            await manager.get_acl_rule_ordering()

        assert "was not a JSON object" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_null_put_acknowledgement_returns_requested_ordering(self):
        from unifi_core.auth import UniFiAuth

        auth = MagicMock(spec=UniFiAuth)
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock()
        manager = self._manager(auth)
        manager._get_integration_site_id = AsyncMock(return_value="site-uuid")
        self._session_with_responses(
            auth,
            [{"orderedAclRuleIds": CURRENT_ORDERING}, None],
        )

        result = await manager.reorder_acl_rules(CURRENT_ORDERING)

        assert result == CURRENT_ORDERING

    @pytest.mark.asyncio
    async def test_empty_204_put_acknowledgement_returns_requested_ordering(self):
        from unifi_core.auth import UniFiAuth

        auth = MagicMock(spec=UniFiAuth)
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock()
        manager = self._manager(auth)
        manager._get_integration_site_id = AsyncMock(return_value="site-uuid")
        first = self._page({"orderedAclRuleIds": CURRENT_ORDERING})
        second = self._page({})
        second.status = 204
        second.json = AsyncMock(side_effect=ValueError("no content"))
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(side_effect=[first, second])
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        session = AsyncMock()
        session.request = MagicMock(return_value=mock_ctx)
        session.close = AsyncMock()
        auth.get_api_key_session.return_value = session

        result = await manager.reorder_acl_rules(CURRENT_ORDERING)

        assert result == CURRENT_ORDERING

    @pytest.mark.asyncio
    async def test_null_list_body_is_not_an_empty_success(self):
        from unifi_core.auth import UniFiAuth
        from unifi_core.exceptions import UniFiMalformedResponseError

        auth = MagicMock(spec=UniFiAuth)
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock()
        manager = self._manager(auth)
        manager._get_integration_site_id = AsyncMock(return_value="site-uuid")
        self._session_with_response(auth, None)

        with pytest.raises(UniFiMalformedResponseError) as exc_info:
            await manager.list_integration_acl_rules()

        assert "invalid ACL rule list response" in str(exc_info.value)


class TestAclOrderingRegistration:
    def test_tools_are_registered_with_correct_annotations(self):
        import json
        from pathlib import Path

        manifest_path = Path(__file__).resolve().parents[2] / "src" / "unifi_network_mcp" / "tools_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        tools = {tool["name"]: tool for tool in manifest["tools"]}

        assert "unifi_get_acl_rule_ordering" in tools
        assert "unifi_reorder_acl_rules" in tools
        assert "unifi_list_integration_acl_rules" in tools
        for name in ("unifi_get_acl_rule_ordering", "unifi_list_integration_acl_rules"):
            annotations = tools[name]["annotations"]
            assert annotations["readOnlyHint"] is True
            assert annotations["idempotentHint"] is True
            assert annotations["openWorldHint"] is False
        reorder_annotations = tools["unifi_reorder_acl_rules"]["annotations"]
        assert reorder_annotations["readOnlyHint"] is False
        assert reorder_annotations["destructiveHint"] is False
        assert reorder_annotations["idempotentHint"] is True
        assert reorder_annotations["openWorldHint"] is False

    def test_reorder_policy_gate_denies_update(self, monkeypatch):
        from unifi_core.policy_gate import PolicyGateChecker
        from unifi_network_mcp.categories import NETWORK_CATEGORY_MAP

        checker = PolicyGateChecker("network", NETWORK_CATEGORY_MAP)
        monkeypatch.setenv("UNIFI_POLICY_NETWORK_ACL_RULES_UPDATE", "false")
        assert checker.check("acl", "update") is False
        assert "UNIFI_POLICY_NETWORK_ACL_RULES_UPDATE" in checker.denial_message("acl", "update")
