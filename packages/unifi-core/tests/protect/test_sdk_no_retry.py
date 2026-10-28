"""Protect requests are sent once: a resent mutation repeats work the NVR may still be doing."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from uiprotect.api import ProtectApiClient
from uiprotect.exceptions import NvrError
from unifi_core.protect.managers import connection_manager as module


@pytest.mark.asyncio
async def test_connection_manager_builds_the_sdk_client_without_retries(monkeypatch):
    client = MagicMock()
    client.update = AsyncMock()
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(module, "ProtectApiClient", factory)

    manager = module.ProtectConnectionManager(host="controller.invalid", username="test", password="test")
    await manager._connect_once()

    assert factory.call_args.kwargs["max_retries"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["delete", "patch", "post"])
@pytest.mark.parametrize("status", [500, 504])
async def test_failed_mutation_is_sent_once(method, status):
    client = ProtectApiClient(
        "controller.invalid",
        443,
        "fixture-user",
        "fixture-password",
        store_sessions=False,
        max_retries=module.SDK_MAX_RETRIES,
    )
    response = MagicMock(status=status, reason="Internal Server Error", headers={})
    response.json = AsyncMock(return_value={"error": "timeout"})
    sent = AsyncMock(return_value=response)
    client._paced_request = sent  # type: ignore[method-assign]
    try:
        with pytest.raises(NvrError):
            await client.api_request_raw("face-groups/group", method=method, require_auth=False)
    finally:
        await client.close_session()

    assert sent.await_count == 1
