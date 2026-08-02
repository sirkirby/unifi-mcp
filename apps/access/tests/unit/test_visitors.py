"""Tests for the Access Developer API VisitorManager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.access.managers.visitor_manager import VisitorManager
from unifi_core.exceptions import UniFiAuthError, UniFiConnectionError, UniFiNotFoundError


@pytest.fixture
def cm_api() -> MagicMock:
    cm = MagicMock(spec=AccessConnectionManager)
    cm.has_api_key = True
    cm.has_api_client = True
    cm.developer_request = AsyncMock()
    return cm


@pytest.fixture
def visitor_mgr(cm_api: MagicMock) -> VisitorManager:
    return VisitorManager(cm_api)


class TestListVisitors:
    @pytest.mark.asyncio
    async def test_list_visitors_paginates_developer_api(self, visitor_mgr, cm_api):
        first_page = [{"id": f"vis-{i}"} for i in range(100)]
        cm_api.developer_request.side_effect = [first_page, [{"id": "vis-100"}]]

        result = await visitor_mgr.list_visitors()

        assert len(result) == 101
        assert result[-1]["id"] == "vis-100"
        assert cm_api.developer_request.await_args_list == [
            call(
                "GET",
                "visitors",
                operation="List visitors",
                params={"page_num": 1, "page_size": 100},
            ),
            call(
                "GET",
                "visitors",
                operation="List visitors",
                params={"page_num": 2, "page_size": 100},
            ),
        ]

    @pytest.mark.asyncio
    async def test_list_visitors_requires_api_key_without_proxy_fallback(self, visitor_mgr, cm_api):
        cm_api.has_api_key = False

        with pytest.raises(UniFiAuthError, match="UNIFI_ACCESS_API_KEY"):
            await visitor_mgr.list_visitors()

        cm_api.developer_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_list_visitors_rejects_unexpected_shape(self, visitor_mgr, cm_api):
        cm_api.developer_request.return_value = {"items": []}

        with pytest.raises(UniFiConnectionError, match="unexpected Access API response shape"):
            await visitor_mgr.list_visitors()


class TestGetVisitor:
    @pytest.mark.asyncio
    async def test_get_visitor_success(self, visitor_mgr, cm_api):
        expected = {"id": "vis-1", "first_name": "John", "last_name": "Doe", "status": 6}
        cm_api.developer_request.return_value = expected

        result = await visitor_mgr.get_visitor("vis-1")

        assert result == expected
        cm_api.developer_request.assert_awaited_once_with(
            "GET",
            "visitors/vis-1",
            operation="Get visitor",
        )

    @pytest.mark.asyncio
    async def test_get_visitor_empty_id(self, visitor_mgr):
        with pytest.raises(ValueError, match="visitor_id is required"):
            await visitor_mgr.get_visitor("")

    @pytest.mark.asyncio
    async def test_get_visitor_maps_developer_not_found(self, visitor_mgr, cm_api):
        cm_api.developer_request.side_effect = UniFiConnectionError(
            "Get visitor failed: HTTP 404 GET /api/v1/developer/visitors/missing"
        )

        with pytest.raises(UniFiNotFoundError, match="visitor 'missing' not found"):
            await visitor_mgr.get_visitor("missing")


class TestCreateVisitor:
    @pytest.mark.asyncio
    async def test_create_visitor_preview_uses_stable_fields(self, visitor_mgr):
        preview = await visitor_mgr.create_visitor(
            name="Jane Doe",
            access_start="2026-03-17T09:00:00Z",
            access_end="2026-03-17T17:00:00Z",
            email="jane@example.com",
            company="Example Co",
        )

        assert preview["visitor_data"] == {
            "name": "Jane Doe",
            "access_start": "2026-03-17T09:00:00Z",
            "access_end": "2026-03-17T17:00:00Z",
            "email": "jane@example.com",
            "company": "Example Co",
        }
        assert preview["proposed_changes"]["action"] == "create"

    @pytest.mark.asyncio
    async def test_create_visitor_rejects_partial_explicit_name(self, visitor_mgr):
        with pytest.raises(ValueError, match="first_name and last_name must be provided together"):
            await visitor_mgr.create_visitor(
                name="Jane Doe",
                first_name="Jane",
                access_start="2026-03-17T09:00:00Z",
                access_end="2026-03-17T17:00:00Z",
            )

    @pytest.mark.asyncio
    async def test_create_visitor_requires_timezone(self, visitor_mgr):
        with pytest.raises(ValueError, match="valid_from must include a timezone"):
            await visitor_mgr.create_visitor(
                name="Jane Doe",
                access_start="2026-03-17T09:00:00",
                access_end="2026-03-17T17:00:00Z",
            )

    @pytest.mark.asyncio
    async def test_create_visitor_accepts_canonical_time_fields(self, visitor_mgr):
        preview = await visitor_mgr.create_visitor(
            name="Jane Doe",
            valid_from="2026-03-17T09:00:00Z",
            valid_until="2026-03-17T17:00:00Z",
        )

        assert preview["proposed_changes"]["valid_from"] == "2026-03-17T09:00:00Z"
        assert preview["proposed_changes"]["valid_until"] == "2026-03-17T17:00:00Z"

    @pytest.mark.asyncio
    async def test_create_visitor_requires_end_after_start(self, visitor_mgr):
        with pytest.raises(ValueError, match="access_end must be after access_start"):
            await visitor_mgr.create_visitor(
                name="Jane Doe",
                access_start="2026-03-17T17:00:00Z",
                access_end="2026-03-17T09:00:00Z",
            )


class TestApplyCreateVisitor:
    @pytest.mark.asyncio
    async def test_apply_create_translates_to_developer_payload(self, visitor_mgr, cm_api):
        cm_api.developer_request.return_value = {"id": "vis-new", "first_name": "Jane", "last_name": "Doe"}

        result = await visitor_mgr.apply_create_visitor(
            name="Display Name",
            first_name="Jane",
            last_name="Doe",
            access_start="2026-03-17T09:00:00Z",
            access_end="2026-03-17T17:00:00Z",
            email="jane@example.com",
            phone="+15551234567",
            company="Example Co",
            visit_reason="Business",
            remarks="Disposable test",
        )

        assert result["result"] == "success"
        assert result["data"]["id"] == "vis-new"
        cm_api.developer_request.assert_awaited_once_with(
            "POST",
            "visitors",
            operation="Create visitor",
            json={
                "first_name": "Jane",
                "last_name": "Doe",
                "start_time": 1773738000,
                "end_time": 1773766800,
                "email": "jane@example.com",
                "mobile_phone": "+15551234567",
                "company": "Example Co",
                "visit_reason": "Business",
                "remarks": "Disposable test",
            },
        )

    @pytest.mark.asyncio
    async def test_apply_create_splits_display_name(self, visitor_mgr, cm_api):
        cm_api.developer_request.return_value = {"id": "vis-new"}

        await visitor_mgr.apply_create_visitor(
            name="Jane Doe",
            access_start="2026-03-17T09:00:00Z",
            access_end="2026-03-17T17:00:00Z",
        )

        payload = cm_api.developer_request.await_args.kwargs["json"]
        assert payload["first_name"] == "Jane"
        assert payload["last_name"] == "Doe"


class TestDeleteVisitor:
    @pytest.mark.asyncio
    async def test_delete_visitor_preview_composes_name(self, visitor_mgr, cm_api):
        current = {"id": "vis-1", "first_name": "John", "last_name": "Doe", "status": 6}
        cm_api.developer_request.return_value = current

        preview = await visitor_mgr.delete_visitor("vis-1")

        assert preview["visitor_id"] == "vis-1"
        assert preview["visitor_name"] == "John Doe"
        assert preview["current_state"] == current
        assert preview["proposed_changes"]["action"] == "delete"

    @pytest.mark.asyncio
    async def test_delete_visitor_empty_id(self, visitor_mgr):
        with pytest.raises(ValueError, match="visitor_id is required"):
            await visitor_mgr.delete_visitor("")


class TestApplyDeleteVisitor:
    @pytest.mark.asyncio
    async def test_apply_delete_success(self, visitor_mgr, cm_api):
        cm_api.developer_request.return_value = None

        result = await visitor_mgr.apply_delete_visitor("vis-1")

        assert result == {"visitor_id": "vis-1", "action": "delete", "result": "success"}
        cm_api.developer_request.assert_awaited_once_with(
            "DELETE",
            "visitors/vis-1",
            operation="Delete visitor",
        )

    @pytest.mark.asyncio
    async def test_apply_delete_maps_developer_not_found(self, visitor_mgr, cm_api):
        cm_api.developer_request.side_effect = UniFiConnectionError(
            "Delete visitor failed: Access API code CODE_NOT_FOUND"
        )

        with pytest.raises(UniFiNotFoundError, match="visitor 'missing' not found"):
            await visitor_mgr.apply_delete_visitor("missing")
