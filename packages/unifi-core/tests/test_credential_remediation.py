"""Credential remediation text names server variables only for a caller that reads them.

An MCP server passes its env prefix; the API server passes none and keeps
credentials on the controller record. The shared key applies only on the
UNIFI_HOST console, so it is never named unqualified.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from uiprotect.exceptions import NotAuthorized
from unifi_core.access.managers.connection_manager import AccessConnectionManager, access_api_token_remediation
from unifi_core.auth import AuthenticationStatus, UniFiAuth, api_key_variables, session_credentials_remediation
from unifi_core.exceptions import UniFiAuthError
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.dpi_manager import _missing_key_message
from unifi_core.network.managers.firewall_manager import FirewallManager
from unifi_core.network.managers.traffic_route_manager import TrafficRouteManager
from unifi_core.network.models.traffic_flows import dpi_names_api_key_remediation
from unifi_core.protect.managers.alarm_manager_service import AlarmManagerService
from unifi_core.protect.managers.chime_manager import ChimeManager
from unifi_core.protect.managers.connection_manager import protect_api_key_remediation
from unifi_core.protect.managers.sensor_manager import SensorManager
from unifi_core.protect.managers.system_manager import SystemManager
from yarl import URL

SHARED = "(or UNIFI_API_KEY on the UNIFI_HOST console)"
RECORD = "this controller's configuration"


def _assert_names_variables(text: str, variable: str) -> None:
    assert f"{variable} {SHARED}" in text
    assert RECORD not in text


def _assert_points_at_record(text: str) -> None:
    assert RECORD in text
    assert "UNIFI_" not in text


# -- shared helpers -----------------------------------------------------------


@pytest.mark.parametrize("prefix", [None, "", MagicMock()])
def test_api_key_variables_are_named_only_for_a_string_prefix(prefix):
    assert api_key_variables(prefix) is None


def test_api_key_variables_qualify_the_shared_key():
    assert api_key_variables("PROTECT") == f"UNIFI_PROTECT_API_KEY {SHARED}"


def test_session_credentials_remediation_branches():
    assert session_credentials_remediation("NETWORK") == "Configure UNIFI_NETWORK_USERNAME and UNIFI_NETWORK_PASSWORD."
    _assert_points_at_record(session_credentials_remediation(None))


@pytest.mark.parametrize(
    ("helper", "variable"),
    [
        (_missing_key_message, "UNIFI_NETWORK_API_KEY"),
        (dpi_names_api_key_remediation, "UNIFI_NETWORK_API_KEY"),
    ],
)
def test_network_dpi_key_text_branches(helper, variable):
    _assert_names_variables(helper("NETWORK"), variable)
    _assert_points_at_record(helper(None))


def test_access_and_protect_key_text_say_valid():
    _assert_names_variables(access_api_token_remediation("ACCESS"), "UNIFI_ACCESS_API_KEY")
    _assert_points_at_record(access_api_token_remediation(None))
    _assert_names_variables(protect_api_key_remediation("PROTECT"), "UNIFI_PROTECT_API_KEY")
    _assert_points_at_record(protect_api_key_remediation(None))
    for text in (access_api_token_remediation(None), protect_api_key_remediation("PROTECT")):
        assert "valid" in text


# -- Network ------------------------------------------------------------------


def _network(prefix, api_key=None):
    return ConnectionManager("controller.test", "", "", auth=UniFiAuth(api_key=api_key), tls_env_prefix=prefix)


@pytest.mark.asyncio
async def test_network_integration_request_without_key():
    with pytest.raises(UniFiAuthError) as named:
        await _network("NETWORK").request_integration("/v1/sites")
    _assert_names_variables(str(named.value), "UNIFI_NETWORK_API_KEY")

    with pytest.raises(UniFiAuthError) as record:
        await _network(None).request_integration("/v1/sites")
    _assert_points_at_record(str(record.value))


@pytest.mark.asyncio
@pytest.mark.parametrize(("prefix", "expected"), [("NETWORK", "UNIFI_NETWORK_USERNAME"), (None, RECORD)])
async def test_network_key_transport_refusal_names_session_credentials(prefix, expected):
    cm = _network(prefix, api_key="synthetic-key")
    request = Mock(method="POST", url=URL("https://controller.test/proxy/network/api/s/default/cmd/devmgr"))
    with pytest.raises(UniFiAuthError) as error:
        await cm._key_read_transport(request, AsyncMock())
    assert expected in str(error.value)
    assert ("UNIFI_" in str(error.value)) is bool(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(("prefix", "expected"), [("NETWORK", "UNIFI_NETWORK_USERNAME"), (None, RECORD)])
async def test_network_inventory_only_refusal_names_session_credentials(prefix, expected):
    cm = _network(prefix, api_key="synthetic-key")
    cm._initialized = cm._key_mode = True
    cm.controller = None
    with pytest.raises(UniFiAuthError) as error:
        await cm.ensure_connected()
    assert expected in str(error.value)
    assert ("UNIFI_" in str(error.value)) is bool(prefix)


@pytest.mark.asyncio
async def test_network_rejected_key_error_branches():
    named = _network("NETWORK", api_key="synthetic-key")
    named._key_mode = True
    assert not await named._reauthenticate(0)
    _assert_names_variables(named.last_connection_error, "UNIFI_NETWORK_API_KEY")

    record = _network(None, api_key="synthetic-key")
    record._key_mode = True
    assert not await record._reauthenticate(0)
    _assert_points_at_record(record.last_connection_error)


@pytest.mark.parametrize("prefix", ["NETWORK", None])
def test_firewall_integration_key_requirement_branches(prefix):
    manager = FirewallManager(SimpleNamespace(tls_env_prefix=prefix), auth=UniFiAuth())
    with pytest.raises(RuntimeError) as error:
        manager._require_integration_api_key("Creating a firewall zone")
    if prefix:
        _assert_names_variables(str(error.value), "UNIFI_NETWORK_API_KEY")
    else:
        _assert_points_at_record(str(error.value))


@pytest.mark.asyncio
@pytest.mark.parametrize(("prefix", "expected"), [("NETWORK", "UNIFI_NETWORK_USERNAME"), (None, RECORD)])
async def test_firewall_zone_mutation_session_branches(prefix, expected):
    connection = SimpleNamespace(
        tls_env_prefix=prefix,
        ensure_connected=AsyncMock(return_value=True),
        authentication_status=AuthenticationStatus(session_available=False),
    )
    with pytest.raises(UniFiAuthError) as error:
        await FirewallManager(connection)._require_zone_mutation_session()
    assert expected in str(error.value)
    assert ("UNIFI_" in str(error.value)) is bool(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(("prefix", "expected"), [("NETWORK", "UNIFI_NETWORK_USERNAME"), (None, RECORD)])
async def test_internet_traffic_route_session_branches(prefix, expected):
    connection = _network(prefix, api_key="synthetic-key")
    connection._initialized = connection._key_mode = True
    manager = TrafficRouteManager(connection, network_manager=MagicMock())
    target = [{"type": "CLIENT", "client_mac": "02:00:00:00:00:01"}]
    with pytest.raises(UniFiAuthError) as error:
        await manager.validate_internet_route_target(target, "legacy-wan-id")
    assert expected in str(error.value)
    assert ("UNIFI_" in str(error.value)) is bool(prefix)


# -- Access -------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key", [None, "synthetic-key"])
async def test_access_developer_request_branches(api_key):
    named = AccessConnectionManager(host="h", username="u", password="p", api_key=api_key, tls_env_prefix="ACCESS")
    with pytest.raises(UniFiAuthError) as error:
        await named.developer_request("GET", "visitors", operation="List visitors")
    _assert_names_variables(str(error.value), "UNIFI_ACCESS_API_KEY")

    record = AccessConnectionManager(host="h", username="u", password="p", api_key=api_key)
    with pytest.raises(UniFiAuthError) as error:
        await record.developer_request("GET", "visitors", operation="List visitors")
    _assert_points_at_record(str(error.value))


# -- Protect ------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["PROTECT", None])
async def test_protect_rejected_webhook_key_branches(prefix):
    cm = MagicMock()
    cm.tls_env_prefix = prefix
    cm.client.send_alarm_webhook_public = AsyncMock(side_effect=NotAuthorized("Status: 401"))
    with pytest.raises(ValueError, match="^The controller rejected the Protect API key") as error:
        await AlarmManagerService(cm).fire_webhook("door-test")
    if prefix:
        _assert_names_variables(str(error.value), "UNIFI_PROTECT_API_KEY")
    else:
        _assert_points_at_record(str(error.value))


@pytest.mark.parametrize(
    ("manager_class", "args"),
    [
        (ChimeManager, ("update chime ring settings", "chime-1")),
        (SensorManager, ("update sensor settings", "sensor-1")),
        (SystemManager, ("update viewer", "viewer", "viewer-1")),
    ],
)
@pytest.mark.parametrize("prefix", ["PROTECT", None])
def test_protect_public_api_error_branches(manager_class, args, prefix):
    manager = manager_class(SimpleNamespace(tls_env_prefix=prefix))
    with pytest.raises(ValueError) as error:
        manager._raise_public_api_error(*args, RuntimeError("Status: 401"))
    if prefix:
        _assert_names_variables(str(error.value), "UNIFI_PROTECT_API_KEY")
    else:
        _assert_points_at_record(str(error.value))
