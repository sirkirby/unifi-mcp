"""A cold Network connection acquired inside a bounded read, over real HTTPS through aiounifi.

The controller is a local TLS server. ConnectionManager.initialize runs for
real: controller-type detection, the aiounifi login, post-login detection,
then the API-version probe and the event read. Every request but the login
must be charged to the read's call budget before it is sent.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import json
import ssl
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from unifi_core.incident_evidence import BudgetKind, SourceOutcome
from unifi_core.network.incident_collection import collect_network_incident_evidence
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.event_manager import EventManager
from unifi_core.network.models.incident_evidence import NetworkIncidentRequest
from unifi_core.request_budget import LOGIN_PATHS

WINDOW = {"start": "2026-08-08T12:00:00Z", "end": "2026-08-08T12:59:00Z"}
PRIVATE = "fixture-private-controller-text"


def _tls_context(directory: Path) -> ssl.SSLContext:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "controller.invalid")])
    now = dt.datetime.now(dt.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(cert_path, key_path)
    return context


class Controller:
    """A UniFi OS console answering just enough for aiounifi to log in and read events."""

    def __init__(self, login_status: int = 200) -> None:
        self.login_status = login_status
        self.seen: list[str] = []
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self.handle)
        self.app = app

    async def handle(self, request: web.Request) -> web.Response:
        self.seen.append(f"{request.method} {request.path}")
        path = request.path
        if path == "/":
            return web.Response(text="UniFi OS")
        if path == "/api/auth/login" and self.login_status != 200:
            return web.json_response({"errors": [PRIVATE]}, status=self.login_status)
        if path == "/api/auth/login":
            response = web.json_response({"unique_id": "fixture-user"})
            response.set_cookie("TOKEN", "fixture-session")
            response.headers["x-csrf-token"] = "fixture-csrf"
            return response
        if path.endswith("/self/sites"):
            return web.json_response({"meta": {"rc": "ok"}, "data": [{"name": "default", "desc": "Default"}]})
        if path.endswith("/system-log/count"):
            return web.json_response({"count": 0})
        if path.endswith("/system-log/all"):
            return web.json_response({"data": [], "total_element_count": 0})
        return web.Response(status=404)

    @property
    def charged(self) -> list[str]:
        return [line for line in self.seen if not line.split(" ", 1)[1].endswith(LOGIN_PATHS)]


async def _collect(tmp_path: Path, login_status: int = 200, **budget):
    controller = Controller(login_status)
    server = TestServer(controller.app)
    await server.start_server(ssl=_tls_context(tmp_path))
    connection = ConnectionManager("127.0.0.1", "fixture-user", "fixture-password", port=server.port, retry_delay=0)

    async def acquire() -> EventManager:
        if not await connection.initialize():
            raise connection.initialization_failure or ConnectionError("not connected")
        return EventManager(connection)

    try:
        evidence = await collect_network_incident_evidence(acquire, NetworkIncidentRequest(**WINDOW, **budget))
    finally:
        await connection.cleanup()
        await server.close()
    return evidence, controller


@pytest.mark.asyncio
async def test_every_non_login_request_of_a_cold_connection_is_charged(tmp_path) -> None:
    evidence, controller = await _collect(tmp_path, max_calls=20)
    assert any(line.endswith("/api/auth/login") for line in controller.seen)
    assert controller.charged[-1].endswith("/system-log/all")
    assert evidence.budgets.usage.calls == len(controller.charged) > 2
    assert evidence.sources[0].outcome is SourceOutcome.EMPTY


@pytest.mark.asyncio
async def test_a_cold_connection_that_cannot_fit_the_budget_fails_closed(tmp_path) -> None:
    evidence, controller = await _collect(tmp_path, max_calls=1)
    assert len(controller.charged) == evidence.budgets.usage.calls == 1
    assert not any(line.endswith("/system-log/all") for line in controller.seen)
    assert evidence.budgets.exhausted == (BudgetKind.CALLS,)
    assert evidence.sources[0].outcome is SourceOutcome.NOT_ATTEMPTED
    assert evidence.coverage_complete is False


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "outcome"), [(401, "auth_failed"), (403, "permission_denied")])
async def test_a_refused_login_keeps_its_category_and_no_controller_text(tmp_path, caplog, status, outcome) -> None:
    with caplog.at_level("DEBUG"):
        evidence, _ = await _collect(tmp_path, login_status=status, max_calls=20)
    (source,) = evidence.sources
    assert source.outcome.value == outcome
    assert PRIVATE not in json.dumps(evidence.model_dump(mode="json"))
    assert all(PRIVATE not in record.getMessage() for record in caplog.records)
