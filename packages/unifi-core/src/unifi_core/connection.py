"""Base async connection primitives for UniFi controllers."""

from dataclasses import dataclass

import aiohttp  # noqa: F401

from unifi_core.tls import SslSetting, ssl_setting


@dataclass
class ConnectionConfig:
    host: str
    port: int = 443
    verify_ssl: bool = True
    timeout: float = 30.0
    ssl_fingerprint: str | None = None

    @property
    def url_base(self) -> str:
        return f"https://{self.host}:{self.port}"

    @property
    def ssl_context(self) -> SslSetting:
        """The aiohttp ``ssl=`` value; a fingerprint pins (see :mod:`unifi_core.tls`)."""
        return ssl_setting(self.verify_ssl, self.ssl_fingerprint)
