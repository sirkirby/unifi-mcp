"""Exercise real SDK setters, mocking only the controller transport boundary."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from uiprotect.data import Camera, Light
from uiprotect.data.devices import CameraFeatureFlags, ISPSettings, LightDeviceSettings, LightOnSettings
from uiprotect.data.types import HDRMode, PublicHdrMode
from unifi_core.protect.managers.camera_manager import CameraManager
from unifi_core.protect.managers.connection_manager import ProtectConnectionManager
from unifi_core.protect.managers.light_manager import LightManager


@pytest.fixture
def devices():
    api = SimpleNamespace(
        update_camera_public=AsyncMock(return_value=SimpleNamespace(mic_volume=51)),
        update_light_public=AsyncMock(),
    )
    camera = Camera.model_construct(
        id="camera",
        name="Camera",
        hdr_mode=True,
        mic_volume=50,
        feature_flags=CameraFeatureFlags.model_construct(has_hdr=True, has_mic=True),
        isp_settings=ISPSettings.model_construct(hdr_mode=HDRMode.NORMAL),
    )
    light = Light.model_construct(
        id="light",
        name="Light",
        light_device_settings=LightDeviceSettings.model_construct(
            led_level=3,
            pir_sensitivity=50,
            pir_duration=timedelta(seconds=30),
            is_indicator_enabled=True,
        ),
        light_on_settings=LightOnSettings.model_construct(is_led_force_on=False),
    )
    camera._api = light._api = api
    api.bootstrap = SimpleNamespace(cameras={camera.id: camera}, lights={light.id: light})
    api.get_cameras_public = AsyncMock(return_value=[SimpleNamespace(id="camera")])
    api.get_lights_public = AsyncMock(return_value=[SimpleNamespace(id="light")])
    cm = ProtectConnectionManager(host="controller.invalid", username="test", password="test", api_key="test")
    cm._client = api
    cm._initialized = True
    return cm, api, camera, light


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value,expected", [(False, PublicHdrMode.OFF), (True, PublicHdrMode.AUTO), ("superHdr", PublicHdrMode.ON)]
)
async def test_hdr_real_setter(devices, value, expected):
    cm, api, camera, _ = devices
    result = await CameraManager(cm).apply_camera_settings(camera.id, {"hdr_mode": value})
    assert not result.get("errors")
    api.update_camera_public.assert_awaited_once_with(camera.id, hdr_type=expected)


@pytest.mark.asyncio
async def test_microphone_real_setter(devices):
    cm, api, camera, _ = devices
    await CameraManager(cm).apply_camera_settings(camera.id, {"mic_volume": 51})
    api.update_camera_public.assert_awaited_once_with(camera.id, mic_volume=51)
    assert camera.mic_volume == 51


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settings,field,expected",
    [
        ({"led_level": 4}, "led_level", 4),
        ({"sensitivity": 51}, "pir_sensitivity", 51),
        ({"duration_seconds": 60}, "pir_duration", timedelta(seconds=60)),
    ],
)
async def test_light_real_setters_preserve_other_fields(devices, settings, field, expected):
    cm, api, _, light = devices
    original = light.light_device_settings.model_dump()
    result = await LightManager(cm).apply_light_settings(light.id, settings)
    assert not result.get("errors")
    sent = api.update_light_public.await_args.kwargs["light_device_settings"].model_dump()
    assert sent == {**original, field: expected}


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["light_on", "is_light_on"])
async def test_light_power_aliases(devices, key):
    cm, api, _, light = devices
    await LightManager(cm).apply_light_settings(light.id, {key: True})
    api.update_light_public.assert_awaited_once_with(light.id, is_light_force_enabled=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("preview", [False, True])
@pytest.mark.parametrize(
    "domain,settings",
    [
        ("camera", {"hdr_mode": "auto", "mic_volume": 0}),
        ("camera", {"mic_volume": 50, "hdr_mode": "invalid"}),
        ("camera", {"mic_volume": 50, "speaker_volume": 101}),
        ("light", {"light_on": True, "led_level": 7}),
        ("light", {"light_on": True, "sensitivity": -1}),
        ("light", {"light_on": True, "duration_seconds": 14}),
        ("light", {"light_on": True, "is_light_on": False}),
    ],
)
async def test_invalid_request_has_no_writes(devices, preview, domain, settings):
    cm, api, camera, light = devices
    manager = CameraManager(cm) if domain == "camera" else LightManager(cm)
    method = (
        (manager.update_camera_settings if preview else manager.apply_camera_settings)
        if domain == "camera"
        else (manager.update_light if preview else manager.apply_light_settings)
    )
    with pytest.raises(ValueError):
        await method(camera.id if domain == "camera" else light.id, settings)
    api.update_camera_public.assert_not_awaited()
    api.update_light_public.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["camera", "light"])
@pytest.mark.parametrize("failure", ["missing_key", "id_mismatch", "read_failure"])
async def test_preflight_failure_prevents_all_writes(devices, domain, failure):
    cm, api, camera, light = devices
    if failure == "missing_key":
        cm._api_key = " "
        expected = "requires an API key"
    else:
        getter = api.get_cameras_public if domain == "camera" else api.get_lights_public
        getter.return_value = [SimpleNamespace(id="different")]
        expected = "not portable"
        if failure == "read_failure":
            getter.side_effect = ValueError("controller unavailable")
            expected = "controller unavailable"
    with pytest.raises(ValueError, match=expected):
        if domain == "camera":
            await CameraManager(cm).apply_camera_settings(camera.id, {"name": "new", "mic_volume": 51})
        else:
            await LightManager(cm).apply_light_settings(light.id, {"name": "new", "led_level": 4})
    api.update_camera_public.assert_not_awaited()
    api.update_light_public.assert_not_awaited()
    assert camera.name == "Camera" and light.name == "Light"


@pytest.mark.asyncio
async def test_partial_controller_failure_reports_applied_fields(devices):
    cm, api, camera, _ = devices
    api.update_camera_public.side_effect = [SimpleNamespace(mic_volume=51), RuntimeError("controller failed")]
    result = await CameraManager(cm).apply_camera_settings(camera.id, {"mic_volume": 51, "hdr_mode": "auto"})
    assert result["applied"] == ["mic_volume=51"]
    assert result["errors"] == ["hdr_mode: controller failed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("key,feature,value", [("hdr_mode", "has_hdr", "auto"), ("mic_volume", "has_mic", 51)])
async def test_unsupported_camera_feature_fails_before_writes(devices, key, feature, value):
    cm, api, camera, _ = devices
    setattr(camera.feature_flags, feature, False)
    with pytest.raises(ValueError, match="Cannot update"):
        await CameraManager(cm).apply_camera_settings(camera.id, {"name": "new", key: value})
    api.update_camera_public.assert_not_awaited()
    assert camera.name == "Camera"


@pytest.mark.asyncio
async def test_preview_uses_force_setting_not_transient_light_state(devices):
    cm, api, _, light = devices
    light.is_light_on = True
    result = await LightManager(cm).update_light(light.id, {"light_on": True})
    assert result["current_state"]["light_on"] is False
    assert result["proposed_changes"]["light_on"] is True
    api.update_light_public.assert_not_awaited()


@pytest.mark.asyncio
async def test_hdr_off_preview_does_not_report_normal_isp_mode(devices):
    cm, api, camera, _ = devices
    camera.hdr_mode = False
    result = await CameraManager(cm).update_camera_settings(camera.id, {"hdr_mode": True})
    assert result["current_state"]["hdr_mode"] == "off"
    assert result["proposed_changes"]["hdr_mode"] == "auto"
    api.update_camera_public.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_light_updates_preserve_both_settings(devices):
    cm, api, _, light = devices
    manager = LightManager(cm)
    writes = []

    async def controller_update(device_id, **kwargs):
        writes.append(kwargs["light_device_settings"].model_dump())
        await asyncio.sleep(0)

    api.update_light_public.side_effect = controller_update
    results = await asyncio.gather(
        manager.apply_light_settings(light.id, {"led_level": 4}),
        manager.apply_light_settings(light.id, {"sensitivity": 51}),
    )
    assert all(not result.get("errors") for result in results)
    assert writes[-1]["led_level"] == 4
    assert writes[-1]["pir_sensitivity"] == 51
    assert light.light_device_settings.led_level == 4
    assert light.light_device_settings.pir_sensitivity == 51
