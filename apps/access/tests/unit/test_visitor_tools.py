"""Tool-layer tests for the Access Developer API visitor family."""

from __future__ import annotations

import inspect
import os
from unittest.mock import AsyncMock, patch

import pytest

from unifi_core.access.models.visitors import MUTABLE_FIELDS

os.environ.setdefault("UNIFI_ACCESS_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_ACCESS_USERNAME", "test")
os.environ.setdefault("UNIFI_ACCESS_PASSWORD", "test")


@pytest.mark.asyncio
async def test_list_visitors_normalizes_developer_api_fields() -> None:
    with patch("unifi_access_mcp.tools.visitors.visitor_manager") as manager:
        manager.list_visitors = AsyncMock(
            return_value=[
                {
                    "id": "visitor-uuid",
                    "first_name": "Smoke",
                    "last_name": "Visitor",
                    "start_time": 1773738000,
                    "end_time": 1773766800,
                    "status": 6,
                    "mobile_phone": "+15551234567",
                    "company": "Example Co",
                    "nfc_cards": [],
                    "license_plates": [],
                }
            ]
        )
        from unifi_access_mcp.tools.visitors import access_list_visitors

        result = await access_list_visitors()

    assert result == {
        "success": True,
        "data": {
            "visitors": [
                {
                    "id": "visitor-uuid",
                    "status": "active",
                    "credential_count": 0,
                    "name": "Smoke Visitor",
                    "first_name": "Smoke",
                    "last_name": "Visitor",
                    "valid_from": "2026-03-17T09:00:00Z",
                    "valid_until": "2026-03-17T17:00:00Z",
                    "phone": "+15551234567",
                    "company": "Example Co",
                }
            ],
            "count": 1,
        },
    }


@pytest.mark.asyncio
async def test_create_visitor_accepts_canonical_fields_and_previews() -> None:
    with patch("unifi_access_mcp.tools.visitors.visitor_manager") as manager:
        manager.create_visitor = AsyncMock(
            return_value={
                "proposed_changes": {
                    "action": "create",
                    "name": "Smoke Visitor",
                    "access_start": "2026-03-17T09:00:00Z",
                    "access_end": "2026-03-17T17:00:00Z",
                    "company": "Example Co",
                }
            }
        )
        from unifi_access_mcp.tools.visitors import access_create_visitor

        result = await access_create_visitor(
            name="Smoke Visitor",
            valid_from="2026-03-17T09:00:00Z",
            valid_until="2026-03-17T17:00:00Z",
            company="Example Co",
            confirm=False,
        )

    assert result["success"] is True
    assert result["requires_confirmation"] is True
    assert result["action"] == "create"
    manager.create_visitor.assert_awaited_once_with(
        name="Smoke Visitor",
        access_start="2026-03-17T09:00:00Z",
        access_end="2026-03-17T17:00:00Z",
        company="Example Co",
    )


@pytest.mark.asyncio
async def test_create_visitor_confirm_forwards_developer_metadata() -> None:
    with patch("unifi_access_mcp.tools.visitors.visitor_manager") as manager:
        manager.apply_create_visitor = AsyncMock(
            return_value={"action": "create", "result": "success", "data": {"id": "visitor-uuid"}}
        )
        from unifi_access_mcp.tools.visitors import access_create_visitor

        result = await access_create_visitor(
            name="Smoke Visitor",
            access_start="2026-03-17T09:00:00Z",
            access_end="2026-03-17T17:00:00Z",
            first_name="Smoke",
            last_name="Visitor",
            email="smoke@example.com",
            phone="+15551234567",
            company="Example Co",
            visit_reason="Business",
            remarks="Disposable",
            confirm=True,
        )

    assert result["success"] is True
    assert result["data"]["data"]["id"] == "visitor-uuid"
    manager.apply_create_visitor.assert_awaited_once_with(
        name="Smoke Visitor",
        access_start="2026-03-17T09:00:00Z",
        access_end="2026-03-17T17:00:00Z",
        first_name="Smoke",
        last_name="Visitor",
        email="smoke@example.com",
        phone="+15551234567",
        company="Example Co",
        visit_reason="Business",
        remarks="Disposable",
    )


@pytest.mark.asyncio
async def test_create_visitor_rejects_conflicting_time_aliases() -> None:
    from unifi_access_mcp.tools.visitors import access_create_visitor

    result = await access_create_visitor(
        name="Smoke Visitor",
        access_start="2026-03-17T09:00:00Z",
        valid_from="2026-03-17T10:00:00Z",
        access_end="2026-03-17T17:00:00Z",
    )

    assert result["success"] is False
    assert "must match" in result["error"]


def test_every_mutable_visitor_field_is_a_create_parameter() -> None:
    from unifi_access_mcp.tools.visitors import access_create_visitor

    create_params = set(inspect.signature(access_create_visitor).parameters)
    assert MUTABLE_FIELDS <= create_params
