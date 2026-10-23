"""UniFi controller type detection.

Determines whether the controller is a UniFi OS appliance (UDM, UDR, etc.)
or a standalone/self-hosted Network Application. This affects API path
routing: UniFi OS uses /proxy/network/... while standalone uses /api/...
"""

import enum
import logging

import aiohttp

from unifi_core.tls import certificate_safe_middleware, safe_error_text, ssl_setting

logger = logging.getLogger(__name__)


class ControllerType(enum.Enum):
    UNIFI_OS = "proxy"
    STANDALONE = "direct"
    AUTO = "auto"

    @classmethod
    def from_config(cls, value: str) -> "ControllerType":
        mapping = {"proxy": cls.UNIFI_OS, "direct": cls.STANDALONE, "auto": cls.AUTO}
        result = mapping.get(value.lower(), cls.AUTO)
        if value.lower() not in mapping:
            logger.warning("[detection] Unknown controller type '%s', falling back to auto", value)
        return result


async def detect_controller_type_pre_login(
    host: str, port: int, verify_ssl: bool = True, timeout: float = 10.0, ssl_fingerprint: str | None = None
) -> ControllerType | None:
    """Probe the controller before login to detect type.

    Strategy:
    - GET the base URL without following redirects
    - UniFi OS returns 200 with x-csrf-token header or HTML
    - Standalone controllers redirect (301/302) to /manage

    A failed certificate check is logged as its class and fixed guidance only:
    aiohttp's text names the controller and, for a stale pin, both fingerprints.

    Returns:
        ControllerType.UNIFI_OS or ControllerType.STANDALONE if detected, None otherwise.
    """
    url = f"https://{host}:{port}"
    ssl_context = ssl_setting(verify_ssl, ssl_fingerprint)
    client_timeout = aiohttp.ClientTimeout(total=timeout)

    try:
        async with aiohttp.ClientSession(
            timeout=client_timeout, middlewares=(certificate_safe_middleware(env_prefix="NETWORK"),)
        ) as session:
            async with session.get(url, ssl=ssl_context, allow_redirects=False) as resp:
                headers = resp.headers
                if "x-csrf-token" in headers or resp.status == 200:
                    return ControllerType.UNIFI_OS
                if resp.status in (302, 301):
                    return ControllerType.STANDALONE
    except Exception as e:
        logger.debug("[detection] Pre-login probe failed: %s", safe_error_text(e, env_prefix="NETWORK"))

    return None


async def detect_controller_type_by_api_probe(
    session: aiohttp.ClientSession, host: str, port: int, verify_ssl: bool = True, ssl_fingerprint: str | None = None
) -> ControllerType | None:
    """Probe API endpoints to detect controller type (requires authenticated session).

    Tries both UniFi OS and standalone API paths for /api/self/sites.
    Returns the type corresponding to the first path that returns HTTP 200.

    Returns:
        ControllerType.UNIFI_OS or ControllerType.STANDALONE if detected, None otherwise.
    """
    url_base = f"https://{host}:{port}"
    ssl_context = ssl_setting(verify_ssl, ssl_fingerprint)

    for path, expected_type in [
        ("/proxy/network/api/self/sites", ControllerType.UNIFI_OS),
        ("/api/self/sites", ControllerType.STANDALONE),
    ]:
        try:
            async with session.get(f"{url_base}{path}", ssl=ssl_context) as resp:
                if resp.status == 200:
                    logger.info("[detection] Detected %s via %s", expected_type.name, path)
                    return expected_type
        except Exception:
            continue

    return None
