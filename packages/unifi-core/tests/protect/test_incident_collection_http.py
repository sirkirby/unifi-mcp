"""Protect evidence reads over real HTTP: uiprotect's own retry loop runs, and every attempt is charged."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from uiprotect.api import ProtectApiClient
from unifi_core.incident_evidence import BudgetKind, FailureKind, SourceOutcome
from unifi_core.protect.incident_collection import collect_protect_incident_evidence
from unifi_core.protect.managers.event_manager import EventManager
from unifi_core.protect.models.incident_evidence import ProtectIncidentRequest
from yarl import URL

WINDOW = {"start": "2026-08-08T12:00:00Z", "end": "2026-08-08T12:59:00Z"}
PRIVATE = "fixture-private-controller-text"


async def _collect(statuses: list[int], **budget):
    """Serve ``statuses`` in turn (200 answers an empty event list) to a real uiprotect client."""
    seen: list[str] = []

    async def events(request: web.Request) -> web.Response:
        seen.append(request.method)
        status = statuses[min(len(seen), len(statuses)) - 1]
        if status == 200:
            return web.json_response([])
        return web.Response(status=status, text=PRIVATE)

    app = web.Application()
    app.router.add_get("/proxy/protect/api/events", events)
    server = TestServer(app)
    await server.start_server()
    client = ProtectApiClient("controller.invalid", 443, "fixture-user", "fixture-password", store_sessions=False)
    client._url = URL(f"http://{server.host}:{server.port}")
    client.ensure_authenticated = AsyncMock()
    client._reauthenticate = AsyncMock()
    try:
        with patch("uiprotect.api.calculate_retry_delay", return_value=0):
            evidence = await collect_protect_incident_evidence(
                EventManager(SimpleNamespace(client=client), {}), ProtectIncidentRequest(**WINDOW, **budget)
            )
    finally:
        await client.close_session()
        await server.close()
    return evidence, seen


@pytest.mark.asyncio
async def test_sdk_retries_are_refused_once_the_call_budget_is_spent() -> None:
    evidence, seen = await _collect([503, 503, 200], max_calls=1)
    assert seen == ["GET"]  # the retry was refused before it was sent
    assert evidence.budgets.usage.calls == 1 and evidence.budgets.exhausted == (BudgetKind.CALLS,)
    (source,) = evidence.sources
    assert source.outcome is SourceOutcome.NOT_ATTEMPTED and source.failure.kind is FailureKind.BUDGET_EXHAUSTED
    assert evidence.coverage_complete is False
    assert PRIVATE not in json.dumps(evidence.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_every_sdk_retry_is_charged_as_a_call() -> None:
    evidence, seen = await _collect([503, 503, 200], max_calls=5)
    assert len(seen) == evidence.budgets.usage.calls == 3
    assert evidence.sources[0].outcome is SourceOutcome.EMPTY


@pytest.mark.asyncio
async def test_the_retry_after_a_relogin_is_charged() -> None:
    evidence, seen = await _collect([401, 200], max_calls=1)
    assert seen == ["GET"] and evidence.budgets.exhausted == (BudgetKind.CALLS,)
    evidence, seen = await _collect([401, 200], max_calls=2)
    assert len(seen) == evidence.budgets.usage.calls == 2
    assert evidence.sources[0].outcome is SourceOutcome.EMPTY


@pytest.mark.asyncio
async def test_a_denied_read_is_one_charged_request_with_its_status() -> None:
    evidence, seen = await _collect([403], max_calls=5)
    assert len(seen) == evidence.budgets.usage.calls == 1
    assert evidence.sources[0].outcome is SourceOutcome.PERMISSION_DENIED
    assert evidence.sources[0].failure.http_status == 403
