"""Shared assembly and live-probe controls for sanitized support bundles."""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import platform
import sys
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from unifi_core.support_bundle import (
    ConnectionSection,
    ControllerSection,
    DependencyPackage,
    DependencySection,
    ProbeSection,
    Product,
    RuntimeSection,
    SanitizationSection,
    ServerFeatureFlag,
    ServerSection,
    SupportBundle,
    bounded_support_bundle,
    support_bundle_size,
)

ProbeName = Literal["summary", "connectivity", "resource_shape"]

LIVE_PROBE_COOLDOWN_SECONDS = 30.0
_MANIFEST_GENERATOR = "scripts/generate_tool_manifest.py"
_CONTENT_MODES = {
    "adaptive": "dual",
    "compact": "json",
    "compat": "text",
    "dual": "dual",
    "json": "json",
    "text": "text",
}
_SERVER_PACKAGES = {
    Product.NETWORK: "unifi-network-mcp",
    Product.PROTECT: "unifi-protect-mcp",
    Product.ACCESS: "unifi-access-mcp",
}
_SERVER_TOOLS = {
    Product.NETWORK: "unifi_get_support_bundle",
    Product.PROTECT: "protect_get_support_bundle",
    Product.ACCESS: "access_get_support_bundle",
}
_DEPENDENCIES = {
    Product.NETWORK: (
        DependencyPackage.AIOUNIFI,
        DependencyPackage.MCP,
        DependencyPackage.PYDANTIC,
        DependencyPackage.UNIFI_CORE,
        DependencyPackage.UNIFI_MCP_SHARED,
        DependencyPackage.UNIFI_NETWORK_MCP,
    ),
    Product.PROTECT: (
        DependencyPackage.MCP,
        DependencyPackage.PYDANTIC,
        DependencyPackage.UNIFI_CORE,
        DependencyPackage.UNIFI_MCP_SHARED,
        DependencyPackage.UNIFI_PROTECT_MCP,
        DependencyPackage.UIPROTECT,
    ),
    Product.ACCESS: (
        DependencyPackage.MCP,
        DependencyPackage.PYDANTIC,
        DependencyPackage.PY_UNIFI_ACCESS,
        DependencyPackage.UNIFI_ACCESS_MCP,
        DependencyPackage.UNIFI_CORE,
        DependencyPackage.UNIFI_MCP_SHARED,
    ),
}
_RESOURCE_EXPOSURES = {
    (Product.PROTECT, "sensors"): ("protect_list_sensors", "devices"),
}


@dataclass(frozen=True)
class SupportBundleEvidence:
    """Core-typed evidence returned by a product adapter."""

    controller: ControllerSection
    connection: ConnectionSection
    probe: ProbeSection
    sanitization: SanitizationSection


class SupportBundleAdapter(Protocol):
    """Product seam for local summaries and explicitly bounded live probes."""

    product: Product

    async def collect(self, probe: ProbeName, resource: str | None) -> SupportBundleEvidence: ...


class _LiveProbeBusy(Exception):
    pass


class _LiveProbeCooldown(Exception):
    pass


@dataclass
class LiveProbeGate:
    """One process-wide live-probe slot with per-probe/resource cooldowns."""

    cooldown_seconds: float = LIVE_PROBE_COOLDOWN_SECONDS
    monotonic: Callable[[], float] = time.monotonic
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _last_started: dict[tuple[Product, ProbeName, str | None], float] = field(default_factory=dict, init=False)

    async def run(
        self,
        key: tuple[Product, ProbeName, str | None],
        operation: Callable[[], Awaitable[SupportBundleEvidence]],
    ) -> SupportBundleEvidence:
        if self._lock.locked():
            raise _LiveProbeBusy
        async with self._lock:
            now = self.monotonic()
            previous = self._last_started.get(key)
            if previous is not None and now - previous < self.cooldown_seconds:
                raise _LiveProbeCooldown
            self._last_started[key] = now
            return await operation()


_PROCESS_LIVE_PROBE_GATE = LiveProbeGate()


def configured_filter(value: Any) -> tuple[str, ...] | None:
    """Reduce a configured comma-list/list to exact names without logging values."""
    if value in (None, "", "null"):
        return None
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        return tuple(item for item in value if item)
    return ()


def configured_transports(server_config: Any) -> tuple[str, ...]:
    """Return only configured transport enums, never bind addresses or ports."""
    transports = ["stdio"]
    http = server_config.get("http", {})
    enabled = http.get("enabled", True)
    if enabled is True or (isinstance(enabled, str) and enabled.lower() in {"true", "1", "yes", "on"}):
        transports.append(http.get("transport", "streamable-http"))
    return tuple(transports)


def fixed_manifest_reader(path: Path) -> Callable[[], Mapping[str, Any]]:
    """Build a reader for one package-owned manifest path."""

    def read() -> Mapping[str, Any]:
        value = json.loads(path.read_text())
        return value if isinstance(value, Mapping) else {}

    return read


class SupportBundleService:
    """Assemble, validate, and bound one product's support bundle."""

    def __init__(
        self,
        *,
        adapter: SupportBundleAdapter,
        registration_mode: Literal["meta_only", "lazy", "eager"],
        content_mode: str,
        transports: tuple[str, ...],
        diagnostics_enabled: bool,
        response_redaction_enabled: bool,
        manifest_reader: Callable[[], Mapping[str, Any]],
        enabled_categories: tuple[str, ...] | None = None,
        enabled_tools: tuple[str, ...] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        version_resolver: Callable[[str], str] = importlib.metadata.version,
        python_version_resolver: Callable[[], str] = platform.python_version,
        os_family_resolver: Callable[[], str] = lambda: sys.platform,
        architecture_resolver: Callable[[], str] = platform.machine,
        live_probe_gate: LiveProbeGate = _PROCESS_LIVE_PROBE_GATE,
    ) -> None:
        self._adapter = adapter
        self._registration_mode = registration_mode
        self._content_mode = content_mode
        self._transports = transports
        self._diagnostics_enabled = diagnostics_enabled
        self._response_redaction_enabled = response_redaction_enabled
        self._manifest_reader = manifest_reader
        self._enabled_categories = frozenset(enabled_categories) if enabled_categories is not None else None
        self._enabled_tools = frozenset(enabled_tools) if enabled_tools is not None else None
        self._clock = clock
        self._version_resolver = version_resolver
        self._python_version_resolver = python_version_resolver
        self._os_family_resolver = os_family_resolver
        self._architecture_resolver = architecture_resolver
        self._live_probe_gate = live_probe_gate

    async def generate(self, probe: ProbeName = "summary", resource: str | None = None) -> dict[str, Any]:
        """Return the standard tool response without exposing rejected values."""
        try:
            validation_error = self._validate_request(probe, resource)
        except Exception:
            return {"success": False, "error": "Failed to generate support bundle."}
        if validation_error is not None:
            return {"success": False, "error": validation_error}

        typed_probe = cast(ProbeName, probe)
        if typed_probe == "resource_shape" and not self._live_surface_enabled(resource):
            return {
                "success": False,
                "error": "Failed to generate support bundle: the backing read surface is disabled by configuration.",
            }

        try:
            if typed_probe == "summary":
                evidence = await self._adapter.collect(typed_probe, None)
            else:
                key = (self._adapter.product, typed_probe, resource)
                evidence = await self._live_probe_gate.run(
                    key,
                    lambda: self._adapter.collect(typed_probe, resource),
                )
            bundle = bounded_support_bundle(self._assemble(evidence))
            support_bundle_size(bundle)
        except _LiveProbeBusy:
            return {"success": False, "error": "Failed to generate support bundle: another live probe is in progress."}
        except _LiveProbeCooldown:
            return {"success": False, "error": "Failed to generate support bundle: this live probe is in cooldown."}
        except Exception:
            # Privacy boundary: never stringify or log validation, adapter, or
            # serialization exceptions because they may retain rejected input.
            return {"success": False, "error": "Failed to generate support bundle."}
        return {"success": True, "data": bundle.model_dump(mode="json")}

    def _validate_request(self, probe: object, resource: object) -> str | None:
        if probe not in {"summary", "connectivity", "resource_shape"}:
            return "Failed to generate support bundle: unsupported probe."
        if probe in {"summary", "connectivity"} and resource is not None:
            return "Failed to generate support bundle: resource is only valid for resource_shape."
        if probe == "resource_shape":
            if resource is None:
                return "Failed to generate support bundle: resource_shape requires a resource."
            if (self._adapter.product, resource) not in _RESOURCE_EXPOSURES:
                return "Failed to generate support bundle: unsupported resource for this product."
        return None

    def _live_surface_enabled(self, resource: str | None) -> bool:
        exposure = _RESOURCE_EXPOSURES[(self._adapter.product, resource)]
        tool_name, category = exposure
        if self._enabled_tools is not None and tool_name not in self._enabled_tools:
            return False
        if self._enabled_categories is not None and category not in self._enabled_categories:
            return False
        return True

    def _assemble(self, evidence: SupportBundleEvidence) -> SupportBundle:
        product = self._adapter.product
        package = _SERVER_PACKAGES[product]
        feature_flags = (
            ServerFeatureFlag.DIAGNOSTICS_ENABLED
            if self._diagnostics_enabled
            else ServerFeatureFlag.DIAGNOSTICS_DISABLED,
            ServerFeatureFlag.RESPONSE_REDACTION_ENABLED
            if self._response_redaction_enabled
            else ServerFeatureFlag.RESPONSE_REDACTION_DISABLED,
        )
        try:
            manifest_count = self._manifest_reader().get("count")
        except Exception:
            manifest_count = 0
        if not isinstance(manifest_count, int) or isinstance(manifest_count, bool) or not 0 <= manifest_count <= 10_000:
            manifest_count = 0

        dependencies = tuple(
            self._dependency(dependency) for dependency in sorted(_DEPENDENCIES[product], key=lambda item: item.value)
        )
        generated_at = self._clock().astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        return SupportBundle(
            generated_at=generated_at,
            product=product,
            server=ServerSection(
                package=package,
                version=self._server_version(package),
                tool=_SERVER_TOOLS[product],
                feature_flags=feature_flags,
            ),
            runtime=RuntimeSection(
                python_version=self._python_version_resolver(),
                os_family=_normalize_os_family(self._os_family_resolver()),
                architecture=_normalize_architecture(self._architecture_resolver()),
                transports=_normalize_transports(self._transports),
                registration_mode=self._registration_mode,
                content_mode=_normalize_content_mode(self._content_mode),
                manifest_tool_count=manifest_count,
                manifest_generator=_MANIFEST_GENERATOR,
            ),
            dependencies=dependencies,
            controller=evidence.controller,
            connection=evidence.connection,
            probe=evidence.probe,
            sanitization=evidence.sanitization,
        )

    def _resolve_version(self, package: str) -> str:
        try:
            return self._version_resolver(package)
        except Exception:
            return "not_installed"

    def _dependency(self, package: DependencyPackage) -> DependencySection:
        try:
            return DependencySection(package=package, version=self._resolve_version(package.value))
        except Exception:
            return DependencySection(package=package, version="not_installed")

    def _server_version(self, package: str) -> str:
        version = self._resolve_version(package)
        try:
            ServerSection(
                package=_SERVER_PACKAGES[self._adapter.product],
                version=version,
                tool=_SERVER_TOOLS[self._adapter.product],
            )
        except Exception:
            return "0.0.0"
        return version


def _normalize_os_family(value: str) -> Literal["linux", "macos", "windows", "other"]:
    normalized = value.lower()
    if normalized.startswith("linux"):
        return "linux"
    if normalized.startswith(("darwin", "macos")):
        return "macos"
    if normalized.startswith(("win", "cygwin", "msys")):
        return "windows"
    return "other"


def _normalize_architecture(value: str) -> Literal["x86_64", "amd64", "arm64", "aarch64", "i386", "i686", "other"]:
    normalized = value.lower()
    allowed = {"x86_64", "amd64", "arm64", "aarch64", "i386", "i686"}
    return cast(Any, normalized if normalized in allowed else "other")


def _normalize_transports(values: tuple[str, ...]) -> tuple[Literal["stdio", "streamable_http", "sse"], ...]:
    normalized = tuple("streamable_http" if value == "streamable-http" else value for value in values)
    allowed = {"stdio", "streamable_http", "sse"}
    if any(value not in allowed for value in normalized):
        raise ValueError("unsupported configured transport")
    return cast(Any, normalized)


def _normalize_content_mode(value: str) -> Literal["json", "text", "dual"]:
    try:
        return cast(Any, _CONTENT_MODES[value])
    except KeyError as exc:
        raise ValueError("unsupported content mode") from exc
