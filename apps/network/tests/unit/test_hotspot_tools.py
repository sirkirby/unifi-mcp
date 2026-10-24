"""Tests for unifi_list_vouchers and unifi_get_voucher_details tools.

Covers issue #737:
- Default no-argument compatibility (exact legacy envelope)
- Parameter bounds validation (limit ge=1 le=1000, offset ge=0)
- Case-insensitive substring search over note and code
- Pagination with limit and offset (including offsets beyond total)
- Strict allowlist fields projection (and explicit rejection of unknown fields)
- Deterministic ordering preservation
- Response redaction governed by policy
"""

import inspect
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import TypeAdapter

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")

SAMPLE_VOUCHERS = [
    {
        "_id": "60a8b3c4d5e6f7a8b9c0d101",
        "code": "ABC12345",
        "note": "Conference Guest 1",
        "quota": 1,
        "used": 0,
        "duration": 1440,
        "status": "VALID_ONE",
        "create_time": 1700000000,
        "qos_overwrite": True,
        "qos_rate_max_up": 5000,
        "qos_rate_max_down": 10000,
        "qos_usage_quota": 500,
    },
    {
        "_id": "60a8b3c4d5e6f7a8b9c0d102",
        "code": "DEF67890",
        "note": "VIP Lounge Access",
        "quota": 0,
        "used": 2,
        "duration": 2880,
        "status": "VALID_MULTI",
        "create_time": 1700000100,
        "qos_overwrite": False,
    },
    {
        "_id": "60a8b3c4d5e6f7a8b9c0d103",
        "code": "GHI11111",
        "note": None,
        "quota": 5,
        "used": 1,
        "duration": 60,
        "status": "USED_MULTIPLE",
        "create_time": 1700000200,
        "qos_overwrite": False,
    },
    {
        "_id": "60a8b3c4d5e6f7a8b9c0d104",
        "code": "JKL22222",
        "note": "Conference Speaker",
        "quota": 1,
        "used": 1,
        "duration": 720,
        "status": "USED_EXPIRED",
        "create_time": 1700000300,
        "qos_overwrite": False,
    },
]


def _mock_conn():
    conn = MagicMock()
    conn.site = "default"
    return conn


# ---------------------------------------------------------------------------
# 1. Compatibility Tests (No-Argument Preservation)
# ---------------------------------------------------------------------------


TIED_VOUCHERS = [
    {"_id": "v_alpha", "code": "ALPHA", "create_time": 1700000000},
    {"_id": "v_beta", "code": "BETA", "create_time": 1700000000},
    {"_id": "v_newest", "code": "NEWEST", "create_time": 1700000500},
]

DIGIT_VOUCHERS = [
    {"_id": "v1", "code": "1234567890", "note": "Guest Wifi", "create_time": 1700000000},
    {"_id": "v2", "code": "9876543210", "note": "Staff-Only", "create_time": 1700000100},
]


async def _list(vouchers, **kwargs):
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_vouchers = AsyncMock(return_value=list(vouchers))
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        return await list_vouchers(**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"limit": None, "offset": 0, "search": None, "fields": None},
        {"search": "   "},
    ],
)
async def test_list_vouchers_unshaped_calls_preserve_legacy_envelope(kwargs):
    """No-arg, explicit-default and whitespace-search calls keep the exact legacy envelope in controller order."""
    result = await _list(SAMPLE_VOUCHERS, **kwargs)

    assert result["success"] is True
    assert result["site"] == "default"
    assert result["count"] == 4
    # Crucial: NO shaping metadata present in unshaped responses
    assert set(result.keys()) == {"success", "site", "count", "vouchers"}
    assert [v["id"] for v in result["vouchers"]] == [v["_id"] for v in SAMPLE_VOUCHERS]


# Shaped calls sort created_at desc (ties by id desc); total_count reflects the filtered set.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "vouchers,kwargs,total,codes",
    [
        (SAMPLE_VOUCHERS, {"search": "abc"}, 1, ["ABC12345"]),
        (SAMPLE_VOUCHERS, {"search": "conference"}, 2, ["JKL22222", "ABC12345"]),
        # "VALID_ONE" is a status, but no code or note contains "VALID"
        (SAMPLE_VOUCHERS, {"search": "VALID"}, 0, []),
        (SAMPLE_VOUCHERS, {"search": "nonexistent-substring"}, 0, []),
        (SAMPLE_VOUCHERS, {"limit": 1, "offset": 0}, 4, ["JKL22222"]),
        (SAMPLE_VOUCHERS, {"limit": 1000, "offset": 0}, 4, ["JKL22222", "GHI11111", "DEF67890", "ABC12345"]),
        (SAMPLE_VOUCHERS, {"limit": 2, "offset": 0}, 4, ["JKL22222", "GHI11111"]),
        (SAMPLE_VOUCHERS, {"limit": 2, "offset": 2}, 4, ["DEF67890", "ABC12345"]),
        (SAMPLE_VOUCHERS, {"offset": 10, "limit": 5}, 4, []),
        ([], {"limit": 10}, 0, []),
        (TIED_VOUCHERS, {"limit": 10}, 3, ["NEWEST", "BETA", "ALPHA"]),
        (DIGIT_VOUCHERS, {"search": "12345-67890"}, 1, ["1234567890"]),
        (DIGIT_VOUCHERS, {"search": "12345-6"}, 1, ["1234567890"]),
        (DIGIT_VOUCHERS, {"search": "Staff-Only"}, 1, ["9876543210"]),
        # Arbitrary punctuation is not generalized
        (DIGIT_VOUCHERS, {"search": "123.456"}, 0, []),
        (SAMPLE_VOUCHERS, {"search": "conference", "limit": 1, "offset": 1, "fields": "code,note"}, 2, ["ABC12345"]),
    ],
)
async def test_list_vouchers_shaping(vouchers, kwargs, total, codes):
    result = await _list(vouchers, **kwargs)

    assert result["success"] is True
    assert result["total_count"] == total
    assert result["count"] == len(codes)
    assert "total" not in result
    assert "returned_count" not in result
    assert [v["code"] for v in result["vouchers"]] == codes
    for key in ("limit", "offset"):
        if key in kwargs:
            assert result[key] == kwargs[key]
    if "fields" in kwargs:
        for voucher in result["vouchers"]:
            assert set(voucher) == set(kwargs["fields"].split(","))


# ---------------------------------------------------------------------------
# 2. Schema and Bounds Validation Tests
# ---------------------------------------------------------------------------


def test_list_vouchers_parameter_schema_bounds():
    """Verify limit and offset parameter schema bounds via TypeAdapter."""
    from unifi_network_mcp.tools.hotspot import list_vouchers

    parameters = inspect.signature(list_vouchers).parameters
    limit_adapter = TypeAdapter(parameters["limit"].annotation)
    offset_adapter = TypeAdapter(parameters["offset"].annotation)

    schema_limit = limit_adapter.json_schema()
    # Annotated[Optional[int], Field(ge=1, le=1000)]
    assert schema_limit.get("minimum") == 1 or any(s.get("minimum") == 1 for s in schema_limit.get("anyOf", []))
    assert schema_limit.get("maximum") == 1000 or any(s.get("maximum") == 1000 for s in schema_limit.get("anyOf", []))

    schema_offset = offset_adapter.json_schema()
    assert schema_offset.get("minimum") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_limit", [0, -1, -50, 1001, 5000, True, False])
async def test_list_vouchers_rejects_invalid_limit(invalid_limit):
    """Explicitly reject limit out of [1, 1000] bounds or boolean."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        result = await list_vouchers(limit=invalid_limit)

    assert result["success"] is False
    assert "Invalid limit" in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_offset", [-1, -10, True, False])
async def test_list_vouchers_rejects_invalid_offset(invalid_offset):
    """Explicitly reject offset < 0 or boolean."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        result = await list_vouchers(offset=invalid_offset)

    assert result["success"] is False
    assert "Invalid offset" in result["error"]


# ---------------------------------------------------------------------------
# 3. Search Filter Tests (Narrow Substring on Code and Note)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 4. Paging and Ordering Tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 5. Fields Projection Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_vouchers_fields_projection_valid():
    """Projection returns only requested fields from allowlist."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_vouchers = AsyncMock(return_value=list(SAMPLE_VOUCHERS))
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        result = await list_vouchers(fields="code, note, quota")

    assert result["success"] is True
    assert result["total_count"] == 4
    for voucher in result["vouchers"]:
        # Only requested fields should be present
        assert set(voucher.keys()).issubset({"code", "note", "quota"})
    assert result["vouchers"][0]["code"] == "JKL22222"
    assert result["vouchers"][0]["note"] == "Conference Speaker"
    assert result["vouchers"][0]["quota"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_fields",
    [
        "unknown_field",
        "code,bogus",
        "password",
        "_id",  # Controller internal key is _id, but response field is id
        "secret,token",
    ],
)
async def test_list_vouchers_rejects_unknown_projection_fields(invalid_fields):
    """Explicitly reject unknown or non-allowlisted projection fields."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        result = await list_vouchers(fields=invalid_fields)

    assert result["success"] is False
    assert "Unknown projection fields" in result["error"]
    assert "Allowed fields" in result["error"]


@pytest.mark.asyncio
async def test_list_vouchers_rejects_non_string_fields():
    """Projection rejects non-string field types (list, tuple, int, etc.)."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        res_list = await list_vouchers(fields=["id", "code"])
        assert res_list["success"] is False
        assert "Invalid fields parameter type" in res_list["error"]

        res_int = await list_vouchers(fields=123)
        assert res_int["success"] is False
        assert "Invalid fields parameter type" in res_int["error"]


# ---------------------------------------------------------------------------
# 6. Combined Search, Paging, and Projection
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 7. Redaction Integration Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("redact", [True, False])
async def test_list_vouchers_respects_redaction_policy(monkeypatch, redact):
    """Verify response redaction follows server-owned policy without caller bypass."""
    monkeypatch.setenv("UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS", str(redact).lower())

    vouchers_with_secret = [
        {
            "_id": "v1",
            "code": "ABC12345",
            "note": "Conference Guest",
        }
    ]

    with (
        patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm,
        patch("unifi_core.network.read_views.voucher_from_controller") as mock_vfc,
    ):
        mock_hm.get_vouchers = AsyncMock(return_value=vouchers_with_secret)
        mock_hm._connection = _mock_conn()

        fake_shaped = MagicMock()
        fake_shaped.model_dump.return_value = {
            "id": "v1",
            "code": "ABC12345",
            "secret": "top-secret-val",
        }
        mock_vfc.return_value = fake_shaped

        from unifi_network_mcp.tools.hotspot import list_vouchers

        result = await list_vouchers()

    assert result["success"] is True
    voucher = result["vouchers"][0]
    if redact:
        assert voucher["secret"] == "***REDACTED***"
    else:
        assert voucher["secret"] == "top-secret-val"


# ---------------------------------------------------------------------------
# 8. Error Handling Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_vouchers_manager_exception_returns_error_dict():
    """Exceptions from hotspot_manager are caught, logged, and return error dict."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_vouchers = AsyncMock(side_effect=RuntimeError("Controller connection lost"))
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        result = await list_vouchers()

    assert result["success"] is False
    assert "Failed to list vouchers" in result["error"]
    assert "Controller connection lost" in result["error"]


@pytest.mark.asyncio
async def test_get_voucher_details_returns_voucher():
    """get_voucher_details returns shaped voucher from controller."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_voucher_details = AsyncMock(
            return_value={
                "_id": "v1",
                "code": "ABC12345",
                "duration": 1440,
            }
        )
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import get_voucher_details

        result = await get_voucher_details("v1")

    assert result["success"] is True
    assert result["voucher"]["code"] == "ABC12345"
    assert result["voucher"]["duration"] == 1440
