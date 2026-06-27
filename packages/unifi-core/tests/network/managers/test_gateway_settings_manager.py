"""Gateway (USG) settings manager — fetch-merge-put + persistence verification."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.network.managers.gateway_settings_manager import (
    GatewaySettingsManager,
    _unpersisted_fields,
)


def _make_connection():
    """Connection mock whose cache always misses, so each fetch hits request()."""
    conn = MagicMock()
    conn.site = "default"
    conn.request = AsyncMock()
    conn.get_cached = MagicMock(return_value=None)
    conn._update_cache = MagicMock()
    conn._invalidate_cache = MagicMock()
    conn.ensure_connected = AsyncMock(return_value=True)
    return conn


def _usg(**overrides):
    base = {
        "_id": "usg1",
        "key": "usg",
        "upnp_enabled": False,
        "tcp_established_timeout": 7440,
        "dns_verification": {
            "setting_preference": "auto",
            "primary_dns_server": "1.1.1.1",
            "secondary_dns_server": "8.8.8.8",
            "domain": "ui.com",
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# get_gateway_settings
# ---------------------------------------------------------------------------


async def test_get_gateway_settings_unwraps_list():
    conn = _make_connection()
    mgr = GatewaySettingsManager(conn)
    conn.request.return_value = [_usg()]
    out = await mgr.get_gateway_settings()
    assert out["key"] == "usg"
    assert conn.request.call_args[0][0].path == "/get/setting/usg"


async def test_get_gateway_settings_empty():
    conn = _make_connection()
    mgr = GatewaySettingsManager(conn)
    conn.request.return_value = []
    assert await mgr.get_gateway_settings() == {}


# ---------------------------------------------------------------------------
# update_gateway_settings
# ---------------------------------------------------------------------------


async def test_update_succeeds_when_persisted():
    conn = _make_connection()
    mgr = GatewaySettingsManager(conn)
    conn.request.side_effect = [[_usg()], {}, [_usg(upnp_enabled=True)]]
    ok, err = await mgr.update_gateway_settings({"upnp_enabled": True})
    assert ok is True
    assert err is None
    # PUT sends the full merged object to /set/setting/usg
    put_call = conn.request.call_args_list[1][0][0]
    assert put_call.method == "put"
    assert put_call.path == "/set/setting/usg"


async def test_update_fails_when_not_persisted():
    conn = _make_connection()
    mgr = GatewaySettingsManager(conn)
    conn.request.side_effect = [[_usg()], {}, [_usg()]]  # post == pre
    ok, err = await mgr.update_gateway_settings({"upnp_enabled": True})
    assert ok is False
    assert err is not None and "upnp_enabled" in err


async def test_update_deep_merges_nested_without_wiping_siblings():
    """Maintainer's key requirement: a nested-field update must not wipe the
    sibling keys of dns_verification."""
    conn = _make_connection()
    mgr = GatewaySettingsManager(conn)
    captured = {}

    async def _request(req):
        if req.method == "put":
            captured["data"] = req.data
            return {}
        # GET: pre (before PUT) then post (reflects the merge)
        if captured.get("data"):
            return [
                _usg(
                    dns_verification={
                        "setting_preference": "auto",
                        "primary_dns_server": "9.9.9.9",
                        "secondary_dns_server": "8.8.8.8",
                        "domain": "ui.com",
                    }
                )
            ]
        return [_usg()]

    conn.request.side_effect = _request
    ok, err = await mgr.update_gateway_settings({"dns_verification": {"primary_dns_server": "9.9.9.9"}})
    assert ok is True, err
    sent = captured["data"]["dns_verification"]
    assert sent["primary_dns_server"] == "9.9.9.9"  # changed
    assert sent["secondary_dns_server"] == "8.8.8.8"  # sibling preserved
    assert sent["domain"] == "ui.com"  # sibling preserved
    assert sent["setting_preference"] == "auto"  # sibling preserved
    # the section discriminator is included on the PUT
    assert captured["data"]["key"] == "usg"


async def test_empty_update_is_noop():
    conn = _make_connection()
    mgr = GatewaySettingsManager(conn)
    ok, err = await mgr.update_gateway_settings({})
    assert ok is True
    assert err is None
    conn.request.assert_not_called()


async def test_update_nested_subkey_noop_is_flagged_not_persisted():
    """Per-leaf verify for nested objects: a controller that no-ops the requested
    dns_verification sub-key (while normalizing an untouched sibling) must be
    caught, not falsely reported persisted just because the sub-object moved."""
    conn = _make_connection()
    mgr = GatewaySettingsManager(conn)
    pre = _usg()  # dns_verification.primary_dns_server == "1.1.1.1"
    post = _usg(
        dns_verification={
            "setting_preference": "manual",  # controller normalized a SIBLING
            "primary_dns_server": "1.1.1.1",  # requested 9.9.9.9 but NOT applied
            "secondary_dns_server": "8.8.8.8",
            "domain": "ui.com",
        }
    )
    conn.request.side_effect = [[pre], {}, [post]]
    ok, err = await mgr.update_gateway_settings({"dns_verification": {"primary_dns_server": "9.9.9.9"}})
    assert ok is False
    assert err is not None and "dns_verification.primary_dns_server" in err


async def test_update_rejects_non_dict_nested_field():
    """A non-dict dns_verification would clobber the nested object via deep_merge —
    reject before any controller call."""
    conn = _make_connection()
    mgr = GatewaySettingsManager(conn)
    ok, err = await mgr.update_gateway_settings({"dns_verification": "evil"})
    assert ok is False
    assert err is not None and "dns_verification must be an object" in err
    conn.request.assert_not_called()


async def test_update_raises_on_connection_failure():
    conn = _make_connection()
    conn.ensure_connected = AsyncMock(return_value=False)
    mgr = GatewaySettingsManager(conn)
    with pytest.raises(ConnectionError):
        await mgr.update_gateway_settings({"upnp_enabled": True})


def test_unpersisted_helper():
    assert _unpersisted_fields({"a": 1}, {"a": 1}, {"a": 2}) == ["a"]
    assert _unpersisted_fields({"a": 1}, {"a": 2}, {"a": 2}) == []
    assert _unpersisted_fields({"a": 1}, {"a": 1}, {"a": 1}) == []
    # nested: requested leaf no-op'd while sibling moved -> flagged by leaf path
    before = {"dns": {"a": "1", "b": "x"}}
    after = {"dns": {"a": "1", "b": "y"}}  # 'a' (requested) unchanged, 'b' moved
    assert _unpersisted_fields(before, after, {"dns": {"a": "2"}}) == ["dns.a"]
