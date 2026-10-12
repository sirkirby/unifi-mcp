"""Pytest configuration for unifi-core tests."""

import ipaddress
import os
import socket

import pytest

# Controller settings inherited from a developer's shell must never reach code
# under test. Tests that need a setting set it themselves.
for _name in [name for name in os.environ if name.startswith("UNIFI_")]:
    del os.environ[_name]

# --- Network guard -----------------------------------------------------------
# Tests must never reach a real host: fixture addresses such as 192.168.1.1 are
# real gateways and consoles on many networks. Every connection to a
# non-loopback address, and every lookup of a non-local name, is refused here
# and fails the test that made it at teardown, even when the code under test
# catches the refusal. Use loopback stubs or mocks instead.

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_getaddrinfo = socket.getaddrinfo
_blocked_network_access: list[str] = []


def _is_loopback(host: object) -> bool:
    if not isinstance(host, str):
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _refuse(target: str) -> None:
    _blocked_network_access.append(target)
    raise ConnectionRefusedError(f"test network guard: blocked outbound access to {target}")


def _guard_connect(real):
    def connect(self, address):
        if isinstance(address, tuple) and not _is_loopback(address[0]):
            _refuse(f"{address[0]}:{address[1]}")
        return real(self, address)

    return connect


def _guarded_getaddrinfo(host, *args, **kwargs):
    if host is not None and not _is_loopback(host if isinstance(host, str) else host.decode()):
        try:
            ipaddress.ip_address(host if isinstance(host, str) else host.decode())
        except ValueError:
            _blocked_network_access.append(f"DNS lookup of {host!r}")
            raise socket.gaierror(socket.EAI_NONAME, "test network guard: name lookup blocked") from None
    return _real_getaddrinfo(host, *args, **kwargs)


socket.socket.connect = _guard_connect(_real_connect)
socket.socket.connect_ex = _guard_connect(_real_connect_ex)
socket.getaddrinfo = _guarded_getaddrinfo


@pytest.fixture(autouse=True)
def _fail_on_outbound_network_access():
    start = len(_blocked_network_access)
    yield
    attempted = _blocked_network_access[start:]
    if attempted:
        pytest.fail(f"test attempted outbound network access: {attempted}; use loopback stubs or mocks")
