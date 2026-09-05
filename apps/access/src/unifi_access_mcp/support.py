"""Privacy-bounded support-bundle adapter for UniFi Access."""

from __future__ import annotations

from typing import Any

from unifi_core.support_bundle import (
    AccessCapabilities,
    ConnectionSection,
    ConnectivityProbe,
    ControllerCapabilityFlag,
    ControllerSection,
    EvidenceStatus,
    Product,
    SanitizationSection,
    SummaryProbe,
)
from unifi_mcp_shared.support_bundle import ProbeName, SupportBundleEvidence


class AccessSupportBundleAdapter:
    """Translate Access's public safe connection snapshot into Core types."""

    product = Product.ACCESS

    def __init__(self, connection_manager: Any) -> None:
        self._connection_manager = connection_manager

    async def collect(self, probe: ProbeName, resource: str | None) -> SupportBundleEvidence:
        del resource
        status = self._connection_manager.support_status()
        connected = status["connected"] is True
        developer_api_available = status["developer_api_available"] is True
        proxy_available = status["proxy_session_available"] is True
        if developer_api_available and proxy_available:
            api_surface = "mixed"
        elif developer_api_available:
            api_surface = "integration"
        elif proxy_available:
            api_surface = "controller_v2"
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
                capabilities=AccessCapabilities(
                    developer_api_available=developer_api_available,
                    proxy_session_available=proxy_available,
                    api_token_configured=status["api_token_configured"] is True,
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
