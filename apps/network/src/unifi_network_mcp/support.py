"""Privacy-bounded support-bundle adapter for UniFi Network."""

from __future__ import annotations

from typing import Any

from unifi_core.support_bundle import (
    ConnectionSection,
    ConnectivityProbe,
    ControllerCapabilityFlag,
    ControllerSection,
    EvidenceStatus,
    NetworkCapabilities,
    Product,
    SanitizationSection,
    SummaryProbe,
)
from unifi_mcp_shared.support_bundle import ProbeName, SupportBundleEvidence


class NetworkSupportBundleAdapter:
    """Translate Network's public safe connection snapshot into Core types."""

    product = Product.NETWORK

    def __init__(self, connection_manager: Any, *, integration_api_key_configured: bool) -> None:
        self._connection_manager = connection_manager
        self._integration_api_key_configured = integration_api_key_configured

    async def collect(self, probe: ProbeName, resource: str | None) -> SupportBundleEvidence:
        del resource
        status = self._connection_manager.support_status()
        connected = status["connected"] is True
        controller_type = status["controller_type"]
        session_available = status["session_available"] is True
        if session_available and self._integration_api_key_configured:
            api_surface = "mixed"
        elif session_available:
            api_surface = "controller_v2"
        elif self._integration_api_key_configured:
            api_surface = "integration"
        else:
            api_surface = "unknown"
        probe_section = (
            SummaryProbe(status=EvidenceStatus.AVAILABLE if connected else EvidenceStatus.UNAVAILABLE)
            if probe == "summary"
            else ConnectivityProbe(
                status=EvidenceStatus.UNSUPPORTED,
                duration_bucket="unknown",
                outcome="unknown",
            )
        )
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
                capabilities=NetworkCapabilities(
                    session_available=session_available,
                    integration_api_key_configured=self._integration_api_key_configured,
                    controller_type=controller_type,
                    reconnect_circuit=status["reconnect_circuit"],
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
