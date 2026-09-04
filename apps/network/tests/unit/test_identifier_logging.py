"""Tool error logging must not reintroduce private controller identifiers."""

import importlib
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["clients", "devices"])
async def test_detail_error_logs_do_not_include_private_exception(domain, monkeypatch, caplog):
    monkeypatch.setenv("UNIFI_HOST", "127.0.0.1")
    monkeypatch.setenv("UNIFI_USERNAME", "test")
    monkeypatch.setenv("UNIFI_PASSWORD", "test")
    from unifi_network_mcp import runtime

    singular = "client" if domain == "clients" else "device"
    private = "aa:bb:cc:11:22:33 private-owner password=do-not-log"
    manager = MagicMock()
    method = f"get_{singular}_details"
    setattr(manager, method, AsyncMock(side_effect=RuntimeError(private)))
    monkeypatch.setattr(runtime, f"{singular}_manager", manager)
    module = importlib.import_module(f"unifi_network_mcp.tools.{domain}")
    monkeypatch.setattr(module, f"{singular}_manager", manager)
    with caplog.at_level(logging.ERROR, logger=module.__name__):
        result = await getattr(module, method)("aa:bb:cc:11:22:33")
    assert result["success"] is False
    records = [record for record in caplog.records if record.name == module.__name__]
    assert records
    for record in records:
        assert record.exc_info is None
        for marker in ("aa:bb:cc:11:22:33", "private-owner", "do-not-log"):
            assert marker not in record.getMessage()
            assert marker not in repr(record.args)
    assert "RuntimeError" in caplog.text
