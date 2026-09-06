"""An expired session must be recovered on the handler-refresh path too.

`unifi_list_devices`, `get_client_details` and `get_top_clients` once failed
with 401 after the controller had been up for a while, while
`get_network_health`, `get_traffic_flows` and `get_system_info` kept working.
That split is not arbitrary: the working tools go through
``ConnectionManager.request()``, which catches ``LoginRequired`` and
re-authenticates. The failing ones call an aiounifi handler's ``update()``
directly, so the exception is raised straight past that wrapper and no login is
ever attempted.

The first fix added re-authentication but its test drove
``ConnectionManager.request()`` — the path that already recovered. These tests
drive ``handler.update()`` instead, which is the path that did not, so they
fail against that first fix and pass against the handler-refresh recovery.
"""

import pytest
from aiounifi.errors import LoginRequired

from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.device_manager import DeviceManager


class _Handler:
    """Stand-in for an aiounifi handler such as ``controller.devices``.

    ``update()`` raises ``LoginRequired`` until a login happens, which is what an
    expired controller session does. Crucially the failure surfaces from
    ``update()`` and not from ``controller.request()`` — reproducing the real
    call path rather than the one the original fix's test exercised.
    """

    def __init__(self, controller, values):
        self._controller = controller
        self._values = values
        self.update_calls = 0

    async def update(self):
        self.update_calls += 1
        if not self._controller.logged_in:
            raise LoginRequired("expired")

    def values(self):
        return list(self._values)


class _Controller:
    def __init__(self, values=()):
        self.logged_in = False
        self.login_calls = 0
        self.connectivity = _Connectivity()
        self.devices = _Handler(self, values)

    async def login(self):
        self.login_calls += 1
        self.logged_in = True


class _Connectivity:
    def __init__(self):
        self.can_retry_login = True
        self.config = _Config()


class _Config:
    def __init__(self):
        self.session = _Session()


class _Session:
    closed = False

    async def close(self):
        return None


def _manager(controller):
    manager = ConnectionManager("192.168.1.1", "admin", "secret")
    manager.controller = controller
    manager._aiohttp_session = controller.connectivity.config.session
    manager._initialized = True
    manager._auth_generation = 1
    return manager


@pytest.mark.asyncio
async def test_handler_refresh_reauthenticates_and_retries():
    """The bare defect: an expired session must produce a login, not a 401."""
    controller = _Controller()
    manager = _manager(controller)

    await manager.refresh_handler("devices")

    assert controller.login_calls == 1, "no re-authentication was attempted on the handler path"
    assert controller.devices.update_calls == 2, "the refresh was not retried after logging back in"
    assert manager._auth_generation == 2
    assert controller.connectivity.can_retry_login is False
    await manager.cleanup()


@pytest.mark.asyncio
async def test_handler_refresh_does_not_log_in_when_the_session_is_valid():
    """The happy path must stay a single call with no spurious login."""
    controller = _Controller()
    controller.logged_in = True
    manager = _manager(controller)

    await manager.refresh_handler("devices")

    assert controller.login_calls == 0
    assert controller.devices.update_calls == 1
    assert manager._auth_generation == 1
    await manager.cleanup()


@pytest.mark.asyncio
async def test_handler_refresh_reraises_when_reauthentication_fails():
    """A login that cannot succeed must surface the original error, not mask it."""
    controller = _Controller()

    async def _failing_login():
        controller.login_calls += 1
        raise LoginRequired("still expired")

    controller.login = _failing_login
    manager = _manager(controller)

    with pytest.raises(LoginRequired):
        await manager.refresh_handler("devices")

    assert controller.login_calls == 1
    await manager.cleanup()


@pytest.mark.asyncio
async def test_persistent_login_required_after_refresh_opens_the_auth_circuit():
    """A login that succeeds but is not accepted must not become a login storm.

    ``request()`` already treats a second ``LoginRequired`` as terminal; the
    refresh path has to agree, or every later tool call starts another login
    against a controller that is already refusing them.
    """
    controller = _Controller()

    async def _login_that_is_not_accepted():
        controller.login_calls += 1
        # Login "succeeds" but the session it produces is still rejected.

    controller.login = _login_that_is_not_accepted
    manager = _manager(controller)

    with pytest.raises(LoginRequired):
        await manager.refresh_handler("devices")

    assert controller.login_calls == 1
    assert controller.devices.update_calls == 2, "the refresh should have been retried exactly once"
    assert manager._reconnect_block_active(), "a rejected refreshed session must open the auth circuit"
    await manager.cleanup()


@pytest.mark.asyncio
async def test_get_devices_recovers_from_an_expired_session():
    """The user-visible regression, end to end.

    `unifi_list_devices` is `DeviceManager.get_devices`. Without handler-refresh
    recovery this raises `LoginRequired` and the tool reports
    "received 401 Unauthorized".
    """
    controller = _Controller(values=[{"mac": "aa:bb:cc:dd:ee:ff", "name": "sw"}])
    manager = _manager(controller)

    devices = await DeviceManager(manager).get_devices()

    assert controller.login_calls == 1, "get_devices did not re-authenticate an expired session"
    assert [d["mac"] for d in devices] == ["aa:bb:cc:dd:ee:ff"]
    await manager.cleanup()
