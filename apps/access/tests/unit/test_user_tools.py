"""access_list_users reads every user page and maps the Users application's fields."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("UNIFI_ACCESS_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_ACCESS_USERNAME", "test")
os.environ.setdefault("UNIFI_ACCESS_PASSWORD", "test")

ROW = {"unique_id": "u-1", "full_name": "Synthetic User", "status": "ACTIVE", "roles": [{"name": "Viewer"}]}


@pytest.mark.asyncio
@pytest.mark.parametrize(("args", "expected"), [({}, (False, None)), ({"limit": 30, "compact": True}, (True, 30))])
async def test_list_users_reads_every_page_through_the_manager(args, expected) -> None:
    with patch("unifi_access_mcp.tools.system.system_manager") as manager:
        manager.list_all_users = AsyncMock(return_value=[ROW])
        from unifi_access_mcp.tools.system import access_list_users

        result = await access_list_users(**args)

    compact, limit = expected
    manager.list_all_users.assert_awaited_once_with(compact=compact, limit=limit)
    assert result["data"] == {
        "users": [{"id": "u-1", "name": "Synthetic User", "status": "ACTIVE", "role": "Viewer"}],
        "count": 1,
    }
