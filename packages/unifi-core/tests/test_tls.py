"""TLS settings: parsing, precedence, warnings, and the pin against a real handshake."""

import datetime
import hashlib
import logging
import ssl

import aiohttp
import pytest
from aiohttp import web
from unifi_core.connection import ConnectionConfig
from unifi_core.exceptions import UniFiConnectionError
from unifi_core.tls import (
    CertificateVerificationError,
    certificate_error_hint,
    certificate_failure,
    is_certificate_error,
    parse_fingerprint,
    ssl_setting,
    tls_mode,
    warn_if_unverified,
)

DIGEST = bytes(range(32))
HEX = DIGEST.hex()
COLON = ":".join(f"{b:02X}" for b in DIGEST)


class TestParseFingerprint:
    @pytest.mark.parametrize(
        "value",
        [
            HEX,
            HEX.upper(),
            COLON,
            COLON.lower(),
            f"  {COLON}\n",
            f"sha256 Fingerprint={COLON}",
            COLON.replace(":", " "),
        ],
    )
    def test_accepts_common_spellings(self, value):
        assert parse_fingerprint(value) == DIGEST

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_unset(self, value):
        assert parse_fingerprint(value) is None

    @pytest.mark.parametrize("value", [HEX[:-2], HEX + "00", "zz" * 32, hashlib.sha1(b"x").hexdigest()])
    def test_rejects_anything_but_sha256(self, value):
        with pytest.raises(ValueError, match="SHA-256") as excinfo:
            parse_fingerprint(value)
        assert value not in str(excinfo.value)


class TestSslSetting:
    def test_verify_flag(self):
        assert ssl_setting(True) is True
        assert ssl_setting(False) is False

    @pytest.mark.parametrize("verify", [True, False])
    def test_fingerprint_wins(self, verify):
        setting = ssl_setting(verify, COLON)
        assert isinstance(setting, aiohttp.Fingerprint)
        assert setting.fingerprint == DIGEST

    def test_modes(self):
        assert tls_mode(ssl_setting(True)) == "verified"
        assert tls_mode(ssl_setting(False, COLON)) == "pinned"
        assert tls_mode(ssl_setting(False)) == "disabled"

    def test_connection_config_defaults_to_verified(self):
        assert ConnectionConfig(host="192.0.2.1").ssl_context is True
        pinned = ConnectionConfig(host="192.0.2.1", verify_ssl=False, ssl_fingerprint=HEX).ssl_context
        assert isinstance(pinned, aiohttp.Fingerprint)


class TestWarning:
    def test_warns_only_when_disabled(self, caplog):
        logger = logging.getLogger("test-tls")
        with caplog.at_level(logging.WARNING, logger="test-tls"):
            warn_if_unverified(logger, True, product="Network", env_prefix="NETWORK")
            warn_if_unverified(logger, ssl_setting(False, HEX), product="Network", env_prefix="NETWORK")
        assert caplog.records == []
        with caplog.at_level(logging.WARNING, logger="test-tls"):
            warn_if_unverified(logger, False, product="Network", env_prefix="NETWORK")
        [record] = caplog.records
        assert "disabled" in record.getMessage()
        assert "UNIFI_NETWORK_SSL_FINGERPRINT" in record.getMessage()


class TestCertificateError:
    def test_found_through_from_none(self):
        """aiounifi re-raises transport failures ``from None``; the context still holds the cause."""
        mismatch = aiohttp.ServerFingerprintMismatch(DIGEST, b"\x00" * 32, "192.0.2.1", 443)
        try:
            try:
                raise mismatch
            except aiohttp.ClientError:
                raise RuntimeError("Error requesting data") from None
        except RuntimeError as wrapped:
            assert is_certificate_error(wrapped)

    def test_other_errors(self):
        assert not is_certificate_error(aiohttp.ClientConnectionError("refused"))
        assert not is_certificate_error(TimeoutError())

    def test_hint_names_the_variables(self):
        hint = certificate_error_hint(env_prefix="PROTECT")
        assert "UNIFI_PROTECT_SSL_FINGERPRINT" in hint
        assert "UNIFI_PROTECT_VERIFY_SSL=false" in hint

    def test_failure_keeps_only_the_class_and_the_hint(self):
        mismatch = aiohttp.ServerFingerprintMismatch(DIGEST, b"\xbb" * 32, "198.51.100.7", 8443)
        failure = certificate_failure(mismatch, env_prefix="NETWORK")
        assert isinstance(failure, CertificateVerificationError)
        assert isinstance(failure, UniFiConnectionError)
        assert str(failure) == f"ServerFingerprintMismatch: {certificate_error_hint(env_prefix='NETWORK')}"
        for marker in ("198.51.100.7", "8443", HEX, "bb" * 32, repr(DIGEST)):
            assert marker not in str(failure)
        assert is_certificate_error(failure)


# ---------------------------------------------------------------------------
# A real handshake against a self-signed loopback server
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def self_signed(tmp_path_factory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "unifi.test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    directory = tmp_path_factory.mktemp("tls")
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    fingerprint = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    return cert_path, key_path, fingerprint


@pytest.fixture
async def https_url(self_signed):
    cert_path, key_path, _ = self_signed
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(cert_path, key_path)

    async def ok(request):
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/", ok)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=context)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield f"https://127.0.0.1:{port}/"
    finally:
        await runner.cleanup()


async def _get(url, connector_ssl, request_ssl=True):
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=connector_ssl)) as session:
        async with session.get(url, ssl=request_ssl) as response:
            return response.status


class TestHandshake:
    async def test_default_rejects_self_signed(self, https_url):
        with pytest.raises(aiohttp.ClientConnectorCertificateError) as excinfo:
            await _get(https_url, ssl_setting(True))
        assert is_certificate_error(excinfo.value)

    async def test_pin_accepts_matching_certificate(self, https_url, self_signed):
        setting = ssl_setting(True, self_signed[2])
        assert await _get(https_url, setting, setting) == 200

    async def test_pin_rejects_other_certificate(self, https_url):
        setting = ssl_setting(True, "00" * 32)
        with pytest.raises(aiohttp.ServerFingerprintMismatch) as excinfo:
            await _get(https_url, setting, setting)
        assert is_certificate_error(excinfo.value)

    async def test_connector_pin_survives_request_without_verification(self, https_url):
        """A request that asks for ssl=False on a pinned session is still pinned.

        The Protect and Access SDKs choose per-request ``ssl`` themselves, so the
        pin they are handed through the session's connector has to hold.
        """
        with pytest.raises(aiohttp.ServerFingerprintMismatch):
            await _get(https_url, ssl_setting(True, "00" * 32), request_ssl=False)
