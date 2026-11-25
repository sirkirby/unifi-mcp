"""The plan image resource: bytes and type, fixed errors, on-demand metadata."""

from __future__ import annotations

import asyncio
import base64
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.server.mcpserver.exceptions import ResourceError
from mcp.shared.exceptions import MCPError
from mcp.types import ReadResourceRequestParams

from unifi_core.exceptions import UniFiNotFoundError
from unifi_innerspace_mcp.resources import plan_image as resource_module
from unifi_innerspace_mcp.resources.uris import PLAN_IMAGE_URI_TEMPLATE, PLAN_JPEG_URI_TEMPLATE, plan_image_uri
from unifi_innerspace_mcp.runtime import server

PLAN = "00000000-0000-4000-8000-000000000003"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
METADATA = {"filename": "f.png", "content_type": "image/png", "width_px": 1000.0}


@pytest.fixture(autouse=True)
def registered():
    resource_module.register_plan_image_resource()


def _serve(monkeypatch, **asset_or_error):
    method = AsyncMock(**asset_or_error)
    monkeypatch.setattr(resource_module, "floor_plan_manager", SimpleNamespace(get_plan_asset=method))
    return method


async def _read(uri):
    (content,) = await server.read_resource(uri)
    return content


def test_uri_shape():
    assert PLAN_IMAGE_URI_TEMPLATE == "innerspace://plans/{plan_id}/image"
    assert PLAN_JPEG_URI_TEMPLATE == "innerspace://plans/{plan_id}/image.jpg"
    assert plan_image_uri(PLAN) == f"innerspace://plans/{PLAN}/image"
    assert plan_image_uri(PLAN, "image/jpeg") == f"innerspace://plans/{PLAN}/image.jpg"
    assert plan_image_uri(PLAN, "image/gif") is None


JPEG = b"\xff\xd8\xff" + b"\x00" * 16
JPEG_METADATA = {"filename": "f.jpg", "content_type": "image/jpeg", "width_px": 1000.0}


async def test_the_jpeg_resource_returns_a_jpeg_plan_with_its_type(monkeypatch):
    asset = {**JPEG_METADATA, "image_base64": base64.b64encode(JPEG).decode()}
    method = _serve(monkeypatch, return_value=asset)

    content = await _read(plan_image_uri(PLAN, "image/jpeg"))

    assert (content.content, content.mime_type) == (JPEG, "image/jpeg")
    method.assert_awaited_once_with(PLAN, include_image=True, image_type="image/jpeg")


async def test_each_resource_refuses_the_other_type_and_names_the_right_one(monkeypatch):
    png_method = _serve(monkeypatch, return_value=JPEG_METADATA)
    with pytest.raises(ResourceError) as png_read:
        await _read(plan_image_uri(PLAN))

    jpeg_method = _serve(monkeypatch, return_value=METADATA)
    with pytest.raises(ResourceError) as jpeg_read:
        await _read(plan_image_uri(PLAN, "image/jpeg"))

    assert str(png_read.value) == (
        "Failed to read InnerSpace plan image: the image is a JPEG; read innerspace://plans/{plan_id}/image.jpg"
    )
    assert str(jpeg_read.value) == (
        "Failed to read InnerSpace plan image: the image is a PNG; read innerspace://plans/{plan_id}/image"
    )
    png_method.assert_awaited_once_with(PLAN, include_image=True, image_type="image/png")
    jpeg_method.assert_awaited_once_with(PLAN, include_image=True, image_type="image/jpeg")


async def test_resource_returns_the_image_bytes_with_the_png_type(monkeypatch):
    asset = {**METADATA, "image_base64": base64.b64encode(PNG).decode()}
    method = _serve(monkeypatch, return_value=asset)

    content = await _read(plan_image_uri(PLAN))

    assert (content.content, content.mime_type) == (PNG, "image/png")
    method.assert_awaited_once_with(PLAN, include_image=True, image_type="image/png")


async def test_unknown_plan_is_a_fixed_error(monkeypatch, caplog):
    text = "get InnerSpace plan asset: no such floor plan"
    _serve(monkeypatch, side_effect=UniFiNotFoundError("floor plan", "InnerSpace", text))

    with caplog.at_level(logging.ERROR), pytest.raises(ResourceError) as raised:
        await _read(plan_image_uri(PLAN))

    assert text in str(raised.value)
    assert str(raised.value).startswith("Failed to read InnerSpace plan image: ")
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == [
        "Failed to read InnerSpace plan image: UniFiNotFoundError"
    ]


async def test_invalid_plan_id_is_a_fixed_error_that_does_not_echo_it(caplog):
    marker = "marker.value"
    with caplog.at_level(logging.DEBUG), pytest.raises(ResourceError) as raised:
        await _read(plan_image_uri(marker))

    assert str(raised.value) == "Failed to read InnerSpace plan image: invalid arguments"
    assert marker not in str(raised.value) + caplog.text


async def test_unreadable_metadata_is_a_fixed_error(monkeypatch, caplog):
    _serve(monkeypatch, return_value={"filename": "f.png"})

    with caplog.at_level(logging.ERROR), pytest.raises(ResourceError) as raised:
        await _read(plan_image_uri(PLAN))

    assert str(raised.value) == "Failed to read InnerSpace plan image: unexpected KeyError"


async def test_a_rejected_plan_id_stays_out_of_the_sdk_log(caplog):
    # Through the SDK's request handler, which logs a failed read with its URI.
    marker = "marker.value"
    params = ReadResourceRequestParams(uri=plan_image_uri(marker))

    with caplog.at_level(logging.DEBUG), pytest.raises(MCPError) as raised:
        await server._handle_read_resource(MagicMock(), params)

    assert raised.value.error.message == "Failed to read InnerSpace plan image: invalid arguments"
    assert "Resource 'innerspace://plans/{plan_id}/image' failed" in caplog.text
    assert marker not in caplog.text


@pytest.mark.parametrize(
    ("uri_template", "mime_type"), [(PLAN_IMAGE_URI_TEMPLATE, "image/png"), (PLAN_JPEG_URI_TEMPLATE, "image/jpeg")]
)
async def test_template_is_on_demand_with_no_subscription(uri_template, mime_type):
    (template,) = [t for t in await server.list_resource_templates() if t.uri_template == uri_template]

    assert template.mime_type == mime_type
    assert template.meta["io.unifi.updateMode"] == "on-demand"
    assert template.meta["io.unifi.protocolSubscribe"] is False
    assert template.meta["io.unifi.relatedTools"] == ["innerspace_get_plan_asset", "innerspace_list_floor_plans"]
    assert "InnerSpace tool family" in template.description


@pytest.mark.parametrize(
    "uri",
    [
        "innerspace://plans/MARK1/x/image",
        "innerspace://plans/..%2FMARK2/image",
        "innerspace://plans/MARK3/image/extra",
    ],
)
async def test_a_rejected_uri_never_reaches_a_log(caplog, uri):
    with caplog.at_level(logging.DEBUG), pytest.raises(MCPError):
        await server._handle_read_resource(None, ReadResourceRequestParams(uri=uri))

    seen = []
    for record in caplog.records:
        seen += [record.getMessage(), str(record.args), str(record.__dict__)]
    assert "MARK" not in "\n".join(seen)


@pytest.fixture
def gate(monkeypatch):
    from unifi_core.operation_gate import GateSettings, OperationGate

    gate = OperationGate(GateSettings(read_cap=1, direct_call_wait_seconds=0.05), name="innerspace")
    monkeypatch.setattr(resource_module, "get_operation_gate", lambda: gate)
    return gate


async def test_the_console_fetch_holds_a_read_slot_at_the_gate(monkeypatch, gate):
    """MCP resources are not tool calls, so this read takes its own slot."""
    slots = []

    async def get_plan_asset(plan_id, **_):
        slots.append(gate.snapshot()["reads_in_use"])
        return {**METADATA, "image_base64": base64.b64encode(PNG).decode()}

    monkeypatch.setattr(resource_module, "floor_plan_manager", SimpleNamespace(get_plan_asset=get_plan_asset))

    await _read(plan_image_uri(PLAN))

    assert slots == [1]
    assert gate.snapshot()["reads_in_use"] == 0


async def test_a_busy_gate_refuses_the_read_before_the_console_is_reached(monkeypatch, gate):
    method = _serve(monkeypatch, return_value=METADATA)

    # Another task holds the only read slot; this read waits its short budget, then is refused.
    held, release = asyncio.Event(), asyncio.Event()

    async def hold_the_slot():
        async with gate.read():
            held.set()
            await release.wait()

    holder = asyncio.create_task(hold_the_slot())
    await held.wait()
    try:
        with pytest.raises(ResourceError) as raised:
            await asyncio.wait_for(_read(plan_image_uri(PLAN)), timeout=5)
    finally:
        release.set()
        await holder

    assert str(raised.value).startswith("Failed to read InnerSpace plan image: ")
    method.assert_not_awaited()


async def test_no_gate_in_setup_mode_still_reads(monkeypatch):
    monkeypatch.setattr(resource_module, "get_operation_gate", lambda: None)
    asset = {**METADATA, "image_base64": base64.b64encode(PNG).decode()}
    _serve(monkeypatch, return_value=asset)

    content = await _read(plan_image_uri(PLAN))

    assert content.content == PNG


async def test_a_failed_fetch_gives_its_read_slot_back(monkeypatch, gate):
    _serve(monkeypatch, side_effect=UniFiNotFoundError("floor plan", "InnerSpace", "get InnerSpace plan asset: gone"))

    with pytest.raises(ResourceError):
        await _read(plan_image_uri(PLAN))

    assert gate.snapshot()["reads_in_use"] == 0


async def test_an_undecodable_image_is_a_fixed_error(monkeypatch):
    _serve(monkeypatch, return_value={**METADATA, "image_base64": "not base64!"})

    with pytest.raises(ResourceError) as raised:
        await _read(plan_image_uri(PLAN))

    assert str(raised.value) == "Failed to read InnerSpace plan image: the image could not be decoded"
