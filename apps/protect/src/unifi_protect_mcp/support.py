"""Privacy-bounded support-bundle adapter for UniFi Protect."""

from __future__ import annotations

from typing import Any

from unifi_core.support_bundle import (
    ConnectionSection,
    ControllerCapabilityFlag,
    ControllerSection,
    EvidenceStatus,
    Product,
    ProtectCapabilities,
    ResourceShapeProbe,
    SanitizationSection,
    SummaryProbe,
)
from unifi_mcp_shared.support_bundle import ProbeName, SupportBundleEvidence


class ProtectSupportBundleAdapter:
    """Translate Protect's public safe connection snapshot into Core types."""

    product = Product.PROTECT

    def __init__(self, connection_manager: Any) -> None:
        self._connection_manager = connection_manager

    async def collect(self, probe: ProbeName, resource: str | None) -> SupportBundleEvidence:
        status = self._connection_manager.support_status()
        connected = status["connected"] is True
        session_available = status["session_available"] is True
        api_key_configured = status["public_api_key_configured"] is True
        if session_available and api_key_configured:
            api_surface = "mixed"
        elif session_available:
            api_surface = "controller_v2"
        elif api_key_configured:
            api_surface = "integration"
        else:
            api_surface = "unknown"
        if probe == "summary":
            probe_section = SummaryProbe(status=EvidenceStatus.AVAILABLE if connected else EvidenceStatus.UNAVAILABLE)
        elif probe == "resource_shape":
            probe_section = ResourceShapeProbe(
                status=EvidenceStatus.UNSUPPORTED,
                resource="sensors",
            )
        else:
            probe_section = await self._connection_manager.support_connectivity_probe()
        return SupportBundleEvidence(
            controller=ControllerSection(
                status=EvidenceStatus.AVAILABLE if connected else EvidenceStatus.NOT_CONNECTED,
                api_surface=api_surface,
                capability_flags=(ControllerCapabilityFlag.CACHED_STATE,) if connected else (),
            ),
            connection=ConnectionSection(
                initialized=status["initialized"] is True,
                connected=connected,
                tls_verification_enabled=status["tls_verification_enabled"] is True,
                last_attempt=status["last_attempt"],
                capabilities=ProtectCapabilities(
                    session_available=session_available,
                    bootstrap_available=status["bootstrap_available"] is True,
                    public_api_key_configured=api_key_configured,
                    websocket_state=status["websocket_state"],
                ),
            ),
            probe=probe_section,
            sanitization=SanitizationSection(
                values_suppressed=False,
                dynamic_keys_suppressed=False,
                errors_normalized=True,
                variants_truncated=False,
                nodes_truncated=False,
                bytes_truncated=False,
            ),
        )
