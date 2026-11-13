"""HTTP client for the UniFi Site Manager API.

Credential and destination rules, which the rest of the package relies on:

* The destination is :data:`SITE_MANAGER_API_ORIGIN`. It is not configurable
  from the environment or a config file, so a Site Manager key can only ever
  be sent to Ubiquiti. Tests pass ``base_url`` to the constructor.
* Redirects are never followed and proxy settings from the environment are
  ignored: either would let something other than this module choose where the
  key goes.
* Transport exceptions are never re-raised or chained. aiohttp errors carry
  the request, headers included; every error raised here is built from fixed
  text, the HTTP status and the upstream trace id.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import aiohttp
from yarl import URL

from unifi_core.exceptions import (
    UniFiAuthError,
    UniFiConnectionError,
    UniFiMalformedResponseError,
    UniFiNotFoundError,
    UniFiOperationError,
    UniFiPermissionError,
    UniFiRateLimitError,
    UniFiValidationError,
)

logger = logging.getLogger(__name__)

SITE_MANAGER_API_ORIGIN = "https://api.ui.com"
API_KEY_ENV_VAR = "UNIFI_SITEMANAGER_API_KEY"

DEFAULT_TIMEOUT_SECONDS = 30.0
# Longest total time one call may spend waiting out 429 responses.
DEFAULT_RATE_LIMIT_WAIT_SECONDS = 10.0
_MAX_RATE_LIMIT_RETRIES = 2
_MAX_ID_LENGTH = 256
_UNSAFE_SEGMENT = re.compile(r"[/?#%\\\s\x00-\x1f\x7f]")
_UPSTREAM_MESSAGE_LIMIT = 200
_LOG_ROUTES = (
    (r"/v1/hosts", "/v1/hosts"),
    (r"/v1/hosts/[^/]+", "/v1/hosts/{id}"),
    (r"/v1/sites", "/v1/sites"),
    (r"/v1/devices", "/v1/devices"),
    (r"/v1/isp-metrics/(?:5m|1h)", "/v1/isp-metrics/{metric_type}"),
    (r"/v1/isp-metrics/(?:5m|1h)/query", "/v1/isp-metrics/{metric_type}/query"),
    (r"/v1/sd-wan-configs", "/v1/sd-wan-configs"),
    (r"/v1/sd-wan-configs/[^/]+", "/v1/sd-wan-configs/{id}"),
    (r"/v1/sd-wan-configs/[^/]+/status", "/v1/sd-wan-configs/{id}/status"),
)


def _log_route(path: str) -> str:
    """Return fixed route vocabulary only, including for unknown paths and queries."""
    route = path.partition("?")[0].partition("#")[0]
    for pattern, template in _LOG_ROUTES:
        if re.fullmatch(pattern, route):
            return template
    return "/{unknown}"


class SiteManagerNotConfiguredError(UniFiAuthError):
    """No Site Manager API key is configured."""


class SiteManagerHttpError(UniFiOperationError):
    """The Site Manager API answered with a status this client does not map to a narrower error."""

    def __init__(self, message: str, *, status: int, code: str | None = None, trace_id: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.trace_id = trace_id


@dataclass(frozen=True, slots=True)
class SiteManagerResponse:
    """The parts of a Site Manager response envelope a manager reads."""

    data: Any
    next_token: str | None = None
    trace_id: str | None = None


def path_segment(value: Any, kind: str) -> str:
    """Return ``value`` percent-encoded for use as exactly one URL path segment.

    Site Manager ids are opaque and contain characters such as ``:``, so they
    are encoded rather than restricted to an alphabet. Separators, dot
    segments, existing percent-encoding and control characters are refused: an
    id must not be able to address a different resource. The rejected value is
    not echoed.
    """
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_ID_LENGTH
        or value in {".", ".."}
        or _UNSAFE_SEGMENT.search(value)
    ):
        raise UniFiValidationError(f"Invalid {kind} id")
    return quote(value, safe="")


class SiteManagerConnectionManager:
    """Sends authenticated requests to the Site Manager API."""

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = SITE_MANAGER_API_ORIGIN,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        rate_limit_wait_seconds: float = DEFAULT_RATE_LIMIT_WAIT_SECONDS,
    ) -> None:
        self._api_key = api_key.strip() if isinstance(api_key, str) else ""
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._rate_limit_wait_seconds = max(0.0, rate_limit_wait_seconds)
        self._session: aiohttp.ClientSession | None = None

    @property
    def configured(self) -> bool:
        """Whether an API key is available. Says nothing about whether it is valid."""
        return bool(self._api_key)

    async def initialize(self) -> bool:
        """Report whether the client is configured. Makes no network request."""
        return self.configured

    async def close(self) -> None:
        session, self._session = self._session, None
        if session is not None and not session.closed:
            await session.close()

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout, trust_env=False)
        return self._session

    async def get(
        self,
        path: str,
        *,
        params: list[tuple[str, str]] | None = None,
        resource: tuple[str, str] | None = None,
    ) -> SiteManagerResponse:
        """GET ``path``. ``resource`` names what a 404 refers to, as ``(type, id)``."""
        return await self._request("GET", path, params=params, resource=resource)

    async def post(
        self,
        path: str,
        *,
        json_body: dict[str, Any],
        resource: tuple[str, str] | None = None,
    ) -> SiteManagerResponse:
        """POST ``path``. Never retried: a rate-limited POST reports the wait instead."""
        return await self._request("POST", path, json_body=json_body, resource=resource)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: list[tuple[str, str]] | None = None,
        json_body: dict[str, Any] | None = None,
        resource: tuple[str, str] | None = None,
    ) -> SiteManagerResponse:
        if not self.configured:
            raise SiteManagerNotConfiguredError(
                f"No Site Manager API key is configured. Set {API_KEY_ENV_VAR} to a key created at "
                "unifi.ui.com > Settings > API Keys."
            )
        url = self._url(path)
        if params:
            url = url.with_query(params)
        headers = {"X-API-Key": self._api_key, "Accept": "application/json"}
        deadline = time.monotonic() + self._rate_limit_wait_seconds
        attempt = 0
        while True:
            attempt += 1
            status, retry_after, payload = await self._send(method, path, url, headers, json_body)
            if status != 429:
                return _interpret(status, payload, resource, secret=self._api_key)
            wait = _retry_after_seconds(retry_after)
            can_retry = (
                method == "GET"
                and attempt <= _MAX_RATE_LIMIT_RETRIES
                and wait is not None
                and time.monotonic() + wait <= deadline
            )
            if not can_retry:
                hint = f" Retry after {int(wait)} seconds." if wait is not None else ""
                raise UniFiRateLimitError(f"Site Manager API rate limit reached.{hint}")
            logger.info("Site Manager rate limit on %s %s; retrying in %.1fs", method, _log_route(path), wait)
            await asyncio.sleep(wait)

    def _url(self, path: str) -> URL:
        """Join ``path`` to the base URL, refusing any path that would change the destination.

        A path that does not start with ``/`` can turn the host into userinfo
        (``https://api.ui.com@other.example/``), which would send the key
        elsewhere without a redirect.
        """
        if not isinstance(path, str) or not path.startswith("/") or "\\" in path:
            raise UniFiValidationError("Site Manager request path must be root-relative")
        url = URL(self._base_url + path, encoded=True)
        if url.origin() != URL(self._base_url).origin():
            raise UniFiValidationError("Site Manager request path must be root-relative")
        return url

    async def _send(
        self,
        method: str,
        path: str,
        url: URL,
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
    ) -> tuple[int, str | None, Any]:
        """Send one request and return ``(status, Retry-After, decoded JSON or None)``."""
        try:
            async with self._get_session().request(
                method, url, headers=headers, json=json_body, allow_redirects=False
            ) as response:
                status = response.status
                retry_after = response.headers.get("Retry-After")
                try:
                    payload = await response.json(content_type=None)
                except (ValueError, aiohttp.ClientError):
                    payload = None
                return status, retry_after, payload
        except asyncio.TimeoutError:
            failure = "timed out"
        except aiohttp.ClientError as exc:
            # Name the class only: the exception text and its request_info can carry the key.
            failure = f"failed ({type(exc).__name__})"
        logger.warning("Site Manager request %s %s %s", method, _log_route(path), failure)
        raise UniFiConnectionError(f"Site Manager API request {failure}.") from None


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if 0 <= seconds < 3600 else None


def _upstream_text(payload: Any, key: str) -> str | None:
    if isinstance(payload, dict) and isinstance(payload.get(key), str) and payload[key]:
        return payload[key]
    return None


def _scrub(text: str | None, secret: str) -> str | None:
    return text.replace(secret, "[redacted]") if text and secret else text


def _interpret(status: int, payload: Any, resource: tuple[str, str] | None, *, secret: str = "") -> SiteManagerResponse:
    # Upstream text reaches the caller in error messages, so a key echoed back
    # in any of it is removed first.
    trace_id = _scrub(_upstream_text(payload, "traceId"), secret)
    code = _scrub(_upstream_text(payload, "code"), secret)
    suffix = f" (trace {trace_id})" if trace_id else ""
    if status == 200:
        if not isinstance(payload, dict) or "data" not in payload:
            raise UniFiMalformedResponseError(f"Site Manager API returned an unreadable response{suffix}.")
        return SiteManagerResponse(
            data=payload["data"], next_token=_upstream_text(payload, "nextToken"), trace_id=trace_id
        )
    if 300 <= status < 400:
        raise UniFiConnectionError(f"Site Manager API answered with an unexpected redirect ({status}); not followed.")
    if status == 401:
        raise UniFiAuthError(
            f"Site Manager API rejected the API key (401). Check that {API_KEY_ENV_VAR} holds a current key "
            f"from unifi.ui.com > Settings > API Keys{suffix}."
        )
    if status == 403:
        raise UniFiPermissionError(
            "Site Manager API refused this request (403). The API key may lack the Site Manager scope, "
            f"or the account may not have access to the requested resource{suffix}."
        )
    if status == 404 and resource is not None:
        raise UniFiNotFoundError(resource[0], resource[1])
    if status == 400:
        message = _scrub(_upstream_text(payload, "message"), secret)
        detail = f": {message[:_UPSTREAM_MESSAGE_LIMIT]}" if message else ""
        raise UniFiValidationError(f"Site Manager API rejected the request (400){detail}{suffix}")
    raise SiteManagerHttpError(
        f"Site Manager API error ({status}){suffix}.", status=status, code=code, trace_id=trace_id
    )
