"""Safety net shared by the repository's pytest suites. Test-only; no package ships it.

A suite's conftest loads it before anything imports the code under test::

    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "testsupport"))
    import unifi_test_guard

    unifi_test_guard.protect_test_session()
    from unifi_test_guard import fail_on_outbound_network_access, pytest_configure  # noqa: F401

    stub_automatic_controller_connects = unifi_test_guard.connect_stub("<app>.runtime")

Three layers keep tests away from real controllers:

* ``protect_test_session`` deletes ``UNIFI_*`` variables inherited from the
  developer's shell, so runtime singletons built from the environment never
  carry a real host or credentials, and refuses every connection to a
  non-loopback address and every lookup of a non-local name.
* ``fail_on_outbound_network_access`` fails a test that attempted such access,
  at teardown, even when the code under test swallowed the refusal.
* ``connect_stub(...)`` builds an autouse fixture that replaces the
  self-initiated login and reconnect paths of a suite's environment-built
  runtime connection manager, and Access's and Protect's on-demand reconnects,
  unless a test opts in with ``@pytest.mark.real_reconnect``.

Fixture controller hosts should use TEST-NET addresses (``192.0.2.0/24``).
"""

from __future__ import annotations

import ipaddress
import os
import socket

import pytest

_blocked: list[str] = []
_installed = False


def protect_test_session() -> None:
    """Scrub inherited controller settings and install the network guard."""
    scrub_controller_settings()
    install_network_guard()


def scrub_controller_settings() -> None:
    """Delete ``UNIFI_*`` variables; tests that need a setting set it themselves."""
    for name in [name for name in os.environ if name.startswith("UNIFI_")]:
        del os.environ[name]


def blocked_network_access() -> list[str]:
    """The live record of refused access; tests of the guard may clear it."""
    return _blocked


def _bare_host(host: str) -> str:
    return host.strip("[]").split("%", 1)[0]


def _is_loopback(host: object) -> bool:
    if isinstance(host, bytes):
        host = host.decode(errors="replace")
    if not isinstance(host, str):
        return False
    host = _bare_host(host)
    if host.lower() in ("localhost", "localhost.localdomain"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return address.is_loopback or (mapped is not None and mapped.is_loopback)


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(_bare_host(host))
    except ValueError:
        return False
    return True


def install_network_guard() -> None:
    """Refuse non-loopback connections and non-local name lookups (idempotent)."""
    global _installed
    if _installed:
        return
    _installed = True

    def guard_connect(real):
        def connect(self, address):
            if isinstance(address, tuple) and not _is_loopback(address[0]):
                target = f"{address[0]}:{address[1]}"
                _blocked.append(target)
                raise ConnectionRefusedError(f"test network guard: blocked outbound access to {target}")
            return real(self, address)

        return connect

    real_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host, *args, **kwargs):
        name = host.decode() if isinstance(host, bytes) else host
        if name is not None and not _is_loopback(name) and not _is_ip_literal(name):
            _blocked.append(f"DNS lookup of {name!r}")
            raise socket.gaierror(socket.EAI_NONAME, "test network guard: name lookup blocked")
        return real_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = guard_connect(socket.socket.connect)
    socket.socket.connect_ex = guard_connect(socket.socket.connect_ex)
    socket.getaddrinfo = getaddrinfo


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_reconnect: run the connection managers' real login and reconnect paths instead of the stub",
    )


@pytest.fixture(autouse=True)
def fail_on_outbound_network_access():
    start = len(_blocked)
    yield
    attempted = _blocked[start:]
    if attempted:
        pytest.fail(f"test attempted outbound network access: {attempted}; use loopback stubs or mocks")


async def _not_connected(*args, **kwargs) -> bool:
    return False


# Login and reconnect paths a connection manager runs on its own, by product.
# Network's lazy ensure_connected/ensure_session_connected and Access's on-demand
# reconnect all funnel through these.
_SELF_INITIATED_CONNECTS = ("_initialize_session", "_initialize_key", "_reauthenticate", "reconnect")


def connect_stub(*runtime_modules: str):
    """Build an autouse fixture that stubs self-initiated controller connects.

    Each named runtime module's ``connection_manager`` singleton, the one built
    from the environment, has its login and reconnect paths replaced on the
    instance, so connection managers that tests build themselves keep their
    real (mocked) logic. Access's and Protect's on-demand reconnects are also
    stubbed for every instance: Protect's domain tools call ``ensure_connected``
    before they run, so any tool test could otherwise attempt a login. A test
    opts out with ``@pytest.mark.real_reconnect``.
    """

    @pytest.fixture(autouse=True)
    def stub_automatic_controller_connects(request, monkeypatch):
        if request.node.get_closest_marker("real_reconnect"):
            return
        import importlib

        for module_name in runtime_modules:
            manager = importlib.import_module(module_name).connection_manager
            for name in _SELF_INITIATED_CONNECTS:
                if hasattr(manager, name):
                    monkeypatch.setattr(manager, name, _not_connected)
        _stub_access_reconnect(monkeypatch)
        _stub_protect_reconnect(monkeypatch)

    return stub_automatic_controller_connects


def _stub_access_reconnect(monkeypatch) -> None:
    try:
        from unifi_core.access.managers.connection_manager import AccessConnectionManager
    except ImportError:
        return
    if hasattr(AccessConnectionManager, "reconnect"):

        async def _access_reconnect_stub(self) -> bool:
            return self.is_connected

        monkeypatch.setattr(AccessConnectionManager, "reconnect", _access_reconnect_stub)


def _stub_protect_reconnect(monkeypatch) -> None:
    try:
        from unifi_core.protect.managers.connection_manager import ProtectConnectionManager
    except ImportError:
        return
    if hasattr(ProtectConnectionManager, "ensure_connected"):

        async def _protect_ensure_connected_stub(self) -> bool:
            return self._initialized and self._client is not None

        monkeypatch.setattr(ProtectConnectionManager, "ensure_connected", _protect_ensure_connected_stub)
