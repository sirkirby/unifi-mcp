"""Plan image fetch: strict address, size cap, type and magic-byte checks."""

import base64

import pytest
from unifi_core.exceptions import UniFiMalformedResponseError, UniFiNotFoundError, UniFiValidationError
from unifi_core.innerspace.managers.connection_manager import (
    ASSET_CEILING_BYTES,
    INTERNAL_PROJECT_PATH,
    SYSTEM_PATH,
    InnerSpaceHttpError,
)
from unifi_core.innerspace.managers.floor_plan_manager import PLAN_ASSET_MAX_BYTES, InnerSpaceFloorPlanManager

from tests.innerspace.helpers import PLAN_A, PLANS_PATH, PROJECT_PATH, jpeg_bytes, load, png_bytes, with_unit

PNG = {"Content-Type": "image/png"}
# The console stores a plan's image under a folder id of its own, not the plan id.
_FOLDER_A = "00000000-0000-4000-8000-000000000034"
_FILE = "00000000-0000-4000-8000-000000000014"
_BASE = "/proxy/innerspace/integration/v1/assets"
ASSET_A = f"{_BASE}/{_FOLDER_A}/{_FILE}.png"
ASSET_B = f"{_BASE}/00000000-0000-4000-8000-000000000035/00000000-0000-4000-8000-000000000021.png"


_KEEP = object()


def _script(console, image_url=_KEEP, unit="metric", map_url=None, drop_map=False):
    """Script a plan-asset read; ``image_url`` replaces Plan A's address in both the row and its map."""
    plans, project = load("v1_floor_plans.json"), load("v1_project.json")
    (map_a,) = [s for s in project["data"]["shapes"] if s["type"] == "map" and s["planId"] == PLAN_A]
    if image_url is not _KEEP:
        plans["floor_plans"][0]["image_url"] = map_a["urlImage"] = image_url
    if map_url is not None:
        map_a["urlImage"] = map_url
    if drop_map:
        project["data"]["shapes"].remove(map_a)
    console.reply("GET", SYSTEM_PATH, load("system.json"))
    console.reply("GET", PLANS_PATH, plans)
    console.reply("GET", PROJECT_PATH, project)
    console.reply("GET", INTERNAL_PROJECT_PATH, with_unit(unit))


def _asset_calls(console):
    return [r for r in console.requests if "/assets/" in r.path]


async def test_metadata_without_image_requests_no_asset(connected, console):
    _script(console)
    result = await InnerSpaceFloorPlanManager(connected).get_plan_asset(PLAN_A)
    assert result == {
        "filename": "00000000-0000-4000-8000-000000000014.png",
        "content_type": "image/png",
        "width_px": 1000.0,
        "height_px": 800.0,
        "scale_per_unit": 100.0,
        "image_scale": 1.0,
        "image_offset": (0.0, 0.0),
        "unit": "metric",
    }
    assert _asset_calls(console) == []


async def test_include_image_returns_base64(connected, console):
    _script(console)
    body = png_bytes()
    console.reply("GET", ASSET_A, body_bytes=body, headers=PNG)
    result = await InnerSpaceFloorPlanManager(connected).get_plan_asset(PLAN_A, include_image=True)
    assert base64.b64decode(result["image_base64"]) == body
    assert result["content_type"] == "image/png"
    assert len(_asset_calls(console)) == 1


async def test_jpeg_plan(connected, console):
    url = ASSET_A.replace(".png", ".jpg")
    _script(console, image_url=url)
    console.reply("GET", url, body_bytes=jpeg_bytes(), headers={"Content-Type": "image/jpeg"})
    result = await InnerSpaceFloorPlanManager(connected).get_plan_asset(PLAN_A, include_image=True)
    assert (result["content_type"], base64.b64decode(result["image_base64"])[:3]) == ("image/jpeg", b"\xff\xd8\xff")


async def test_folder_id_different_from_the_plan_id_is_fetched(connected, console):
    """The folder segment is the console's own id; it is never compared with the plan id."""
    assert _FOLDER_A != PLAN_A
    _script(console)
    console.reply("GET", ASSET_A, body_bytes=png_bytes(), headers=PNG)
    await InnerSpaceFloorPlanManager(connected).get_plan_asset(PLAN_A, include_image=True)
    assert [r.path for r in _asset_calls(console)] == [ASSET_A]


async def test_plan_a_read_never_fetches_plan_b_image(connected, console):
    """Only the requested plan's own row supplies the address."""
    _script(console)
    console.reply("GET", ASSET_A, body_bytes=png_bytes(), headers=PNG)
    console.reply("GET", ASSET_B, body_bytes=png_bytes(), headers=PNG)
    await InnerSpaceFloorPlanManager(connected).get_plan_asset(PLAN_A, include_image=True)
    assert [r.path for r in _asset_calls(console)] == [ASSET_A]


@pytest.mark.parametrize(
    "change",
    [{"map_url": ASSET_B}, {"drop_map": True}],
    ids=["map-names-another-image", "plan-without-map"],
)
async def test_address_must_equal_the_plans_map_image(connected, console, change):
    _script(console, **change)
    with pytest.raises(UniFiMalformedResponseError) as caught:
        await InnerSpaceFloorPlanManager(connected).get_plan_asset(PLAN_A, include_image=True)
    assert str(caught.value) == "get InnerSpace plan asset: the floor plan has no usable image address"
    assert _asset_calls(console) == []


async def test_scaled_plan_metadata_exposes_the_image_transform(connected, console):
    _script(console)
    result = await InnerSpaceFloorPlanManager(connected).get_plan_asset("00000000-0000-4000-8000-000000000004")
    assert (result["image_scale"], result["image_offset"]) == (1.784, (12.5, -7.5))


async def test_unknown_plan_is_not_found(connected, console):
    _script(console)
    with pytest.raises(UniFiNotFoundError) as caught:
        await InnerSpaceFloorPlanManager(connected).get_plan_asset("00000000-0000-4000-8000-000000009999")
    assert str(caught.value) == "get InnerSpace plan asset: no such floor plan"


@pytest.mark.parametrize(
    "url",
    [
        f"{_BASE}/{_FOLDER_A}/{_FILE}.PNG",
        f"{_BASE}/{_FOLDER_A}/{_FILE}.png?x=1",
        f"https://198.51.100.7{_BASE}/{_FOLDER_A}/{_FILE}.png",
        f"/{_BASE}/{_FOLDER_A}/{_FILE}.png",
        f"{_BASE}/{_FOLDER_A}/../{_FILE}.png",
        f"{_BASE}/{_FOLDER_A}/{_FILE}.svg",
        f"/proxy/innerspace/integration/v1/other/{_FOLDER_A}/{_FILE}.png",
        None,
        42,
    ],
)
async def test_unsafe_image_url_is_refused_without_a_request(connected, console, url):
    _script(console, image_url=url)
    with pytest.raises(UniFiMalformedResponseError):
        await InnerSpaceFloorPlanManager(connected).get_plan_asset(PLAN_A, include_image=True)
    assert _asset_calls(console) == []


@pytest.mark.parametrize(
    ("body", "headers"),
    [
        (png_bytes(), {"Content-Type": "text/html"}),
        (png_bytes(), {"Content-Type": "image/svg+xml"}),
        (png_bytes(), {}),
        (b"<html>not an image</html>", PNG),
        (jpeg_bytes(), PNG),
        (png_bytes(), {"Content-Type": "image/jpeg"}),
        (png_bytes(PLAN_ASSET_MAX_BYTES), PNG),
    ],
    ids=["html", "svg", "no-type", "wrong-magic", "jpeg-as-png", "type-differs-from-name", "oversize"],
)
async def test_asset_refusals(connected, console, body, headers):
    _script(console)
    console.reply("GET", ASSET_A, body_bytes=body, headers=headers)
    with pytest.raises(UniFiMalformedResponseError):
        await InnerSpaceFloorPlanManager(connected).get_plan_asset(PLAN_A, include_image=True)


async def test_asset_redirect_is_refused(connected, console):
    _script(console)
    console.redirect(ASSET_A, "https://198.51.100.7/x.png")
    with pytest.raises(InnerSpaceHttpError) as caught:
        await InnerSpaceFloorPlanManager(connected).get_plan_asset(PLAN_A, include_image=True)
    assert caught.value.status == 302
    assert "198.51.100.7" not in str(caught.value)
    assert [r.path for r in console.requests if "198.51.100.7" in r.path] == []


async def test_asset_cap_is_the_constant_and_under_the_ceiling():
    assert PLAN_ASSET_MAX_BYTES == 8_000_000
    assert PLAN_ASSET_MAX_BYTES < ASSET_CEILING_BYTES == 16_000_000


async def test_asset_stream_without_content_length_stops_at_the_cap(connected, console):
    """A chunked body of 64 MB is cut off once the cap is passed; the server sees the client leave."""
    _script(console)
    console.reply("GET", ASSET_A, headers=PNG, stream=(1000, 65_536))
    with pytest.raises(UniFiMalformedResponseError):
        await InnerSpaceFloorPlanManager(connected).get_plan_asset(PLAN_A, include_image=True)
    # Checked first so a refusal before the request fails here rather than waiting forever.
    assert len(_asset_calls(console)) == 1
    await console.stream_done.wait()
    assert console.streamed < 64_000_000


async def test_declared_oversize_is_refused_without_reading_a_body(connected, console):
    _script(console)
    console.reply("GET", ASSET_A, headers=PNG, declared=PLAN_ASSET_MAX_BYTES + 1)
    with pytest.raises(UniFiMalformedResponseError) as caught:
        await InnerSpaceFloorPlanManager(connected).get_plan_asset(PLAN_A, include_image=True)
    assert str(caught.value) == "get InnerSpace plan asset: the image is larger than the allowed size"
    assert len(_asset_calls(console)) == 1


async def test_jpeg_extension_plan(connected, console):
    url = ASSET_A.replace(".png", ".jpeg")
    _script(console, image_url=url)
    console.reply("GET", url, body_bytes=jpeg_bytes(), headers={"Content-Type": "image/jpeg"})
    result = await InnerSpaceFloorPlanManager(connected).get_plan_asset(PLAN_A, include_image=True)
    assert (result["filename"], result["content_type"]) == (f"{_FILE}.jpeg", "image/jpeg")


async def test_jpeg_extension_refuses_a_png_type(connected, console):
    url = ASSET_A.replace(".png", ".jpeg")
    _script(console, image_url=url)
    console.reply("GET", url, body_bytes=png_bytes(), headers=PNG)
    with pytest.raises(UniFiMalformedResponseError):
        await InnerSpaceFloorPlanManager(connected).get_plan_asset(PLAN_A, include_image=True)


async def test_request_bytes_clamps_to_the_ceiling_and_reports_oversize(connected, console):
    console.reply("GET", SYSTEM_PATH, load("system.json"))
    path = "/proxy/innerspace/integration/v1/assets/a/b"
    console.reply("GET", path, headers=PNG, stream=(300, 65_536))
    with pytest.raises(UniFiMalformedResponseError) as caught:
        await connected.request_bytes(path, operation="fetch", max_bytes=10**9, allowed_types=("image/png",))
    assert str(caught.value) == "fetch: the image is larger than the allowed size"


async def test_request_bytes_relogs_in_once_after_a_refused_session(connected, console):
    path = "/proxy/innerspace/integration/v1/assets/a/b"
    console.expire_session()
    console.reply("GET", path, body_bytes=png_bytes(), headers=PNG)
    body, content_type = await connected.request_bytes(
        path, operation="fetch", max_bytes=1000, allowed_types=("image/png",)
    )
    assert (body[:4], content_type) == (b"\x89PNG", "image/png")
    assert console.logins == 2
    assert len(console.calls("GET", path)) == 2


@pytest.mark.parametrize(
    ("status", "error", "text"),
    [
        (403, InnerSpaceHttpError, "fetch: the console answered HTTP 403 (errors.thing.failed)"),
        (404, InnerSpaceHttpError, "fetch: the console answered HTTP 404 (errors.thing.failed)"),
        (500, InnerSpaceHttpError, "fetch: the console answered HTTP 500 (errors.thing.failed)"),
    ],
)
async def test_request_bytes_maps_errors_like_request(connected, console, status, error, text):
    path = "/proxy/innerspace/integration/v1/assets/a/b"
    console.reply("GET", path, {"error": {"code": "errors.thing.failed", "message": "secret body text"}}, status=status)
    with pytest.raises(error) as caught:
        await connected.request_bytes(path, operation="fetch", max_bytes=1000, allowed_types=("image/png",))
    assert str(caught.value) == text


async def test_request_bytes_refuses_unsafe_path(connected, console):
    with pytest.raises(UniFiValidationError):
        await connected.request_bytes("/a/../b", operation="fetch", max_bytes=1, allowed_types=("image/png",))


async def test_json_body_over_the_cap_is_refused(connected, console, monkeypatch):
    monkeypatch.setattr("unifi_core.innerspace.managers.connection_manager._JSON_CEILING_BYTES", 2_000)
    console.reply("GET", SYSTEM_PATH, load("system.json"))
    plans = {"floor_plans": [{"name": "x" * 5000}]}
    console.reply("GET", PLANS_PATH, plans)
    await connected.request("GET", SYSTEM_PATH, operation="status")
    with pytest.raises(UniFiMalformedResponseError) as caught:
        await connected.request("GET", PLANS_PATH, operation="plans")
    assert str(caught.value) == "plans: the console returned a response larger than the allowed size"
