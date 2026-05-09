"""Tests for the shared bootstrap module."""

import logging

import pytest
from omegaconf import OmegaConf
from unifi_mcp_shared.bootstrap import assert_credentials_configured, validate_registration_mode


class TestValidateRegistrationMode:
    """Tests for validate_registration_mode."""

    def test_default_is_lazy(self, monkeypatch):
        monkeypatch.delenv("UNIFI_TOOL_REGISTRATION_MODE", raising=False)
        mode = validate_registration_mode(logging.getLogger("test"))
        assert mode == "lazy"

    def test_eager(self, monkeypatch):
        monkeypatch.setenv("UNIFI_TOOL_REGISTRATION_MODE", "eager")
        assert validate_registration_mode(logging.getLogger("test")) == "eager"

    def test_meta_only(self, monkeypatch):
        monkeypatch.setenv("UNIFI_TOOL_REGISTRATION_MODE", "meta_only")
        assert validate_registration_mode(logging.getLogger("test")) == "meta_only"

    def test_invalid_falls_back_to_lazy(self, monkeypatch):
        monkeypatch.setenv("UNIFI_TOOL_REGISTRATION_MODE", "invalid_mode")
        mode = validate_registration_mode(logging.getLogger("test"))
        assert mode == "lazy"

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("UNIFI_TOOL_REGISTRATION_MODE", "EAGER")
        assert validate_registration_mode(logging.getLogger("test")) == "eager"


class TestAssertCredentialsConfigured:
    """Tests for assert_credentials_configured."""

    def _cfg(self, host: str = ""):
        return OmegaConf.create({"unifi": {"host": host}})

    def test_passes_when_host_set(self):
        assert_credentials_configured(
            self._cfg("10.0.0.1"),
            plugin_name="unifi-network",
            env_prefix="NETWORK",
            logger=logging.getLogger("test"),
        )

    def test_exits_when_host_empty(self, caplog):
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            assert_credentials_configured(
                self._cfg(""),
                plugin_name="unifi-network",
                env_prefix="NETWORK",
                logger=logging.getLogger("test"),
            )
        assert exc.value.code == 5
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "unifi-network" in joined
        assert "UNIFI_NETWORK_HOST" in joined
        assert "/setup" in joined

    def test_exits_when_host_whitespace(self):
        with pytest.raises(SystemExit):
            assert_credentials_configured(
                self._cfg("   "),
                plugin_name="unifi-protect",
                env_prefix="PROTECT",
                logger=logging.getLogger("test"),
            )

    def test_exits_when_unifi_section_missing(self):
        cfg = OmegaConf.create({})
        with pytest.raises(SystemExit):
            assert_credentials_configured(
                cfg,
                plugin_name="unifi-access",
                env_prefix="ACCESS",
                logger=logging.getLogger("test"),
            )
