"""Tests for shared support-bundle assembly and live-probe controls."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from unifi_core.support_bundle import (
    AccessCapabilities,
    ConnectionSection,
    ControllerSection,
    EvidenceStatus,
    NetworkCapabilities,
    Product,
    ProtectCapabilities,
    ResourceShapeProbe,
    SanitizationSection,
    SummaryProbe,
    connection_attempt_succeeded,
)
from unifi_mcp_shared.meta_tools import register_meta_tools
from unifi_mcp_shared.strict_dispatch import StrictKwargFastMCP
from unifi_mcp_shared.support_bundle import (
    LiveProbeGate,
    SupportBundleEvidence,
    SupportBundleService,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "product,prefix", [(Product.NETWORK, "unifi"), (Product.PROTECT, "protect"), (Product.ACCESS, "access")]
)
@pytest.mark.parametrize(
    "arguments",
    [
        {"probe": "private-canary-token"},
        {"probe": ["private-canary-token"]},
        {"probe": {"secret": "private-canary-token"}},
        {"probe": None},
        {"probe": 42},
        {"probe": "resource_shape", "resource": {"secret": "private-canary-token"}},
        {"probe": "resource_shape", "resource": ["private-canary-token"]},
        {"resource": ["private-canary-token"]},
    ],
)
async def test_mcp_support_validation_never_echoes_rejected_input(product, prefix, arguments, caplog):
    service, adapter = _service(product)
    server = StrictKwargFastMCP("support-validation-test")
    register_meta_tools(
        server=server,
        tool_decorator=server.tool,
        tool_index_handler=AsyncMock(return_value={}),
        start_async_tool=AsyncMock(),
        get_job_status=AsyncMock(),
        register_tool=Mock(),
        support_bundle_handler=service.generate,
        prefix=prefix,
    )
    with caplog.at_level("INFO"):
        result = await server.call_tool(f"{prefix}_get_support_bundle", arguments)

    payload = json.loads(result.content[0].text)
    assert payload["success"] is False
    assert payload["error"].startswith("Failed to generate support bundle")
    assert "private-canary-token" not in result.model_dump_json()
    assert "private-canary-token" not in caplog.text
    assert "traceback" not in caplog.text.lower()
    audits = [record.message for record in caplog.records if "Support bundle audit" in record.message]
    assert len(audits) == 1
    assert "outcome=failed" in audits[0]
    adapter.collect.assert_not_awaited()

    tool = next(tool for tool in await server.list_tools() if tool.name == f"{prefix}_get_support_bundle")
    assert tool.input_schema["properties"]["probe"]["enum"] == ["summary", "connectivity", "resource_shape"]


def _evidence(product: Product, *, probe: str = "summary") -> SupportBundleEvidence:
    capabilities = {
        Product.NETWORK: NetworkCapabilities(
            session_available=True,
            integration_api_key_configured=False,
            controller_type="proxy",
            reconnect_circuit="closed",
        ),
        Product.PROTECT: ProtectCapabilities(
            session_available=True,
            bootstrap_available=True,
            public_api_key_configured=False,
            websocket_state="connected",
        ),
        Product.ACCESS: AccessCapabilities(
            developer_api_available=True,
            proxy_session_available=False,
            api_token_configured=True,
        ),
    }[product]
    probe_section = (
        SummaryProbe(status=EvidenceStatus.AVAILABLE)
        if probe == "summary"
        else ResourceShapeProbe(status=EvidenceStatus.UNSUPPORTED, resource="sensors")
    )
    return SupportBundleEvidence(
        controller=ControllerSection(
            status=EvidenceStatus.AVAILABLE,
            application_version="10.1.2",
            api_surface="controller_v2",
            capability_flags=("cached_state",),
        ),
        connection=ConnectionSection(
            initialized=True,
            connected=True,
            tls_verification_enabled=True,
            last_attempt=connection_attempt_succeeded(),
            capabilities=capabilities,
        ),
        probe=probe_section,
        sanitization=SanitizationSection(
            values_suppressed=True,
            dynamic_keys_suppressed=True,
            errors_normalized=True,
            variants_truncated=False,
            nodes_truncated=False,
            bytes_truncated=False,
        ),
    )


class _Adapter:
    def __init__(self, product: Product) -> None:
        self.product = product
        self.collect = AsyncMock(side_effect=self._collect)

    async def _collect(self, probe: str, resource: str | None) -> SupportBundleEvidence:
        del resource
        return _evidence(self.product, probe=probe)


def _service(product: Product, **overrides) -> tuple[SupportBundleService, _Adapter]:
    adapter = _Adapter(product)
    versions = {
        "aiounifi": "95",
        "mcp": "2.1.1",
        "pydantic": "2.12.5",
        "py-unifi-access": "3.3.0",
        "unifi-access-mcp": "0.14.0",
        "unifi-core": "0.4.39",
        "unifi-mcp-shared": "0.6.12",
        "unifi-network-mcp": "1.4.2",
        "unifi-protect-mcp": "0.12.0",
        "uiprotect": "15.14.2",
    }
    kwargs = {
        "adapter": adapter,
        "registration_mode": "lazy",
        "content_mode": "adaptive",
        "transports": ("stdio", "streamable-http"),
        "diagnostics_enabled": False,
        "response_redaction_enabled": True,
        "manifest_reader": lambda: {"count": 75, "host": "never-read.example.invalid"},
        "clock": lambda: datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        "version_resolver": versions.__getitem__,
        "python_version_resolver": lambda: "3.13.7",
        "os_family_resolver": lambda: "darwin",
        "architecture_resolver": lambda: "arm64",
        "live_probe_gate": LiveProbeGate(),
    }
    kwargs.update(overrides)
    return SupportBundleService(**kwargs), adapter


@pytest.mark.parametrize(
    ("product", "package", "tool"),
    [
        (Product.NETWORK, "unifi-network-mcp", "unifi_get_support_bundle"),
        (Product.PROTECT, "unifi-protect-mcp", "protect_get_support_bundle"),
        (Product.ACCESS, "unifi-access-mcp", "access_get_support_bundle"),
    ],
)
async def test_summary_assembles_deterministic_safe_runtime_and_manifest_facts(product, package, tool):
    service, adapter = _service(product)

    first = await service.generate()
    second = await service.generate()

    assert first == second
    assert first["success"] is True
    data = first["data"]
    assert data["generated_at"] == "2026-09-04T12:00:00Z"
    assert data["server"]["package"] == package
    assert data["server"]["tool"] == tool
    assert data["runtime"] == {
        "python_version": "3.13.7",
        "os_family": "macos",
        "architecture": "arm64",
        "transports": ["stdio", "streamable_http"],
        "registration_mode": "lazy",
        "content_mode": "dual",
        "manifest_tool_count": 75,
        "manifest_generator": "scripts/generate_tool_manifest.py",
    }
    assert "never-read.example.invalid" not in json.dumps(first)
    assert adapter.collect.await_count == 2


@pytest.mark.parametrize(
    ("probe", "resource"),
    [
        ("unknown", None),
        ("summary", "sensors"),
        ("connectivity", "sensors"),
        ("resource_shape", None),
        ("resource_shape", "doors"),
    ],
)
async def test_invalid_arguments_never_call_adapter(probe, resource):
    service, adapter = _service(Product.PROTECT)

    result = await service.generate(probe=probe, resource=resource)

    assert result["success"] is False
    assert result["error"].startswith("Failed to generate support bundle:")
    adapter.collect.assert_not_awaited()


@pytest.mark.parametrize(
    ("categories", "tools"),
    [((), None), (None, ()), (("system",), None), (None, ("protect_list_cameras",))],
)
async def test_resource_probe_respects_backing_category_and_tool_exposure(categories, tools):
    service, adapter = _service(
        Product.PROTECT,
        enabled_categories=categories,
        enabled_tools=tools,
    )

    result = await service.generate(probe="resource_shape", resource="sensors")

    assert result == {
        "success": False,
        "error": "Failed to generate support bundle: the backing read surface is disabled by configuration.",
    }
    adapter.collect.assert_not_awaited()


async def test_enabled_resource_probe_returns_adapter_unsupported_evidence():
    service, adapter = _service(
        Product.PROTECT,
        enabled_categories=("devices",),
        enabled_tools=("protect_list_sensors",),
    )

    result = await service.generate(probe="resource_shape", resource="sensors")

    assert result["success"] is True
    assert result["data"]["probe"] == {
        "probe": "resource_shape",
        "status": "unsupported",
        "resource": "sensors",
        "shape": None,
    }
    adapter.collect.assert_awaited_once()


async def test_live_probes_are_single_flight_and_have_per_key_cooldown():
    monotonic_value = 100.0
    gate = LiveProbeGate(monotonic=lambda: monotonic_value)
    service, adapter = _service(Product.PROTECT, live_probe_gate=gate)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_collect(probe: str, resource: str | None) -> SupportBundleEvidence:
        entered.set()
        await release.wait()
        return _evidence(Product.PROTECT, probe=probe)

    adapter.collect.side_effect = slow_collect
    first = asyncio.create_task(service.generate(probe="resource_shape", resource="sensors"))
    await entered.wait()
    busy = await service.generate(probe="resource_shape", resource="sensors")
    release.set()
    assert (await first)["success"] is True
    assert busy["error"] == "Failed to generate support bundle: another live probe is in progress."

    cooldown = await service.generate(probe="resource_shape", resource="sensors")
    assert cooldown["error"] == "Failed to generate support bundle: this live probe is in cooldown."


async def test_adapter_and_validation_failures_return_fixed_errors_without_values(caplog):
    canary = "token-DO-NOT-LOG"
    service, adapter = _service(Product.NETWORK)
    adapter.collect.side_effect = ValueError(canary)

    result = await service.generate()

    assert result == {"success": False, "error": "Failed to generate support bundle."}
    assert canary not in caplog.text


async def test_partial_controller_failure_still_returns_summary():
    service, adapter = _service(Product.NETWORK)
    partial = _evidence(Product.NETWORK)
    adapter.collect.side_effect = None
    adapter.collect.return_value = SupportBundleEvidence(
        controller=partial.controller.model_copy(update={"status": EvidenceStatus.NOT_CONNECTED}),
        connection=partial.connection.model_copy(update={"initialized": False, "connected": False}),
        probe=SummaryProbe(status=EvidenceStatus.UNAVAILABLE),
        sanitization=partial.sanitization,
    )

    result = await service.generate()

    assert result["success"] is True
    assert result["data"]["controller"]["status"] == "not_connected"
    assert result["data"]["probe"]["status"] == "unavailable"


async def test_manifest_reader_and_version_failures_are_reduced_to_safe_fallbacks():
    def fail_manifest():
        raise RuntimeError("/private/path/controller.example.invalid")

    def fail_version(_package: str):
        raise RuntimeError("secret-index-url")

    service, _ = _service(Product.ACCESS, manifest_reader=fail_manifest, version_resolver=fail_version)

    result = await service.generate()

    assert result["success"] is True
    assert result["data"]["runtime"]["manifest_tool_count"] == 0
    assert result["data"]["server"]["version"] == "0.0.0"
    assert {item["version"] for item in result["data"]["dependencies"]} == {"not_installed"}
    assert "private" not in json.dumps(result)
    assert "secret-index" not in json.dumps(result)


def test_product_manifests_have_identical_support_input_output_and_annotations():
    entries = []
    for product, prefix in (("network", "unifi"), ("protect", "protect"), ("access", "access")):
        path = REPO_ROOT / "apps" / product / "src" / f"unifi_{product}_mcp" / "tools_manifest.json"
        manifest = json.loads(path.read_text())
        entries.append(next(tool for tool in manifest["tools"] if tool["name"] == f"{prefix}_get_support_bundle"))

    assert all(entry["schema"] == entries[0]["schema"] for entry in entries)
    assert all(entry["annotations"] == entries[0]["annotations"] for entry in entries)
    assert entries[0]["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
