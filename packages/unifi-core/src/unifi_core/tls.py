"""TLS settings shared by the Network, Protect and Access connection managers.

A controller connection is in one of three TLS states:

* **verified** -- the certificate must chain to a trusted CA and match the host.
* **pinned** -- the leaf certificate's SHA-256 fingerprint must equal a configured
  value. CA chain and hostname are not checked, so a self-signed console keeps a
  real identity check without a CA.
* **disabled** -- no certificate check at all. Anyone on the path can present a
  certificate and read the session credentials.

:func:`ssl_setting` turns the configuration into the value aiohttp takes for
both ``TCPConnector(ssl=...)`` and per-request ``ssl=...``, so every request a
manager sends, including the unauthenticated pre-login probes, gets the same
check.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import aiohttp

from unifi_core.exceptions import UniFiConnectionError

#: What aiohttp accepts as ``ssl=``: ``True`` verifies, ``False`` disables,
#: a :class:`aiohttp.Fingerprint` pins.
SslSetting = aiohttp.Fingerprint | bool

_HEX_DIGEST = re.compile(r"[0-9a-f]{64}")


def parse_fingerprint(value: str | None) -> bytes | None:
    """Parse a SHA-256 certificate fingerprint, or return ``None`` when unset.

    Accepts 64 hex digits in either case, optionally separated by colons or
    spaces, and tolerates the ``sha256 Fingerprint=`` prefix that
    ``openssl x509 -fingerprint -sha256`` prints.

    Raises:
        ValueError: The value is set but is not a SHA-256 fingerprint. The
            message never echoes the value.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "=" in text:
        text = text.split("=", 1)[1]
    digest = re.sub(r"[\s:]", "", text).lower()
    if not _HEX_DIGEST.fullmatch(digest):
        raise ValueError(
            "SSL fingerprint must be the SHA-256 fingerprint of the controller certificate: "
            "64 hex digits, optionally colon-separated."
        )
    return bytes.fromhex(digest)


def ssl_setting(verify_ssl: bool, fingerprint: str | None = None) -> SslSetting:
    """Return the aiohttp ``ssl=`` value for a controller connection.

    A configured fingerprint wins over ``verify_ssl``: pinning is a stricter
    check than nothing and a different one from CA verification, and a console
    with a self-signed certificate can only use the pin.
    """
    digest = parse_fingerprint(fingerprint)
    if digest is not None:
        return aiohttp.Fingerprint(digest)
    return bool(verify_ssl)


def tls_mode(setting: SslSetting) -> str:
    """Name the TLS state of ``setting``: ``verified``, ``pinned`` or ``disabled``."""
    if isinstance(setting, aiohttp.Fingerprint):
        return "pinned"
    return "verified" if setting else "disabled"


def warn_if_unverified(logger: logging.Logger, setting: SslSetting, *, product: str, env_prefix: str) -> None:
    """Log one startup warning when certificate checks are disabled.

    Args:
        logger: The product logger.
        setting: The value from :func:`ssl_setting`.
        product: Display name, e.g. ``"Network"``.
        env_prefix: Server-specific env prefix, e.g. ``"NETWORK"``.
    """
    if setting is not False:
        return
    logger.warning(
        "TLS certificate verification is disabled for the UniFi %s connection: anyone on the network "
        "path can impersonate the controller and capture its credentials. Set UNIFI_%s_SSL_FINGERPRINT "
        "(or UNIFI_SSL_FINGERPRINT) to the console certificate's SHA-256 fingerprint to pin a "
        "self-signed certificate, or set UNIFI_%s_VERIFY_SSL=true if it chains to a trusted CA.",
        product,
        env_prefix,
        env_prefix,
    )


class CertificateVerificationError(UniFiConnectionError):
    """A controller request failed its certificate check.

    Carries fixed remediation text and the failing exception's class only. The
    aiohttp exception it replaces names the controller host and port, and a pin
    mismatch also both fingerprints; build it with :func:`certificate_failure`
    and raise it outside the ``except`` block so the original is not chained.
    """


def is_certificate_error(error: BaseException) -> bool:
    """Whether ``error``, or anything it was raised from, is a failed certificate check.

    Walks ``__context__`` as well as ``__cause__``: aiounifi re-raises transport
    failures as ``RequestError(...) from None``, which hides the cause but keeps
    the context.
    """
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(
            current,
            (aiohttp.ClientConnectorCertificateError, aiohttp.ServerFingerprintMismatch, CertificateVerificationError),
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def certificate_error_hint(*, env_prefix: str) -> str:
    """Fixed remediation text for a failed certificate check. Never quotes the certificate."""
    return (
        "The controller's TLS certificate failed verification. For a self-signed console certificate, "
        f"set UNIFI_{env_prefix}_SSL_FINGERPRINT (or UNIFI_SSL_FINGERPRINT) to its SHA-256 fingerprint; "
        f"if the fingerprint is already set, the certificate has changed. UNIFI_{env_prefix}_VERIFY_SSL=false "
        "disables the check entirely."
    )


def certificate_failure(error: BaseException, *, env_prefix: str) -> CertificateVerificationError:
    """Replace a failed certificate check with an error that is safe to log and return to a caller.

    The message is the exception class plus :func:`certificate_error_hint`; nothing from
    ``str(error)`` is kept.
    """
    return CertificateVerificationError(f"{type(error).__name__}: {certificate_error_hint(env_prefix=env_prefix)}")


def safe_error_text(error: BaseException, *, env_prefix: str) -> Any:
    """``error`` itself, or the fixed certificate text when it is a failed certificate check.

    For log calls that format an exception whose text is otherwise safe to
    record; a certificate failure names the controller and both fingerprints.
    """
    if is_certificate_error(error) and not isinstance(error, CertificateVerificationError):
        return certificate_failure(error, env_prefix=env_prefix)
    return error


def certificate_safe_middleware(*, env_prefix: str) -> aiohttp.ClientMiddlewareType:
    """Session middleware that replaces a failed certificate check with :class:`CertificateVerificationError`.

    Installed on every controller session so the translation happens below the
    SDKs. aiounifi, uiprotect and py-unifi-access each wrap an aiohttp
    ``ClientError`` in their own exception with the controller URL and the raw
    error in its text. :class:`CertificateVerificationError` is not a
    ``ClientError``, so it passes through them unwrapped, and it is raised
    outside the ``except`` block, so no traceback renders the original.
    """

    async def middleware(request: aiohttp.ClientRequest, handler: aiohttp.ClientHandlerType) -> aiohttp.ClientResponse:
        failure: CertificateVerificationError | None = None
        try:
            return await handler(request)
        except (aiohttp.ClientConnectorCertificateError, aiohttp.ServerFingerprintMismatch) as error:
            failure = certificate_failure(error, env_prefix=env_prefix)
        raise failure

    return middleware
