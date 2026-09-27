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


@pytest.mark.asyncio
async def test_list_vouchers_no_args_preserves_exact_legacy_envelope():
    """No-argument call must preserve exact legacy response envelope: success, site, count, vouchers."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_vouchers = AsyncMock(return_value=list(SAMPLE_VOUCHERS))
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        result = await list_vouchers()

    assert result["success"] is True
    assert result["site"] == "default"
    assert result["count"] == 4
    assert len(result["vouchers"]) == 4

    # Crucial: NO shaping metadata present in unshaped/no-arg response
    assert "total_count" not in result
    assert "total" not in result
    assert "returned_count" not in result
    assert "limit" not in result
    assert "offset" not in result
    assert set(result.keys()) == {"success", "site", "count", "vouchers"}


@pytest.mark.asyncio
async def test_list_vouchers_explicit_defaults_preserves_exact_legacy_envelope():
    """Explicitly passing default values preserves exact legacy envelope."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_vouchers = AsyncMock(return_value=list(SAMPLE_VOUCHERS))
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        result = await list_vouchers(limit=None, offset=0, search=None, fields=None)

    assert result["success"] is True
    assert set(result.keys()) == {"success", "site", "count", "vouchers"}
    assert result["count"] == 4


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


@pytest.mark.asyncio
async def test_list_vouchers_accepts_valid_boundary_values():
    """Accept valid boundary values limit=1, limit=1000, offset=0."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_vouchers = AsyncMock(return_value=list(SAMPLE_VOUCHERS))
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        res1 = await list_vouchers(limit=1, offset=0)
        assert res1["success"] is True
        assert res1["count"] == 1
        assert res1["total_count"] == 4
        assert res1["limit"] == 1
        assert "total" not in res1
        assert "returned_count" not in res1

        res1000 = await list_vouchers(limit=1000, offset=0)
        assert res1000["success"] is True
        assert res1000["count"] == 4
        assert res1000["total_count"] == 4
        assert res1000["limit"] == 1000


# ---------------------------------------------------------------------------
# 3. Search Filter Tests (Narrow Substring on Code and Note)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_vouchers_search_by_code_case_insensitive():
    """Search matches code substring case-insensitively."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_vouchers = AsyncMock(return_value=list(SAMPLE_VOUCHERS))
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        result = await list_vouchers(search="abc")

    assert result["success"] is True
    assert result["total_count"] == 1
    assert result["count"] == 1
    assert "total" not in result
    assert "returned_count" not in result
    assert result["vouchers"][0]["code"] == "ABC12345"


@pytest.mark.asyncio
async def test_list_vouchers_search_by_note_case_insensitive():
    """Search matches note substring case-insensitively."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_vouchers = AsyncMock(return_value=list(SAMPLE_VOUCHERS))
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        result = await list_vouchers(search="conference")

    assert result["success"] is True
    assert result["total_count"] == 2
    assert result["count"] == 2
    matched_codes = {v["code"] for v in result["vouchers"]}
    assert matched_codes == {"ABC12345", "JKL22222"}


@pytest.mark.asyncio
async def test_list_vouchers_search_narrow_does_not_match_other_fields():
    """Search does not match fields outside code and note (e.g. status or duration)."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_vouchers = AsyncMock(return_value=list(SAMPLE_VOUCHERS))
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        # "VALID_ONE" is a status, but no code or note contains "VALID"
        result = await list_vouchers(search="VALID")

    assert result["success"] is True
    assert result["total_count"] == 0
    assert result["vouchers"] == []


@pytest.mark.asyncio
async def test_list_vouchers_search_no_match_returns_empty_well_defined():
    """Sparse / no-match search returns well-defined empty page with total_count=0."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_vouchers = AsyncMock(return_value=list(SAMPLE_VOUCHERS))
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        result = await list_vouchers(search="nonexistent-substring")

    assert result["success"] is True
    assert result["total_count"] == 0
    assert result["count"] == 0
    assert "total" not in result
    assert "returned_count" not in result
    assert result["vouchers"] == []


@pytest.mark.asyncio
async def test_list_vouchers_whitespace_search_ignored():
    """Whitespace-only search string is ignored and preserves all vouchers."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_vouchers = AsyncMock(return_value=list(SAMPLE_VOUCHERS))
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        result = await list_vouchers(search="   ")

    # Treated as no shaping requested
    assert result["success"] is True
    assert result["count"] == 4
    assert len(result["vouchers"]) == 4


# ---------------------------------------------------------------------------
# 4. Paging and Ordering Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_vouchers_paging_limit_and_offset():
    """Limit and offset paginate correctly with total_count and count metadata."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_vouchers = AsyncMock(return_value=list(SAMPLE_VOUCHERS))
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        page1 = await list_vouchers(limit=2, offset=0)
        assert page1["success"] is True
        assert page1["total_count"] == 4
        assert page1["count"] == 2
        assert page1["limit"] == 2
        assert page1["offset"] == 0
        assert "total" not in page1
        assert "returned_count" not in page1
        assert [v["code"] for v in page1["vouchers"]] == ["JKL22222", "GHI11111"]

        page2 = await list_vouchers(limit=2, offset=2)
        assert page2["success"] is True
        assert page2["total_count"] == 4
        assert page2["count"] == 2
        assert page2["offset"] == 2
        assert [v["code"] for v in page2["vouchers"]] == ["DEF67890", "ABC12345"]


@pytest.mark.asyncio
async def test_list_vouchers_offset_beyond_total_is_well_defined():
    """Offset beyond total returns empty vouchers list with well-defined metadata."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_vouchers = AsyncMock(return_value=list(SAMPLE_VOUCHERS))
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        result = await list_vouchers(offset=10, limit=5)

    assert result["success"] is True
    assert result["total_count"] == 4
    assert result["count"] == 0
    assert result["vouchers"] == []
    assert result["offset"] == 10
    assert result["limit"] == 5
    assert "total" not in result
    assert "returned_count" not in result


@pytest.mark.asyncio
async def test_list_vouchers_empty_controller_collection():
    """Empty controller response returns well-defined empty page."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_vouchers = AsyncMock(return_value=[])
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        result = await list_vouchers(limit=10)

    assert result["success"] is True
    assert result["total_count"] == 0
    assert result["count"] == 0
    assert result["vouchers"] == []


@pytest.mark.asyncio
async def test_list_vouchers_paging_preserves_deterministic_order():
    """Shaped calls sort created_at desc; unpaged preserves controller order."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_vouchers = AsyncMock(return_value=list(SAMPLE_VOUCHERS))
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        paged_items = []
        for i in range(4):
            page = await list_vouchers(limit=1, offset=i)
            paged_items.extend(page["vouchers"])

        unpaged = await list_vouchers()
        # Unpaged preserves controller order
        assert [v["id"] for v in unpaged["vouchers"]] == [
            "60a8b3c4d5e6f7a8b9c0d101",
            "60a8b3c4d5e6f7a8b9c0d102",
            "60a8b3c4d5e6f7a8b9c0d103",
            "60a8b3c4d5e6f7a8b9c0d104",
        ]
        # Paged items follow deterministic created_at desc order
        assert [v["id"] for v in paged_items] == [
            "60a8b3c4d5e6f7a8b9c0d104",  # create_time: 1700000300
            "60a8b3c4d5e6f7a8b9c0d103",  # create_time: 1700000200
            "60a8b3c4d5e6f7a8b9c0d102",  # create_time: 1700000100
            "60a8b3c4d5e6f7a8b9c0d101",  # create_time: 1700000000
        ]


@pytest.mark.asyncio
async def test_list_vouchers_paging_deterministic_tie_break():
    """Ties in created_at are deterministically broken by id descending."""
    tied_vouchers = [
        {"_id": "v_alpha", "code": "ALPHA", "create_time": 1700000000},
        {"_id": "v_beta", "code": "BETA", "create_time": 1700000000},
        {"_id": "v_newest", "code": "NEWEST", "create_time": 1700000500},
    ]
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_vouchers = AsyncMock(return_value=tied_vouchers)
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        # Unpaged preserves controller order
        unpaged = await list_vouchers()
        assert [v["id"] for v in unpaged["vouchers"]] == ["v_alpha", "v_beta", "v_newest"]

        # Paged sorts created_at desc with id desc tie break
        paged = await list_vouchers(limit=10)
        assert [v["id"] for v in paged["vouchers"]] == ["v_newest", "v_beta", "v_alpha"]


@pytest.mark.asyncio
async def test_list_vouchers_ui_hyphenated_digit_search():
    """Search matches UI hyphenated digit codes against stored digit codes."""
    digit_vouchers = [
        {"_id": "v1", "code": "1234567890", "note": "Guest Wifi", "create_time": 1700000000},
        {"_id": "v2", "code": "9876543210", "note": "Staff-Only", "create_time": 1700000100},
    ]
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_vouchers = AsyncMock(return_value=digit_vouchers)
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        # Full UI hyphenated search
        res1 = await list_vouchers(search="12345-67890")
        assert res1["count"] == 1
        assert res1["vouchers"][0]["code"] == "1234567890"

        # Partial UI hyphenated search
        res2 = await list_vouchers(search="12345-6")
        assert res2["count"] == 1
        assert res2["vouchers"][0]["code"] == "1234567890"

        # Exact hyphenated note match
        res3 = await list_vouchers(search="Staff-Only")
        assert res3["count"] == 1
        assert res3["vouchers"][0]["code"] == "9876543210"

        # Arbitrary punctuation is not generalized
        res4 = await list_vouchers(search="123.456")
        assert res4["count"] == 0


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


@pytest.mark.asyncio
async def test_list_vouchers_combined_search_paging_and_projection():
    """Search filters first, total_count reflects filtered count, paging and projection apply."""
    with patch("unifi_network_mcp.tools.hotspot.hotspot_manager") as mock_hm:
        mock_hm.get_vouchers = AsyncMock(return_value=list(SAMPLE_VOUCHERS))
        mock_hm._connection = _mock_conn()

        from unifi_network_mcp.tools.hotspot import list_vouchers

        # "conference" matches 2 vouchers: JKL22222 (1700000300) and ABC12345 (1700000000).
        # Sorted created_at desc: JKL22222 is index 0, ABC12345 is index 1.
        # offset=1, limit=1 returns ABC12345.
        result = await list_vouchers(search="conference", limit=1, offset=1, fields="code,note")

    assert result["success"] is True
    assert result["total_count"] == 2
    assert result["count"] == 1
    assert result["limit"] == 1
    assert result["offset"] == 1
    assert "total" not in result
    assert "returned_count" not in result
    assert len(result["vouchers"]) == 1
    assert result["vouchers"][0]["code"] == "ABC12345"
    assert result["vouchers"][0]["note"] == "Conference Guest 1"
    assert set(result["vouchers"][0].keys()) == {"code", "note"}


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
