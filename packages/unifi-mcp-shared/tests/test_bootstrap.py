"""Tests for the shared bootstrap module."""

import logging
import os

import pytest
from omegaconf import OmegaConf
from unifi_mcp_shared.bootstrap import (
    assert_credentials_configured,
    load_server_config,
    resolve_env,
    validate_registration_mode,
)


class TestValidateRegistrationMode:
    """Tests for validate_registration_mode."""

    @pytest.mark.parametrize(
        ("env_val", "expected"),
        [
            (None, "lazy"),
            ("eager", "eager"),
            ("meta_only", "meta_only"),
            ("invalid_mode", "lazy"),
            ("EAGER", "eager"),
        ],
    )
    def test_validate_registration_mode(self, monkeypatch, env_val, expected):
        if env_val is None:
            monkeypatch.delenv("UNIFI_TOOL_REGISTRATION_MODE", raising=False)
        else:
            monkeypatch.setenv("UNIFI_TOOL_REGISTRATION_MODE", env_val)
        assert validate_registration_mode(logging.getLogger("test")) == expected


class TestAssertCredentialsConfigured:
    """Tests for assert_credentials_configured."""

    @pytest.mark.parametrize(
        "cfg_dict",
        [
            {"unifi": {"host": ""}},
            {"unifi": {"host": "   "}},
            {},
        ],
    )
    def test_exits_when_host_missing_or_blank(self, caplog, cfg_dict):
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            assert_credentials_configured(
                OmegaConf.create(cfg_dict),
                plugin_name="unifi-network",
                env_prefix="NETWORK",
                logger=logging.getLogger("test"),
            )
        assert exc.value.code == 5
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "unifi-network" in joined
        assert "UNIFI_NETWORK_HOST" in joined
        assert "unifi-network-setup skill" in joined


class TestResolveEnv:
    """Tests for resolve_env: plain and _FILE spellings."""

    _ALL = [
        f"UNIFI_{p}{k}{s}"
        for p in ("NETWORK_", "")
        for k in ("PASSWORD", "API_KEY", "PORT")
        for s in ("", "_FILE", "_COMMAND")
    ]

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for var in self._ALL:
            monkeypatch.delenv(var, raising=False)

    def _resolve(self, key="password", prefix="NETWORK"):
        return resolve_env(key, env_prefix=prefix, logger=logging.getLogger("test"))

    def test_non_secret_key_ignores_file_spelling(self, monkeypatch, tmp_path):
        (tmp_path / "port").write_text("8443")
        monkeypatch.setenv("UNIFI_NETWORK_PORT_FILE", str(tmp_path / "port"))
        monkeypatch.setenv("UNIFI_PORT", "443")
        assert self._resolve("port") == "443"

    @pytest.mark.parametrize(
        ("raw_bytes", "expected"),
        [
            (b" a b\r\n", " a b"),
            (b"\xef\xbb\xbfhunter2\n", "hunter2"),
            (b"pw\n\n\n", "pw"),
        ],
    )
    def test_file_contents_whitespace_bom_and_newlines(self, monkeypatch, tmp_path, raw_bytes, expected):
        secret = tmp_path / "pw"
        secret.write_bytes(raw_bytes)
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(secret))
        assert self._resolve() == expected

    def test_file_path_expands_user(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "pw").write_text("home-secret")
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", "~/pw")
        assert self._resolve() == "home-secret"

    @pytest.mark.parametrize(
        ("path_kind", "expected_msg"),
        [
            ("absent", "does not exist"),
            ("bad_home", "UNIFI_NETWORK_PASSWORD_FILE"),
            ("dir", "UNIFI_NETWORK_PASSWORD_FILE"),
        ],
    )
    def test_invalid_secret_file_path_refuses_to_start(self, monkeypatch, tmp_path, caplog, path_kind, expected_msg):
        if path_kind == "absent":
            target = str(tmp_path / "absent")
        elif path_kind == "bad_home":
            target = "~nosuchuser_xyz_123/pw"
        else:
            target = str(tmp_path)
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", target)
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "UNIFI_NETWORK_PASSWORD_FILE" in caplog.text
        assert expected_msg in caplog.text

    @pytest.mark.parametrize(
        "raw_bytes",
        [
            b"\n",
            b"p\xe4ss\n",
            b"line-one\nline-two\n",
            b"x" * (64 * 1024 + 1),
        ],
    )
    def test_invalid_secret_file_contents_refuse_to_start(self, monkeypatch, tmp_path, caplog, raw_bytes):
        secret = tmp_path / "pw"
        secret.write_bytes(raw_bytes)
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(secret))
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "UNIFI_NETWORK_PASSWORD_FILE" in caplog.text
        assert "line-one" not in caplog.text

    def test_empty_shared_non_secret_value_counts_as_unset(self, monkeypatch):
        assert self._resolve() is None
        monkeypatch.setenv("UNIFI_PORT", "")
        assert self._resolve("port") is None

    def test_indirection_from_dotenv_is_refused_when_snapshot_taken(self, monkeypatch, tmp_path, caplog):
        # Simulate: process started without the variable, then a .env in the cwd set it.
        from unifi_mcp_shared import bootstrap

        monkeypatch.setattr(bootstrap, "_TRUSTED_VARS", frozenset({"UNIFI_NETWORK_HOST"}))
        secret = tmp_path / "pw"
        secret.write_text("dotenv-pointed-here\n")
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(secret))
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "dotenv-pointed-here" not in caplog.text
        assert "UNIFI_NETWORK_PASSWORD_FILE" in caplog.text
        assert ".env" in caplog.text

    def test_indirection_from_process_env_is_honoured_when_snapshot_taken(self, monkeypatch, tmp_path):
        from unifi_mcp_shared import bootstrap

        (tmp_path / "pw").write_text("trusted\n")
        monkeypatch.setattr(bootstrap, "_TRUSTED_VARS", frozenset({"UNIFI_NETWORK_PASSWORD_FILE"}))
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(tmp_path / "pw"))
        assert self._resolve() == "trusted"

    def test_plain_value_from_dotenv_is_still_accepted(self, monkeypatch):
        # Only the indirection is gated; a .env may still carry the value itself.
        from unifi_mcp_shared import bootstrap

        monkeypatch.setattr(bootstrap, "_TRUSTED_VARS", frozenset())
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD", "from-dotenv")
        assert self._resolve() == "from-dotenv"

    def test_snapshot_process_env_records_current_names_once(self, monkeypatch):
        from unifi_mcp_shared import bootstrap

        monkeypatch.setattr(bootstrap, "_TRUSTED_VARS", None)
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", "/nonexistent")
        bootstrap.snapshot_process_env()
        monkeypatch.setenv("UNIFI_NETWORK_API_KEY_FILE", "/nonexistent")
        bootstrap.snapshot_process_env()  # second call must not widen the snapshot
        assert "UNIFI_NETWORK_PASSWORD_FILE" in bootstrap._TRUSTED_VARS
        assert "UNIFI_NETWORK_API_KEY_FILE" not in bootstrap._TRUSTED_VARS

    def test_plain_value_is_returned_unchanged(self, monkeypatch):
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD", "  p@ss  ")
        assert self._resolve() == "  p@ss  "

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
    def test_group_or_world_readable_file_logs_a_warning(self, monkeypatch, tmp_path, caplog):
        secret = tmp_path / "pw"
        secret.write_text("s\n")
        secret.chmod(0o644)
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(secret))
        with caplog.at_level(logging.WARNING):
            assert self._resolve() == "s"
        assert "UNIFI_NETWORK_PASSWORD_FILE" in caplog.text
        assert "0644" in caplog.text

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
    def test_owner_only_file_logs_no_warning(self, monkeypatch, tmp_path, caplog):
        secret = tmp_path / "pw"
        secret.write_text("s\n")
        secret.chmod(0o600)
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(secret))
        with caplog.at_level(logging.WARNING):
            assert self._resolve() == "s"
        assert caplog.text == ""

    def test_two_spellings_at_one_level_are_refused_as_ambiguous(self, monkeypatch, tmp_path, caplog):
        """Both names are logged, the .env-supplied one tagged, and neither value."""
        from unifi_mcp_shared import bootstrap

        (tmp_path / "pw").write_text("x")
        monkeypatch.setattr(bootstrap, "_TRUSTED_VARS", frozenset({"UNIFI_NETWORK_PASSWORD_FILE"}))
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD", "plain")  # left over in a copied .env
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(tmp_path / "pw"))
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "UNIFI_NETWORK_PASSWORD (from a .env file)" in caplog.text
        assert "UNIFI_NETWORK_PASSWORD_FILE" in caplog.text
        assert "UNIFI_NETWORK_PASSWORD_FILE (from a .env file)" not in caplog.text
        assert "plain" not in caplog.text

    @pytest.mark.parametrize(
        ("file_var", "plain_var", "plain_val", "expected"),
        [
            ("UNIFI_NETWORK_PASSWORD_FILE", "UNIFI_PASSWORD", "shared-plain", "from-file"),
            ("UNIFI_PASSWORD_FILE", "UNIFI_NETWORK_PASSWORD", "", "from-file"),
        ],
    )
    def test_server_and_shared_env_precedence(self, monkeypatch, tmp_path, file_var, plain_var, plain_val, expected):
        (tmp_path / "pw").write_text("from-file")
        monkeypatch.setenv(file_var, str(tmp_path / "pw"))
        monkeypatch.setenv(plain_var, plain_val)
        assert self._resolve() == expected


class TestLoadServerConfigSecrets:
    """load_server_config resolves password/api_key through the secret resolver."""

    # Every variable the default ``keys`` tuple of load_server_config can read, so a
    # developer's real UNIFI_* environment cannot leak into these tests.
    _VARS = [
        f"UNIFI_{p}{k.upper()}{s}"
        for p in ("NETWORK_", "")
        for k in ("host", "username", "password", "port", "site", "verify_ssl", "api_key")
        for s in ("", "_FILE", "_COMMAND")
    ]

    @pytest.fixture(autouse=True)
    def _isolated(self, monkeypatch, tmp_path):
        for var in self._VARS:
            monkeypatch.delenv(var, raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text('unifi:\n  host: ""\n  username: ""\n  password: ""\n  api_key: ""\n')
        monkeypatch.setenv("CONFIG_PATH", str(cfg))
        self.tmp_path = tmp_path

    def _load(self):
        return load_server_config(
            package_name="unifi_mcp_shared",
            env_prefix="NETWORK",
            logger=logging.getLogger("test"),
        )

    def test_api_key_file_reaches_config(self, monkeypatch):
        (self.tmp_path / "key").write_text("api-key-value\n")
        monkeypatch.setenv("UNIFI_NETWORK_API_KEY_FILE", str(self.tmp_path / "key"))
        assert self._load().unifi.api_key == "api-key-value"

    @pytest.mark.parametrize(
        "secret",
        [
            "p${a}ss-${oc.env:HOME}",
            r"p\${a}ss",
            r"a\\${b}",
            r"\${oc.env:HOME}",
            r"C:\Users\x",
            r"C:\Users\x${y}",
            r"a\b${c}",
            "pw${a}\\",
            "x\\",
            "????",
        ],
    )
    def test_secret_round_trips_through_omegaconf(self, monkeypatch, secret):
        (self.tmp_path / "pw").write_text(secret + "\n")
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(self.tmp_path / "pw"))
        assert self._load().unifi.password == secret

    def test_secret_equal_to_omegaconf_missing_marker_is_refused(self, monkeypatch, caplog):
        # "???" is OmegaConf's missing-value marker and would silently become "".
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD", "???")
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._load()
        assert exc.value.code == 6

    def test_non_secret_env_value_is_not_interpolated(self, monkeypatch):
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD", "hunter2")
        monkeypatch.setenv("UNIFI_NETWORK_SITE", "${oc.env:UNIFI_NETWORK_PASSWORD}")
        assert self._load().unifi.site == "${oc.env:UNIFI_NETWORK_PASSWORD}"

    def test_empty_non_secret_env_leaves_yaml_literal_in_place(self, monkeypatch):
        cfg = self.tmp_path / "config.yaml"
        cfg.write_text("unifi:\n  host: h\n  verify_ssl: true\n")
        monkeypatch.setenv("CONFIG_PATH", str(cfg))
        monkeypatch.setenv("UNIFI_VERIFY_SSL", "")
        assert self._load().unifi.verify_ssl is True

    def test_debug_log_masks_secrets(self, monkeypatch, caplog):
        monkeypatch.setenv("UNIFI_NETWORK_HOST", "192.0.2.1")
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD", "hunter2-plain")
        monkeypatch.setenv("UNIFI_NETWORK_API_KEY", "key-abc-123")
        with caplog.at_level(logging.DEBUG):
            self._load()
        assert "192.0.2.1" in caplog.text
        assert "hunter2-plain" not in caplog.text
        assert "key-abc-123" not in caplog.text
