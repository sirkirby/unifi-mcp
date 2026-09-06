import asyncio
import logging
import re
import time
import time as _time
import traceback
from collections.abc import Iterable, Mapping
from typing import Any, Dict, Optional

import aiohttp
from aiounifi.controller import Controller
from aiounifi.errors import (
    AiounifiException,
    AuthenticationRateLimitError,
    Forbidden,
    LoginRequired,
    NoPermission,
    RequestError,
    ResponseError,
    TwoFaTokenRequired,
    Unauthorized,
)
from aiounifi.models.api import ApiRequest, ApiRequestV2
from aiounifi.models.configuration import Configuration

from unifi_core.mac import mask_macs
from unifi_core.redaction import collect_secret_values, sanitize_exception, scrub_secret_values
from unifi_core.support_bundle import (
    ConnectivityProbe,
    SafeConnectionAttempt,
    connection_attempt_failed,
    connection_attempt_started,
    connection_attempt_succeeded,
    connectivity_http_outcome,
    connectivity_probe_result,
)
from unifi_core.support_transport import no_retry_support_request

logger = logging.getLogger("unifi-network-mcp")

# Auth-circuit cool-down: first terminal failure blocks reconnects for the base
# interval, doubling per consecutive failure up to the cap. Rate-limit lockouts
# clear on the controller in minutes, so the circuit half-opens instead of
# requiring a process restart.
_RECONNECT_BLOCK_BASE_SECONDS = 60.0
_RECONNECT_BLOCK_MAX_SECONDS = 900.0

# aiounifi v92 logs the complete login JSON (including password) at DEBUG.
# Keep that dependency logger at INFO even when application diagnostics use DEBUG.
_aiounifi_connectivity_logger = logging.getLogger("aiounifi.interfaces.connectivity")


if _aiounifi_connectivity_logger.level == logging.NOTSET or _aiounifi_connectivity_logger.level < logging.INFO:
    _aiounifi_connectivity_logger.setLevel(logging.INFO)


# aiounifi's ResponseError carries no status attribute. Its message is built as
# ``Call <url> received <status>[ <reason>|: <body>]`` (interfaces/connectivity.py),
# and the URL contains no whitespace, so the status is the first three-digit
# token after the first whitespace-free run following "Call ". The URL and the
# body may contain any digits and are never consulted.
_RESPONSE_STATUS_RE = re.compile(r"^Call \S+ received (\d{3})(?!\d)")


def response_status(exc: BaseException) -> Optional[int]:
    """Return the HTTP status a :class:`ResponseError` reports, else ``None``.

    aiounifi raises the same class for 404 and 429 and does not expose the
    status, so this reads the status-bearing segment of its message and only
    that segment: a 429 from a host named ``controller404.example`` is 429.
    """
    if not isinstance(exc, ResponseError):
        return None
    match = _RESPONSE_STATUS_RE.match(str(exc))
    return int(match.group(1)) if match else None


def controller_error_code(exc: BaseException) -> Optional[str]:
    """Return the ``api.err.*`` code of a controller-reported error, else ``None``.

    aiounifi raises a bare :class:`AiounifiException` carrying the decoded body
    for any ``meta.rc == "error"`` it has no specific class for, e.g.
    ``{"meta": {"rc": "error", "mac": <input>, "msg": "api.err.UnknownUser"}, "data": []}``.
    Only a bare instance qualifies (the mapped auth errors are subclasses and
    keep their ERROR logging) and only a value shaped like a code is returned:
    the body can echo request values such as a MAC, so callers log the code,
    never ``str(exc)``.
    """
    if type(exc) is not AiounifiException or not exc.args:
        return None
    body = exc.args[0]
    meta = body.get("meta") if isinstance(body, dict) else None
    msg = meta.get("msg") if isinstance(meta, dict) else None
    if not isinstance(msg, str) or not msg.startswith("api.err.") or not msg.replace(".", "").isalnum():
        return None
    return msg


async def detect_unifi_os_pre_login(
    session: aiohttp.ClientSession,
    base_url: str,
    timeout: int = 5,
) -> Optional[bool]:
    """
    Detect UniFi OS BEFORE authentication using unauthenticated probes.

    This detection determines which auth endpoint to use:
    - UniFi OS: /api/auth/login
    - Standalone: /api/login

    Strategy:
    1. GET base URL - UniFi OS returns 200 with HTML, standalone redirects or errors
    2. Check for UniFi OS specific headers/behavior

    Args:
        session: Active aiohttp.ClientSession
        base_url: Base URL of controller (e.g., 'https://192.168.1.1:443')
        timeout: Detection timeout in seconds (default: 5)

    Returns:
        True: UniFi OS detected (use /api/auth/login)
        False: Standalone controller (use /api/login)
        None: Detection inconclusive
    """
    client_timeout = aiohttp.ClientTimeout(total=timeout)

    try:
        # Probe 1: GET base URL without following redirects
        # UniFi OS typically returns 200 OK with the web UI
        # Standalone controllers often redirect to /manage or return different status
        async with session.get(base_url, timeout=client_timeout, ssl=False, allow_redirects=False) as response:
            logger.debug("Pre-login probe %s: status=%s", base_url, response.status)

            if response.status == 200:
                # UniFi OS returns 200 at base URL
                logger.debug("Pre-login detection: UniFi OS (200 at base URL)")
                return True
            elif response.status in (301, 302, 303, 307, 308):
                # Redirect typically indicates standalone controller
                location = response.headers.get("Location", "")
                logger.debug("Pre-login detection: redirect to %s", location)
                # Could be standalone redirecting to /manage
                return False

    except asyncio.TimeoutError:
        logger.debug("Pre-login detection: timeout")
    except aiohttp.ClientError as e:
        logger.debug("Pre-login detection failed: %s", e)
    except Exception as e:
        logger.debug("Pre-login detection unexpected error: %s", e)

    return None


async def detect_with_retry(
    session: aiohttp.ClientSession,
    base_url: str,
    max_retries: int = 3,
    timeout: int = 5,
    pre_login: bool = False,
) -> Optional[bool]:
    """
    Detect UniFi OS with exponential backoff retry.

    Args:
        session: Active aiohttp.ClientSession
        base_url: Base URL of controller
        max_retries: Maximum retry attempts (default: 3)
        timeout: Detection timeout per attempt in seconds (default: 5)
        pre_login: If True, use unauthenticated detection for auth endpoint selection.
                   If False, use authenticated detection for API path verification.

    Returns:
        True: UniFi OS detected
        False: Standard controller detected
        None: Detection failed after all retries

    Implementation:
        - Retries up to max_retries times
        - Uses exponential backoff: 1s, 2s, 4s, ...
        - Logs retry attempts at debug level
        - Returns None if all attempts fail
    """
    detect_func = detect_unifi_os_pre_login if pre_login else detect_unifi_os_proactively

    for attempt in range(max_retries):
        try:
            result = await detect_func(session, base_url, timeout)
            if result is not None:
                return result
        except Exception as e:
            if attempt < max_retries - 1:
                delay = 2**attempt  # Exponential backoff: 1s, 2s, 4s
                logger.debug(
                    "Detection attempt %s/%s failed: %s. Retrying in %ss...", attempt + 1, max_retries, e, delay
                )
                await asyncio.sleep(delay)
            else:
                logger.warning("Detection failed after %s attempts: %s", max_retries, e)

    return None


async def _probe_endpoint(
    session: aiohttp.ClientSession,
    url: str,
    timeout: aiohttp.ClientTimeout,
    endpoint_name: str,
) -> bool:
    """
    Probe a single UniFi endpoint to check if it responds successfully.

    Args:
        session: Active aiohttp.ClientSession for making requests
        url: Full URL to probe
        timeout: Request timeout configuration
        endpoint_name: Human-readable name for logging (e.g., "UniFi OS", "standard")

    Returns:
        True if endpoint responds with 200 and valid JSON containing "data" key
        False otherwise
    """
    try:
        logger.debug("Probing %s endpoint: %s", endpoint_name, url)

        async with session.get(url, timeout=timeout, ssl=False) as response:
            if response.status == 200:
                try:
                    data = await response.json()
                    if "data" in data:
                        logger.debug("%s endpoint responded successfully", endpoint_name)
                        return True
                except Exception as e:
                    logger.debug("%s endpoint returned 200 but invalid JSON: %s", endpoint_name, e)
    except asyncio.TimeoutError:
        logger.debug("%s endpoint probe timed out", endpoint_name)
    except aiohttp.ClientError as e:
        logger.debug("%s endpoint probe failed: %s", endpoint_name, e)
    except Exception as e:
        logger.debug("Unexpected error probing %s endpoint: %s", endpoint_name, e)

    return False


async def detect_unifi_os_proactively(
    session: aiohttp.ClientSession, base_url: str, timeout: int = 5
) -> Optional[bool]:
    """
    Detect if controller is UniFi OS by testing endpoint variants.

    Probes both UniFi OS (/proxy/network/api/self/sites) and standard
    (/api/self/sites) endpoints to empirically determine path requirement.

    Args:
        session: Active aiohttp.ClientSession for making requests
        base_url: Base URL of controller (e.g., 'https://192.168.1.1:443')
        timeout: Detection timeout in seconds (default: 5)

    Returns:
        True: UniFi OS detected (requires /proxy/network prefix)
        False: Standard controller detected (uses /api paths)
        None: Detection failed, fall back to aiounifi's check_unifi_os()

    Implementation Notes:
        - Tries UniFi OS endpoint first (newer controllers)
        - Falls back to standard endpoint if UniFi OS fails
        - Returns None if both fail (timeout, network error, etc.)
        - Per FR-012: If both succeed, prefers direct (returns False)
    """
    client_timeout = aiohttp.ClientTimeout(total=timeout)

    # Probe both endpoints
    unifi_os_url = f"{base_url}/proxy/network/api/self/sites"
    standard_url = f"{base_url}/api/self/sites"

    unifi_os_result = await _probe_endpoint(session, unifi_os_url, client_timeout, "UniFi OS")
    standard_result = await _probe_endpoint(session, standard_url, client_timeout, "standard")

    # Determine result based on probe outcomes
    if unifi_os_result and standard_result:
        # FR-012: Both succeed, prefer direct (standard)
        logger.info("Both endpoints succeeded - preferring standard (direct) paths")
        return False
    elif unifi_os_result:
        logger.info("Detected UniFi OS controller (proxy paths required)")
        return True
    elif standard_result:
        logger.info("Detected standard controller (direct paths)")
        return False
    else:
        logger.warning("Auto-detection failed - both endpoints unsuccessful")
        return None


# Free-text marker for a credential masked inside a message. Shorter than
# ``redaction.REDACTED`` because it reads inside a sentence; the payload marker
# stays on structured values, where the write-back guards look for it.
_CREDENTIAL_MASK = "<redacted>"


class ConnectionManager:
    """Manages the connection and session with the Unifi Network Controller."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 443,
        site: str = "default",
        verify_ssl: bool = False,
        cache_timeout: int = 30,
        max_retries: int = 3,
        retry_delay: int = 5,
    ):
        """Initialize the Connection Manager."""
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.site = site
        self.verify_ssl = verify_ssl
        self.cache_timeout = cache_timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self.controller: Optional[Controller] = None
        self._aiohttp_session: Optional[aiohttp.ClientSession] = None
        self._initialized = False
        self._connect_lock = asyncio.Lock()
        self._cache: Dict[str, Any] = {}
        self._last_cache_update: Dict[str, float] = {}
        self._last_connection_error: Optional[str] = None
        self._reconnect_block_error: Optional[str] = None
        self._reconnect_block_until: float = 0.0
        self._reconnect_block_count: int = 0
        self._auth_generation = 0
        self._support_attempt = SafeConnectionAttempt().model_dump(mode="json")

        # Path detection state
        self._unifi_os_override: Optional[bool] = None
        """
        Override for is_unifi_os flag:
        - None: Use aiounifi's detection (no override)
        - True: Force UniFi OS paths (/proxy/network)
        - False: Force standard paths (/api)
        """

    @property
    def url_base(self) -> str:
        proto = "https"
        return f"{proto}://{self.host}:{self.port}"

    def _sanitize_connection_error(self, error: BaseException) -> str:
        """Return a user-facing connection error without configured secrets or addresses."""
        return self._sanitize_text(str(error) or type(error).__name__)

    def _sanitize_text(self, text: str, extra_secrets: Mapping[str, bool] | Iterable[str] = ()) -> str:
        """Mask MAC addresses, the configured credentials and *extra_secrets* in *text*.

        The login is matched on token boundaries (see :meth:`_secret_rules`);
        a credential written directly against ``-`` or ``_`` is not covered by
        that rule. ``extra_secrets`` — the values the request itself submitted
        — are matched literally. Both cover the escaped forms a message can
        quote a value with, so nothing decodable reaches
        ``last_connection_error`` or a log line.
        """
        rules = self._secret_rules()
        if isinstance(extra_secrets, Mapping):
            rules.update(extra_secrets)
        else:
            rules.update(dict.fromkeys(extra_secrets, False))
        return scrub_secret_values(mask_macs(text), rules, marker=_CREDENTIAL_MASK)

    def _scrub_error(self, error: BaseException, api_request: Any = None) -> set[str]:
        """Strip credential values out of ``error`` in place before it is logged or re-raised.

        A controller error can quote the request it rejected, and a transport
        error can quote the login. Both would otherwise reach the manager log,
        any caller that formats ``str(e)`` and the API audit sink.
        Scrubs the configured login plus every value held under a sensitive
        key in the request payload, following the exception's cause chain, and
        marks them the way this manager's own credential masking does.

        Returns the secret set so the log sink can scrub the text it is about
        to write: an exception whose ``__str__`` ignores ``args`` (pydantic's
        ValidationError) passes through the rewrite untouched.
        """
        secrets = self._secret_rules(api_request)
        sanitize_exception(error, secrets, marker=_CREDENTIAL_MASK)
        return secrets

    def _secret_rules(self, api_request: Any = None) -> dict[str, bool]:
        """Every value to mask, mapped to whether it is matched on token boundaries.

        The login is word-like, so it is boundary-matched: masking "admin" as a
        substring would shred "administrator". A submitted value is opaque and
        matched wherever it appears — including when it equals the login, since
        a reused password is still the caller's value. One mapping rather than
        two passes: masking the login first would chop a longer submitted value
        that starts with it and leave the tail beside a mask the reader can
        identify.
        """
        rules = {secret: True for secret in (self.password, self.username) if secret}
        payload = None
        if api_request is not None:
            payload = getattr(api_request, "json", None) or getattr(api_request, "data", None)
        if payload is not None:
            rules.update(dict.fromkeys(collect_secret_values(payload), False))
        return rules

    def _record_connection_error(self, error: BaseException) -> str:
        self._support_attempt = connection_attempt_failed(error)
        self._last_connection_error = self._sanitize_connection_error(error)
        return self._last_connection_error

    @property
    def last_connection_error(self) -> Optional[str]:
        """Return the latest sanitized connection failure, if any."""
        return self._last_connection_error

    def _not_connected_error(self) -> ConnectionError:
        if self._last_connection_error:
            return ConnectionError(
                f"Not connected to controller: last connection attempt failed: {self._last_connection_error}"
            )
        return ConnectionError("Not connected to controller")

    @staticmethod
    def _is_terminal_auth_error(error: BaseException) -> bool:
        if isinstance(
            error,
            (
                AuthenticationRateLimitError,
                Forbidden,
                LoginRequired,
                NoPermission,
                TwoFaTokenRequired,
                Unauthorized,
            ),
        ):
            return True
        message = str(error).lower()
        if isinstance(error, RequestError):
            return "mfa" in message or "totp" in message
        if isinstance(error, ResponseError):
            return response_status(error) == 429
        return False

    def _block_automatic_reconnect(self, error: BaseException) -> str:
        """Open the auth circuit with an escalating cool-down (half-open after expiry).

        Terminal auth failures (bad credentials, 2FA required, controller login
        rate-limits) must not trigger per-request login retries — that is the
        retry-storm this circuit exists to prevent — but rate-limit lockouts and
        proxy-boot 403s clear on their own, so the block expires and the next
        caller gets one half-open attempt instead of requiring a process restart.
        """
        connection_error = self._record_connection_error(error)
        self._reconnect_block_error = connection_error
        self._reconnect_block_count += 1
        cooldown = min(
            _RECONNECT_BLOCK_BASE_SECONDS * (2 ** (self._reconnect_block_count - 1)),
            _RECONNECT_BLOCK_MAX_SECONDS,
        )
        self._reconnect_block_until = _time.monotonic() + cooldown
        self._initialized = False
        self._invalidate_cache()
        logger.error(
            "Automatic reconnect blocked after terminal authentication failure: %s. "
            "Correct the credentials or wait for the controller lockout to clear; "
            "the next reconnect attempt is allowed in %.0f seconds.",
            connection_error,
            cooldown,
        )
        return connection_error

    def _reconnect_block_active(self) -> Optional[str]:
        """Return the block error while the cool-down is running, else None."""
        if self._reconnect_block_error and _time.monotonic() < self._reconnect_block_until:
            return self._reconnect_block_error
        return None

    def _clear_reconnect_block(self) -> None:
        self._reconnect_block_error = None
        self._reconnect_block_until = 0.0
        self._reconnect_block_count = 0

    @property
    def reconnect_blocked(self) -> bool:
        """Whether the last authentication attempt failed terminally with no success since."""
        return self._reconnect_block_error is not None

    def support_status(self) -> dict[str, Any]:
        """Return local connection facts safe for a community support bundle."""
        session_available = bool(self._aiohttp_session and not self._aiohttp_session.closed)
        controller_type = "unknown"
        if self._unifi_os_override is True:
            controller_type = "proxy"
        elif self._unifi_os_override is False:
            controller_type = "direct"
        return {
            "initialized": self._initialized,
            "connected": bool(self._initialized and self.controller and session_available),
            "tls_verification_enabled": self.verify_ssl,
            "last_attempt": dict(self._support_attempt),
            "session_available": session_available,
            "controller_type": controller_type,
            "reconnect_circuit": "open" if self.reconnect_blocked else "closed",
        }

    async def support_connectivity_probe(self) -> ConnectivityProbe:
        """Perform one bounded request through the existing authenticated session."""
        session = self._aiohttp_session
        controller = self.controller
        if not self._initialized or controller is None or session is None or session.closed:
            result = connectivity_probe_result("connection", None)
            logger.info(
                "Support connectivity audit product=network outcome=%s duration=%s",
                result.outcome,
                result.duration_bucket,
            )
            return result

        is_unifi_os = self._unifi_os_override
        if is_unifi_os is None:
            is_unifi_os = bool(getattr(controller.connectivity, "is_unifi_os", False))
        path = "/proxy/network/api/self/sites" if is_unifi_os else "/api/self/sites"
        started = _time.perf_counter()
        try:
            async with session.request(
                "GET",
                f"{self.url_base}{path}",
                timeout=aiohttp.ClientTimeout(total=10),
                ssl=False if not self.verify_ssl else None,
                allow_redirects=False,
                middlewares=(no_retry_support_request,),
            ) as response:
                outcome = connectivity_http_outcome(response.status)
        except TimeoutError:
            outcome = "timeout"
        except (aiohttp.ClientError, OSError):
            outcome = "connection"
        except Exception:
            outcome = "unknown"
        result = connectivity_probe_result(outcome, (_time.perf_counter() - started) * 1000)
        logger.info(
            "Support connectivity audit product=network outcome=%s duration=%s",
            result.outcome,
            result.duration_bucket,
        )
        return result

    async def _discard_connection(self) -> None:
        if self._aiohttp_session and not self._aiohttp_session.closed:
            await self._aiohttp_session.close()
        self._aiohttp_session = None
        self.controller = None
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the controller connection (correct for attached aiounifi version)."""
        blocked = self._reconnect_block_active()
        if blocked:
            logger.error(
                "Automatic reconnect remains blocked after authentication failure: %s",
                blocked,
            )
            return False
        if self._initialized and self.controller and self._aiohttp_session and not self._aiohttp_session.closed:
            return True

        async with self._connect_lock:
            if self._reconnect_block_active():
                return False
            if self._initialized and self.controller and self._aiohttp_session and not self._aiohttp_session.closed:
                return True

            logger.info("Attempting to connect to Unifi controller at %s...", self.host)
            for attempt in range(self._max_retries):
                self._support_attempt = connection_attempt_started()
                try:
                    if self.controller:
                        self.controller = None
                    if self._aiohttp_session and not self._aiohttp_session.closed:
                        await self._aiohttp_session.close()
                        self._aiohttp_session = None

                    connector = aiohttp.TCPConnector(ssl=False if not self.verify_ssl else None)
                    self._aiohttp_session = aiohttp.ClientSession(
                        connector=connector, cookie_jar=aiohttp.CookieJar(unsafe=True)
                    )

                    # Controller type detection/override configuration
                    # Two-phase detection:
                    # 1. Pre-login: Determines auth endpoint (/api/auth/login vs /api/login)
                    # 2. Post-login: Verifies API path prefix (/proxy/network/api vs /api)
                    # See: https://github.com/sirkirby/unifi-network-mcp/issues/33
                    from unifi_core.network.controller_type import resolve_controller_type

                    UNIFI_CONTROLLER_TYPE = resolve_controller_type()

                    if UNIFI_CONTROLLER_TYPE == "proxy":
                        self._unifi_os_override = True
                        logger.info("Controller type forced to UniFi OS (proxy) via config")
                    elif UNIFI_CONTROLLER_TYPE == "direct":
                        self._unifi_os_override = False
                        logger.info("Controller type forced to standard (direct) via config")
                    elif UNIFI_CONTROLLER_TYPE == "auto":
                        # Phase 1: Pre-login detection (unauthenticated)
                        # Determines which auth endpoint to use
                        if self._unifi_os_override is None:
                            detected = await detect_with_retry(
                                self._aiohttp_session,
                                self.url_base,
                                max_retries=3,
                                timeout=5,
                                pre_login=True,  # Use unauthenticated detection
                            )
                            if detected is not None:
                                self._unifi_os_override = detected
                                mode = "UniFi OS (proxy)" if detected else "standard (direct)"
                                logger.info("Pre-login auto-detected controller type: %s", mode)
                            else:
                                # Pre-login detection inconclusive - aiounifi will try its own detection
                                # Show helpful message for troubleshooting
                                logger.warning(
                                    "Pre-login detection inconclusive, deferring to aiounifi. "
                                    "If login fails, try setting UNIFI_CONTROLLER_TYPE=proxy for UniFi OS devices."
                                )
                        else:
                            logger.debug("Using cached detection result: %s", self._unifi_os_override)

                    config = Configuration(
                        session=self._aiohttp_session,
                        host=self.host,
                        username=self.username,
                        password=self.password,
                        port=self.port,
                        site=self.site,
                        ssl_context=False if not self.verify_ssl else None,
                    )

                    self.controller = Controller(config=config)

                    # Apply pre-login detection result BEFORE login to ensure correct auth endpoint
                    # aiounifi uses /api/auth/login for UniFi OS, /api/login for standalone
                    if self._unifi_os_override is not None:
                        self.controller.connectivity.is_unifi_os = self._unifi_os_override
                        logger.debug("Pre-login is_unifi_os set to: %s", self._unifi_os_override)

                    await self.controller.login()
                    # Core owns session-expiry retries so concurrent requests share
                    # the generation-locked _reauthenticate() path below.
                    self.controller.connectivity.can_retry_login = False

                    # Phase 2: Post-login verification (authenticated)
                    # Verify API path prefix works correctly after successful login
                    if UNIFI_CONTROLLER_TYPE == "auto" and self._unifi_os_override is not None:
                        post_login_detected = await detect_with_retry(
                            self._aiohttp_session,
                            self.url_base,
                            max_retries=2,
                            timeout=5,
                            pre_login=False,  # Use authenticated detection
                        )
                        if post_login_detected is not None and post_login_detected != self._unifi_os_override:
                            # Post-login detection differs - update override
                            logger.warning(
                                "Post-login detection differs from pre-login: pre=%s, post=%s. "
                                "Using post-login result.",
                                self._unifi_os_override,
                                post_login_detected,
                            )
                            self._unifi_os_override = post_login_detected
                        elif post_login_detected is not None:
                            logger.debug("Post-login detection confirmed pre-login result")

                    self._initialized = True
                    self._auth_generation += 1
                    self._last_connection_error = None
                    self._support_attempt = connection_attempt_succeeded()
                    self._clear_reconnect_block()
                    logger.info("Successfully connected to Unifi controller at %s for site '%s'", self.host, self.site)
                    self._invalidate_cache()
                    return True

                except (
                    LoginRequired,
                    RequestError,
                    ResponseError,
                    asyncio.TimeoutError,
                    aiohttp.ClientError,
                ) as e:
                    if self._is_terminal_auth_error(e):
                        self._block_automatic_reconnect(e)
                        await self._discard_connection()
                        return False
                    connection_error = self._record_connection_error(e)
                    logger.warning("Connection attempt %s failed: %s", attempt + 1, connection_error)
                    await self._discard_connection()
                    if attempt < self._max_retries - 1:
                        await asyncio.sleep(self._retry_delay)
                    else:
                        logger.error(
                            "Failed to initialize Unifi controller after %s attempts: %s",
                            self._max_retries,
                            connection_error,
                        )
                        self._initialized = False
                        return False
                except Exception as e:
                    if self._is_terminal_auth_error(e):
                        self._block_automatic_reconnect(e)
                    else:
                        connection_error = self._record_connection_error(e)
                        logger.error(
                            "Unexpected error during controller initialization: %s",
                            connection_error,
                        )
                    await self._discard_connection()
                    return False
            return False

    async def ensure_connected(self) -> bool:
        """Ensure the controller is connected, attempting to reconnect if necessary."""

        if not self._initialized or not self.controller or not self._aiohttp_session or self._aiohttp_session.closed:
            logger.warning("Controller not initialized or session lost/closed, attempting to reconnect...")
            return await self.initialize()

        try:
            internal_session = self.controller.connectivity.config.session
            if internal_session.closed:
                logger.warning(
                    "Controller session found closed (via connectivity.config.session), attempting to reconnect..."
                )
                return await self.initialize()
        except AttributeError:
            logger.debug("connectivity.config.session attribute not found – skipping additional session check.")

        return True

    async def _reauthenticate(self, expected_generation: int) -> bool:
        """Refresh an expired controller login once, deduplicating concurrent attempts."""
        if self._reconnect_block_active():
            return False

        async with self._connect_lock:
            if self._reconnect_block_active():
                return False
            if (
                self._auth_generation != expected_generation
                and self._initialized
                and self.controller
                and self._aiohttp_session
                and not self._aiohttp_session.closed
            ):
                return True
            if not self.controller or not self._aiohttp_session or self._aiohttp_session.closed:
                return False

            try:
                await self.controller.login()
            except Exception as error:
                if self._is_terminal_auth_error(error):
                    connection_error = self._block_automatic_reconnect(error)
                else:
                    connection_error = self._record_connection_error(error)
                    logger.error("Controller re-authentication failed: %s", connection_error)
                await self._discard_connection()
                return False

            self.controller.connectivity.can_retry_login = False
            self._initialized = True
            self._auth_generation += 1
            self._last_connection_error = None
            self._support_attempt = connection_attempt_succeeded()
            self._clear_reconnect_block()
            logger.info("Controller session re-authenticated successfully")
            return True

    async def cleanup(self):
        """Clean up resources without racing initialization or reauthentication."""
        async with self._connect_lock:
            had_open_session = bool(self._aiohttp_session and not self._aiohttp_session.closed)
            await self._discard_connection()
            if had_open_session:
                logger.info("aiohttp session closed.")
            self._cache = {}
            self._last_cache_update = {}
            self._last_connection_error = None
            self._clear_reconnect_block()
            self._auth_generation = 0
            logger.info("Unifi connection manager resources cleared.")

    async def close(self) -> None:
        """Close the connection using the common manager lifecycle contract."""
        await self.cleanup()

    async def refresh_handler(self, name: str) -> Any:
        """Refresh an aiounifi handler collection, recovering an expired session.

        ``request()`` is not the only way this project reaches the controller:
        the device, client and DPI collections are refreshed through their
        aiounifi handler's own ``update()``, which builds and issues its request
        internally. ``LoginRequired`` therefore propagates past ``request()``'s
        recovery entirely, and an expired session surfaced to the caller as a
        bare 401 with no login ever attempted.

        The handler is resolved by *name* rather than passed in, so the retry
        reads it off ``self.controller`` again — the same reason ``request()``
        re-derives its request method after re-authenticating.
        """
        if not await self.ensure_connected() or not self.controller:
            raise self._not_connected_error()

        auth_generation = self._auth_generation
        try:
            return await getattr(self.controller, name).update()
        except LoginRequired:
            logger.warning("Login required detected during %s refresh, attempting explicit re-authentication...", name)
            if not await self._reauthenticate(auth_generation):
                raise
            if not self.controller:
                raise ConnectionError("Re-authentication failed, controller not available.")
            logger.info("Re-authentication successful, retrying %s refresh...", name)
            try:
                return await getattr(self.controller, name).update()
            except LoginRequired as retry_error:
                # Same terminal treatment ``request()`` applies: a second
                # LoginRequired means the refreshed session was rejected, so
                # stop here rather than let every later tool call start another
                # controller login.
                secrets = self._scrub_error(retry_error)
                logger.error(
                    "%s refresh failed even after re-authentication: %s",
                    name,
                    self._sanitize_text(str(retry_error) or type(retry_error).__name__, secrets),
                )
                self._block_automatic_reconnect(retry_error)
                await self._discard_connection()
                raise

    def _log_request_failure(
        self,
        level: int,
        what: str,
        api_request: ApiRequest | ApiRequestV2,
        detail: str,
        *,
        with_traceback: bool = False,
        secrets: Mapping[str, bool] | Iterable[str] = (),
    ) -> None:
        """Log a failed request with every address and credential masked.

        ``/stat/user/<mac>`` carries the address in the path itself and
        aiounifi repeats the URL in its error text, so the path, the detail and
        the traceback all pass through :meth:`_sanitize_text`. The traceback is
        rendered here so it passes the mask too; ``exc_info=True`` would append
        it unmasked.
        """
        if not logger.isEnabledFor(level):
            return
        message = f"{what}: %s %s - %s"
        args = [api_request.method.upper(), mask_macs(api_request.path), self._sanitize_text(detail, secrets)]
        if with_traceback:
            message += "\n%s"
            args.append(self._sanitize_text(traceback.format_exc(), secrets))
        logger.log(level, message, *args)

    @staticmethod
    def _rejection_level(api_request: ApiRequest | ApiRequestV2) -> int:
        """A controller's negative answer is routine on a read, worth a warning on a write."""
        return logging.INFO if api_request.method.lower() == "get" else logging.WARNING

    async def request(self, api_request: ApiRequest | ApiRequestV2, return_raw: bool = False) -> Any:
        """Make a request to the controller API, handling raw responses."""
        if not await self.ensure_connected() or not self.controller:
            raise self._not_connected_error()

        # Apply override if we have better detection (FR-003: use cached detection)
        original_controller = self.controller
        original_is_unifi_os = None
        if self._unifi_os_override is not None:
            original_is_unifi_os = original_controller.connectivity.is_unifi_os
            if original_is_unifi_os != self._unifi_os_override:
                logger.debug(
                    "Overriding is_unifi_os from %s to %s for this request",
                    original_is_unifi_os,
                    self._unifi_os_override,
                )
                original_controller.connectivity.is_unifi_os = self._unifi_os_override

        auth_generation = self._auth_generation
        request_method = self.controller.connectivity._request if return_raw else self.controller.request

        try:
            # Diagnostics: capture timing and payloads without leaking secrets
            start_ts = _time.perf_counter()
            response = await request_method(api_request)
            duration_ms = (_time.perf_counter() - start_ts) * 1000.0
            try:
                from unifi_core.diagnostics import diagnostics_enabled, log_api_request

                if diagnostics_enabled():
                    payload = getattr(api_request, "json", None) or getattr(api_request, "data", None)
                    log_api_request(
                        api_request.method,
                        api_request.path,
                        payload,
                        response,
                        duration_ms,
                        True,
                    )
            except Exception:
                pass
            return response if return_raw else response.get("data")

        except LoginRequired as e:
            # Bound and scrubbed even though this branch does not re-raise it:
            # both exits below leave it as ``__context__`` of the error the
            # caller receives, and every ``exc_info=True`` caller renders that
            # chain in full. ``args[0]`` is the decoded response, which echoes
            # the submitted record on a rejected write.
            self._scrub_error(e, api_request)
            logger.warning("Login required detected during request, attempting explicit re-authentication...")
            if await self._reauthenticate(auth_generation):
                if not self.controller:
                    raise ConnectionError("Re-authentication failed, controller not available.")
                logger.info("Re-authentication successful, retrying original request...")
                request_method = self.controller.connectivity._request if return_raw else self.controller.request
                try:
                    start_ts = _time.perf_counter()
                    retry_response = await request_method(api_request)
                    duration_ms = (_time.perf_counter() - start_ts) * 1000.0
                    try:
                        from unifi_core.diagnostics import diagnostics_enabled, log_api_request

                        if diagnostics_enabled():
                            payload = getattr(api_request, "json", None) or getattr(api_request, "data", None)
                            log_api_request(
                                api_request.method,
                                api_request.path,
                                payload,
                                retry_response,
                                duration_ms,
                                True,
                            )
                    except Exception:
                        pass
                    return retry_response if return_raw else retry_response.get("data")
                except Exception as retry_e:
                    secrets = self._scrub_error(retry_e, api_request)
                    retry_error = str(retry_e) or type(retry_e).__name__
                    self._log_request_failure(
                        logging.ERROR,
                        "API request failed even after re-authentication",
                        api_request,
                        retry_error,
                        secrets=secrets,
                    )
                    # A second LoginRequired means the refreshed session was not
                    # accepted. Treat it as terminal so later tool calls cannot
                    # generate another controller-login storm. Other endpoint
                    # permission/rate-limit failures remain scoped to that endpoint.
                    if isinstance(retry_e, LoginRequired):
                        self._block_automatic_reconnect(retry_e)
                        await self._discard_connection()
                    raise retry_e from None
            else:
                raise self._not_connected_error()
        except (RequestError, ResponseError, aiohttp.ClientError) as e:
            # Classify before scrubbing: the scrub rewrites the message in
            # place, and a submitted value that collides with the status text
            # would otherwise change how the reply is read.
            status = response_status(e)
            secrets = self._scrub_error(e, api_request)
            if status == 404:
                # The controller answered: it does not serve this path. That is
                # a negative reply the caller interprets, not a transport fault.
                self._log_request_failure(
                    self._rejection_level(api_request), "Controller answered 404", api_request, str(e), secrets=secrets
                )
            else:
                self._log_request_failure(logging.ERROR, "API request error", api_request, str(e), secrets=secrets)
            try:
                from unifi_core.diagnostics import diagnostics_enabled, log_api_request

                if diagnostics_enabled():
                    payload = getattr(api_request, "json", None) or getattr(api_request, "data", None)
                    log_api_request(
                        api_request.method,
                        api_request.path,
                        payload,
                        {"error": str(e)},
                        0.0,
                        False,
                    )
            except Exception:
                pass
            raise
        except Exception as e:
            # Classified before the scrub, for the same reason as above.
            code = controller_error_code(e)
            secrets = self._scrub_error(e, api_request)
            if code is not None:
                # A controller-reported api.err.* is a negative reply, not an
                # operator event: routine on a read (an unknown MAC on a
                # per-MAC lookup), worth a warning on a write. The body can
                # echo request values, so only the code is logged.
                self._log_request_failure(
                    self._rejection_level(api_request),
                    "Controller rejected request",
                    api_request,
                    code,
                    secrets=secrets,
                )
            else:
                self._log_request_failure(
                    logging.ERROR,
                    "Unexpected error during API request",
                    api_request,
                    str(e),
                    with_traceback=True,
                    secrets=secrets,
                )
            try:
                from unifi_core.diagnostics import diagnostics_enabled, log_api_request

                if diagnostics_enabled():
                    payload = getattr(api_request, "json", None) or getattr(api_request, "data", None)
                    log_api_request(
                        api_request.method,
                        api_request.path,
                        payload,
                        {"error": str(e)},
                        0.0,
                        False,
                    )
            except Exception:
                pass
            raise
        finally:
            # Always restore original value (FR-003: maintain session state)
            if (
                original_is_unifi_os is not None
                and self.controller is original_controller
                and self.controller is not None
            ):
                original_controller.connectivity.is_unifi_os = original_is_unifi_os

    # --- Cache Management ---

    def _update_cache(self, key: str, data: Any, timeout: Optional[int] = None):
        """Update the cache with new data."""
        self._cache[key] = data
        self._last_cache_update[key] = time.time()
        logger.debug("Cache updated for key '%s' with timeout %ss", key, timeout or self.cache_timeout)

    def _is_cache_valid(self, key: str, timeout: Optional[int] = None) -> bool:
        """Check if the cache for a given key is still valid."""
        if key not in self._cache or key not in self._last_cache_update:
            return False

        effective_timeout = timeout if timeout is not None else self.cache_timeout
        current_time = time.time()
        last_update = self._last_cache_update[key]

        is_valid = (current_time - last_update) < effective_timeout
        logger.debug(
            "Cache check for key '%s': %s (Timeout: %ss)", key, "Valid" if is_valid else "Expired", effective_timeout
        )
        return is_valid

    def get_cached(self, key: str, timeout: Optional[int] = None) -> Optional[Any]:
        """Get data from cache if valid."""
        if self._is_cache_valid(key, timeout):
            logger.debug("Cache hit for key '%s'", key)
            return self._cache[key]
        logger.debug("Cache miss for key '%s'", key)
        return None

    def _invalidate_cache(self, prefix: Optional[str] = None):
        """Invalidate cache entries, optionally by prefix."""
        if prefix:
            keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
            for key in keys_to_remove:
                del self._cache[key]
                if key in self._last_cache_update:
                    del self._last_cache_update[key]
            logger.debug("Invalidated cache for keys starting with '%s'", prefix)
        else:
            self._cache = {}
            self._last_cache_update = {}
            logger.debug("Invalidated entire cache")

    async def set_site(self, site: str):
        """Update the target site and invalidate relevant cache.

        Note: This attempts a dynamic switch. Full stability might require
        re-initializing the connection manager or restarting the server.
        """
        if self.controller and hasattr(self.controller.connectivity, "config"):
            self.controller.connectivity.config.site = site
            self.site = site
            self._invalidate_cache()
            logger.info("Switched target site to '%s'. Cache invalidated. Re-login might occur on next request.", site)
        else:
            logger.warning("Cannot set site dynamically, controller or config not available.")
