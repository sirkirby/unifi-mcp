"""Tests for listing and renaming a camera's crossing lines and smart-detect zones."""

import copy
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.managers.camera_manager import CameraManager


def _raw_camera() -> dict:
    return {
        "id": "cam-1",
        "name": "Front Door",
        "smartDetectLines": [
            {
                "id": 1,
                "name": "Driveway",
                "direction": "AB",
                "objectTypes": ["person", "vehicle"],
                "points": [[0.1, 0.2], [0.9, 0.8]],
                "sensitivity": 50,
            },
            {
                "id": 2,
                "name": "Walkway",
                "direction": "BA",
                "objectTypes": ["person"],
                "points": [[0.3, 0.3], [0.4, 0.9]],
                "sensitivity": 70,
            },
        ],
        "smartDetectZones": [
            {
                "id": 1,
                "name": "Porch",
                "objectTypes": ["person"],
                "points": [[0, 0], [1, 0], [1, 1], [0, 1]],
                "sensitivity": 60,
                "color": "#AB46BC",
            },
            {"id": 2, "name": "Lawn", "objectTypes": ["animal"], "points": [[0, 0], [1, 1], [0, 1]], "sensitivity": 40},
        ],
        "smartDetectLoiterZones": [
            {
                "id": 1,
                "name": "Gate",
                "objectTypes": ["person"],
                "points": [[0, 0], [1, 0], [1, 1]],
                "loiterTime": 10,
            }
        ],
        "motionZones": [{"id": 1, "name": "Default", "points": [[0, 0], [1, 1]]}],
    }


@pytest.fixture
def server():
    """Fake NVR: ``raw`` is what it holds, PATCH merges the body into it."""
    state = {"raw": _raw_camera(), "reads": 0}
    calls = []

    async def api_request(path, method="get", json=None, **kwargs):
        calls.append((path, method, copy.deepcopy(json)))
        if method == "get":
            state["reads"] += 1
            return copy.deepcopy(state["raw"])
        if method == "patch":
            state["raw"].update(copy.deepcopy(json))
            return {}
        raise AssertionError(f"unexpected {method}")

    cm = MagicMock()
    cm.client.bootstrap.cameras = {"cam-1": MagicMock()}
    cm.client.api_request = AsyncMock(side_effect=api_request)
    state["cm"] = cm
    state["calls"] = calls
    return state


def _patches(server):
    return [c for c in server["calls"] if c[1] == "patch"]


class TestListDetectionAreas:
    @pytest.mark.asyncio
    async def test_lists_lines_zones_and_loiter_zones(self, server):
        result = await CameraManager(server["cm"]).list_camera_detection_areas("cam-1")

        assert result["camera_id"] == "cam-1"
        assert result["camera_name"] == "Front Door"
        assert result["count"] == 5
        assert result["areas"] == [
            {"id": "1", "name": "Driveway", "kind": "line", "object_types": ["person", "vehicle"], "direction": "AB"},
            {"id": "2", "name": "Walkway", "kind": "line", "object_types": ["person"], "direction": "BA"},
            {"id": "1", "name": "Porch", "kind": "zone", "object_types": ["person"]},
            {"id": "2", "name": "Lawn", "kind": "zone", "object_types": ["animal"]},
            {"id": "1", "name": "Gate", "kind": "loiter_zone", "object_types": ["person"]},
        ]

    @pytest.mark.asyncio
    async def test_reads_the_nvr_not_the_bootstrap_cache(self, server):
        await CameraManager(server["cm"]).list_camera_detection_areas("cam-1")

        assert server["calls"] == [("cameras/cam-1", "get", None)]

    @pytest.mark.asyncio
    async def test_camera_without_areas_returns_empty_list(self, server):
        server["raw"] = {"id": "cam-1", "name": "Front Door"}

        result = await CameraManager(server["cm"]).list_camera_detection_areas("cam-1")

        assert result["areas"] == []
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_unknown_camera_raises_not_found_without_a_request(self, server):
        with pytest.raises(UniFiNotFoundError):
            await CameraManager(server["cm"]).list_camera_detection_areas("nope")

        server["cm"].client.api_request.assert_not_awaited()


class TestRawRead:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("response", [[], None, "text"])
    async def test_non_dict_response_raises(self, server, response):
        server["cm"].client.api_request = AsyncMock(return_value=response)

        with pytest.raises(RuntimeError, match="cam-1"):
            await CameraManager(server["cm"]).list_camera_detection_areas("cam-1")


class TestListTolerance:
    @pytest.mark.asyncio
    async def test_item_without_object_types_or_name(self, server):
        server["raw"]["smartDetectZones"] = [{"id": 9}]

        result = await CameraManager(server["cm"]).list_camera_detection_areas("cam-1")

        zone = next(a for a in result["areas"] if a["kind"] == "zone")
        assert zone == {"id": "9", "name": None, "kind": "zone", "object_types": []}


class TestRenamePreview:
    @pytest.mark.asyncio
    async def test_preview_reports_current_and_proposed_and_sends_no_patch(self, server):
        result = await CameraManager(server["cm"]).rename_camera_detection_area("cam-1", "line", "1", "Street")

        assert result == {
            "camera_id": "cam-1",
            "camera_name": "Front Door",
            "kind": "line",
            "area_id": "1",
            "current_name": "Driveway",
            "proposed_name": "Street",
        }
        assert _patches(server) == []
        assert server["raw"] == _raw_camera()

    @pytest.mark.asyncio
    async def test_preview_trims_the_proposed_name(self, server):
        result = await CameraManager(server["cm"]).rename_camera_detection_area("cam-1", "line", "1", "  Street  ")

        assert result["proposed_name"] == "Street"


class TestRenameRefusals:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["rename_camera_detection_area", "apply_rename_camera_detection_area"])
    @pytest.mark.parametrize(
        ("kind", "area_id", "new_name", "message"),
        [
            ("motion_zone", "1", "X", "kind"),
            ("line", "99", "X", "99"),
            ("line", "1", "", "blank"),
            ("line", "1", "   ", "blank"),
            ("line", "1", "walkway", "already"),
            ("line", "1", "  WALKWAY ", "already"),
            ("zone", "1", "lawn", "already"),
            ("loiter_zone", "7", "X", "7"),
        ],
    )
    async def test_refuses_before_any_write(self, server, method, kind, area_id, new_name, message):
        with pytest.raises(ValueError, match=message):
            await getattr(CameraManager(server["cm"]), method)("cam-1", kind, area_id, new_name)

        assert _patches(server) == []

    @pytest.mark.asyncio
    async def test_unknown_camera_raises_not_found(self, server):
        with pytest.raises(UniFiNotFoundError):
            await CameraManager(server["cm"]).apply_rename_camera_detection_area("nope", "line", "1", "X")

        server["cm"].client.api_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_same_name_in_another_kind_is_allowed(self, server):
        result = await CameraManager(server["cm"]).rename_camera_detection_area("cam-1", "line", "1", "Porch")

        assert result["proposed_name"] == "Porch"

    @pytest.mark.asyncio
    async def test_case_only_change_of_own_name_is_a_rename(self, server):
        result = await CameraManager(server["cm"]).apply_rename_camera_detection_area("cam-1", "line", "1", "driveway")

        assert result["changed"] is True
        assert server["raw"]["smartDetectLines"][0]["name"] == "driveway"


class TestRenameInputTolerance:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("new_name", ["Entry", "None"])
    async def test_sibling_with_null_name_does_not_crash_or_collide(self, server, new_name):
        server["raw"]["smartDetectZones"][1]["name"] = None

        result = await CameraManager(server["cm"]).rename_camera_detection_area("cam-1", "zone", "1", new_name)

        assert result["proposed_name"] == new_name

    @pytest.mark.asyncio
    @pytest.mark.parametrize("new_name", [None, 5, ["x"]])
    async def test_non_string_new_name_is_refused(self, server, new_name):
        with pytest.raises(ValueError, match="blank"):
            await CameraManager(server["cm"]).rename_camera_detection_area("cam-1", "line", "1", new_name)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["rename_camera_detection_area", "apply_rename_camera_detection_area"])
    async def test_duplicate_check_is_unicode_aware(self, server, method):
        server["raw"]["smartDetectZones"][1]["name"] = "STRASSE"

        with pytest.raises(ValueError, match="already"):
            await getattr(CameraManager(server["cm"]), method)("cam-1", "zone", "1", "straße")

        assert _patches(server) == []

    @pytest.mark.asyncio
    async def test_identical_name_is_a_noop_even_when_a_sibling_shares_it(self, server):
        server["raw"]["smartDetectZones"][0]["name"] = "Door"
        server["raw"]["smartDetectZones"][1]["name"] = "Door"
        manager = CameraManager(server["cm"])

        preview = await manager.rename_camera_detection_area("cam-1", "zone", "1", "Door")
        applied = await manager.apply_rename_camera_detection_area("cam-1", "zone", "1", "Door")

        assert preview["current_name"] == preview["proposed_name"] == "Door"
        assert applied["changed"] is False
        assert _patches(server) == []


class TestDiffDetectionAreas:
    def test_reports_an_item_added_during_the_write(self):
        expected = [{"id": 1, "name": "A"}]
        actual = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]

        assert CameraManager._diff_detection_areas(expected, actual) == ["item 2 was added"]

    @pytest.mark.asyncio
    async def test_item_added_by_the_nvr_raises(self, server):
        async def add(path, method="get", json=None, **kwargs):
            if method == "patch":
                server["raw"].update(copy.deepcopy(json))
                server["raw"]["smartDetectLines"].append({"id": 3, "name": "Extra"})
                return {}
            return copy.deepcopy(server["raw"])

        server["cm"].client.api_request = AsyncMock(side_effect=add)

        with pytest.raises(RuntimeError, match="item 3 was added"):
            await CameraManager(server["cm"]).apply_rename_camera_detection_area("cam-1", "line", "1", "Street")

    @pytest.mark.asyncio
    async def test_mismatch_message_says_the_rename_was_sent(self, server):
        async def ignore_patch(path, method="get", json=None, **kwargs):
            return {} if method == "patch" else copy.deepcopy(server["raw"])

        server["cm"].client.api_request = AsyncMock(side_effect=ignore_patch)

        with pytest.raises(RuntimeError, match="was sent to the NVR"):
            await CameraManager(server["cm"]).apply_rename_camera_detection_area("cam-1", "line", "1", "Street")


class TestApplyRename:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("kind", "area_id", "key", "index"),
        [
            ("line", "2", "smartDetectLines", 1),
            ("zone", "1", "smartDetectZones", 0),
            ("loiter_zone", "1", "smartDetectLoiterZones", 0),
        ],
    )
    async def test_patch_body_is_only_that_list_with_one_name_changed(self, server, kind, area_id, key, index):
        before = _raw_camera()

        result = await CameraManager(server["cm"]).apply_rename_camera_detection_area("cam-1", kind, area_id, "Renamed")

        patches = _patches(server)
        assert len(patches) == 1
        path, method, body = patches[0]
        assert (path, method) == ("cameras/cam-1", "patch")
        assert list(body) == [key]
        expected = copy.deepcopy(before[key])
        expected[index]["name"] = "Renamed"
        assert body[key] == expected
        assert result["changed"] is True
        assert result["name"] == "Renamed"
        assert result["previous_name"] == before[key][index]["name"]
        assert result["verified"] is True
        assert server["raw"][key] == expected

    @pytest.mark.asyncio
    async def test_other_lists_and_fields_are_untouched_on_the_nvr(self, server):
        await CameraManager(server["cm"]).apply_rename_camera_detection_area("cam-1", "line", "1", "Street")

        expected = _raw_camera()
        expected["smartDetectLines"][0]["name"] = "Street"
        assert server["raw"] == expected

    @pytest.mark.asyncio
    async def test_write_is_preceded_by_a_fresh_read_and_followed_by_another(self, server):
        await CameraManager(server["cm"]).apply_rename_camera_detection_area("cam-1", "line", "1", "Street")

        assert [c[1] for c in server["calls"]] == ["get", "patch", "get"]

    @pytest.mark.asyncio
    async def test_matches_integer_ids_by_their_string_form(self, server):
        await CameraManager(server["cm"]).apply_rename_camera_detection_area("cam-1", "line", "1", "Street")

        assert _patches(server)[0][2]["smartDetectLines"][0]["id"] == 1

    @pytest.mark.asyncio
    async def test_identical_name_sends_no_patch(self, server):
        result = await CameraManager(server["cm"]).apply_rename_camera_detection_area("cam-1", "line", "1", "Driveway")

        assert result["changed"] is False
        assert _patches(server) == []

    @pytest.mark.asyncio
    async def test_name_not_changed_by_the_nvr_raises(self, server):
        async def ignore_patch(path, method="get", json=None, **kwargs):
            if method == "patch":
                return {}
            return copy.deepcopy(server["raw"])

        server["cm"].client.api_request = AsyncMock(side_effect=ignore_patch)

        with pytest.raises(RuntimeError, match="name"):
            await CameraManager(server["cm"]).apply_rename_camera_detection_area("cam-1", "line", "1", "Street")

    @pytest.mark.asyncio
    async def test_another_field_changed_by_the_nvr_raises_naming_it(self, server):
        async def mangle(path, method="get", json=None, **kwargs):
            if method == "patch":
                server["raw"].update(copy.deepcopy(json))
                server["raw"]["smartDetectLines"][0]["sensitivity"] = 1
                return {}
            return copy.deepcopy(server["raw"])

        server["cm"].client.api_request = AsyncMock(side_effect=mangle)

        with pytest.raises(RuntimeError, match="sensitivity"):
            await CameraManager(server["cm"]).apply_rename_camera_detection_area("cam-1", "line", "1", "Street")

    @pytest.mark.asyncio
    async def test_another_item_changed_by_the_nvr_raises(self, server):
        async def mangle(path, method="get", json=None, **kwargs):
            if method == "patch":
                server["raw"].update(copy.deepcopy(json))
                server["raw"]["smartDetectLines"][1]["points"] = [[0, 0], [0, 0]]
                return {}
            return copy.deepcopy(server["raw"])

        server["cm"].client.api_request = AsyncMock(side_effect=mangle)

        with pytest.raises(RuntimeError, match="points"):
            await CameraManager(server["cm"]).apply_rename_camera_detection_area("cam-1", "line", "1", "Street")

    @pytest.mark.asyncio
    async def test_item_dropped_by_the_nvr_raises(self, server):
        async def drop(path, method="get", json=None, **kwargs):
            if method == "patch":
                server["raw"].update(copy.deepcopy(json))
                server["raw"]["smartDetectLines"].pop()
                return {}
            return copy.deepcopy(server["raw"])

        server["cm"].client.api_request = AsyncMock(side_effect=drop)

        with pytest.raises(RuntimeError, match="2"):
            await CameraManager(server["cm"]).apply_rename_camera_detection_area("cam-1", "line", "1", "Street")

    @pytest.mark.asyncio
    async def test_patch_failure_propagates_and_is_not_retried(self, server):
        async def fail(path, method="get", json=None, **kwargs):
            if method == "patch":
                raise RuntimeError("nvr rejected")
            return copy.deepcopy(server["raw"])

        server["cm"].client.api_request = AsyncMock(side_effect=fail)

        with pytest.raises(RuntimeError, match="nvr rejected"):
            await CameraManager(server["cm"]).apply_rename_camera_detection_area("cam-1", "line", "1", "Street")

        assert [c.kwargs.get("method", "get") for c in server["cm"].client.api_request.await_args_list] == [
            "get",
            "patch",
        ]
