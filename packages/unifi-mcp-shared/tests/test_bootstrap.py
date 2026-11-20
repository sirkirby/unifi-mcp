"""Tests for the shared bootstrap module."""

import logging
import os
import uuid
from pathlib import Path

import pytest
from omegaconf import OmegaConf
from unifi_mcp_shared.bootstrap import (
    EXIT_SECRET_UNRESOLVED,
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

    def _cfg(self, host: str = ""):
        return OmegaConf.create({"unifi": {"host": host}})

    def test_passes_when_host_set(self):
        assert_credentials_configured(
            self._cfg("192.0.2.1"),
            plugin_name="unifi-network",
            env_prefix="NETWORK",
            logger=logging.getLogger("test"),
        )

    @pytest.mark.parametrize(
        ("cfg_dict", "plugin_name", "env_prefix"),
        [
            ({"unifi": {"host": ""}}, "unifi-network", "NETWORK"),
            ({"unifi": {"host": "   "}}, "unifi-protect", "PROTECT"),
            ({}, "unifi-access", "ACCESS"),
        ],
    )
    def test_exits_when_host_missing_or_blank(self, caplog, cfg_dict, plugin_name, env_prefix):
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            assert_credentials_configured(
                OmegaConf.create(cfg_dict),
                plugin_name=plugin_name,
                env_prefix=env_prefix,
                logger=logging.getLogger("test"),
            )
        assert exc.value.code == 5
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert plugin_name in joined
        assert f"UNIFI_{env_prefix}_HOST" in joined
        assert f"{plugin_name}-setup skill" in joined


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
            ("UNIFI_NETWORK_PASSWORD_FILE", "UNIFI_PASSWORD", "shared-plain", "server-file"),
            ("UNIFI_PASSWORD_FILE", "UNIFI_NETWORK_PASSWORD", "", "shared-file"),
        ],
    )
    def test_server_and_shared_env_precedence(self, monkeypatch, tmp_path, file_var, plain_var, plain_val, expected):
        (tmp_path / "pw").write_text(expected)
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

    def test_password_file_reaches_config(self, monkeypatch):
        (self.tmp_path / "pw").write_text("filepw\n")
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(self.tmp_path / "pw"))
        assert self._load().unifi.password == "filepw"

    def test_api_key_file_reaches_config(self, monkeypatch):
        (self.tmp_path / "key").write_text("api-key-value\n")
        monkeypatch.setenv("UNIFI_NETWORK_API_KEY_FILE", str(self.tmp_path / "key"))
        assert self._load().unifi.api_key == "api-key-value"

    def test_plain_password_still_works(self, monkeypatch):
        monkeypatch.setenv("UNIFI_PASSWORD", "plainpw")
        assert self._load().unifi.password == "plainpw"

    def test_isolated_keys_ignore_the_shared_level(self, monkeypatch):
        monkeypatch.setenv("UNIFI_HOST", "192.0.2.1")
        monkeypatch.setenv("UNIFI_PASSWORD", "gatewaypw")
        monkeypatch.setenv("UNIFI_USERNAME", "gateway-admin")

        cfg = load_server_config(
            package_name="unifi_mcp_shared",
            env_prefix="NETWORK",
            logger=logging.getLogger("test"),
            isolated_keys=("host", "password"),
        )

        assert cfg.unifi.host == "" and cfg.unifi.password == ""
        assert cfg.unifi.username == "gateway-admin"

    def test_isolated_key_that_is_not_loaded_is_refused(self):
        with pytest.raises(ValueError, match="passwrod"):
            load_server_config(
                package_name="unifi_mcp_shared",
                env_prefix="NETWORK",
                logger=logging.getLogger("test"),
                keys=("host", "password"),
                isolated_keys=("host", "passwrod"),
            )

    def test_isolated_keys_still_read_the_server_level(self, monkeypatch):
        (self.tmp_path / "pw").write_text("naspw\n")
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(self.tmp_path / "pw"))
        monkeypatch.setenv("UNIFI_PASSWORD", "gatewaypw")

        cfg = load_server_config(
            package_name="unifi_mcp_shared",
            env_prefix="NETWORK",
            logger=logging.getLogger("test"),
            isolated_keys=("password",),
        )

        assert cfg.unifi.password == "naspw"

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


class TestHostLevelCredentials:
    """Credentials come from the level the host came from.

    A server whose host is set at its own level (``UNIFI_<PRODUCT>_HOST``) takes the
    shared username, password and API key only when that host and its port name the
    same console as ``UNIFI_HOST``. Values are synthetic markers made per test.
    """

    @pytest.fixture(autouse=True)
    def _isolated(self, monkeypatch, tmp_path):
        from unifi_mcp_shared import bootstrap

        for name in list(os.environ):
            if name.startswith("UNIFI_") or name == "CONFIG_PATH":
                monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(bootstrap, "_TRUSTED_VARS", None)
        monkeypatch.setattr(bootstrap, "_CREDENTIAL_CUT_NOTES", {})
        self.tmp_path = tmp_path
        self.monkeypatch = monkeypatch
        self._config('unifi:\n  host: ""\n  username: ""\n  password: ""\n  api_key: ""\n  port: 443\n')
        run = uuid.uuid4().hex[:8]
        self.shared = {
            "UNIFI_USERNAME": f"user-{run}",
            "UNIFI_PASSWORD": f"pw-{run}",
            "UNIFI_API_KEY": f"key-{run}",
        }

    def _config(self, text: str) -> None:
        cfg = self.tmp_path / "config.yaml"
        cfg.write_text(text)
        self.monkeypatch.setenv("CONFIG_PATH", str(cfg))

    def _env(self, **variables: str) -> None:
        for name, value in variables.items():
            self.monkeypatch.setenv(name, value)

    def _shared_credentials(self) -> None:
        self._env(**self.shared)

    def _load(self, prefix: str = "PROTECT", **kwargs):
        return load_server_config(
            package_name="unifi_mcp_shared", env_prefix=prefix, logger=logging.getLogger("test"), **kwargs
        )

    @staticmethod
    def _warnings(caplog) -> list[str]:
        return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]

    def _assert_no_secret_logged(self, caplog) -> None:
        for record in caplog.records:
            text = record.getMessage() + repr(record.args)
            for value in self.shared.values():
                assert value not in text

    def _helper(self, name: str = "helper.sh") -> tuple[Path, Path]:
        """An absolute credential helper that leaves a marker file when it runs."""
        if os.name == "nt":
            pytest.skip("the helper is a /bin/sh script")
        marker = self.tmp_path / f"{name}.ran"
        script = self.tmp_path / name
        script.write_text(f"#!/bin/sh\ntouch '{marker}'\necho helper-value\n")
        script.chmod(0o755)
        return script, marker

    # -- red before the change: the shared credentials are cut -----------------

    @pytest.mark.parametrize("prefix", ["NETWORK", "PROTECT", "ACCESS"])
    def test_differing_host_cuts_shared_credentials_and_says_why(self, caplog, prefix):
        self._shared_credentials()
        self._env(UNIFI_HOST="gateway.invalid", **{f"UNIFI_{prefix}_HOST": "other.invalid"})
        with caplog.at_level(logging.DEBUG):
            unifi = self._load(prefix).unifi
        assert unifi.host == "other.invalid"
        assert (unifi.username, unifi.password, unifi.api_key) == ("", "", "")
        assert self._warnings(caplog) == [
            f"UNIFI_USERNAME is set but not used: the host comes from UNIFI_{prefix}_HOST, "
            f"which differs from UNIFI_HOST; set UNIFI_{prefix}_USERNAME.",
            f"UNIFI_PASSWORD is set but not used: the host comes from UNIFI_{prefix}_HOST, "
            f"which differs from UNIFI_HOST; set UNIFI_{prefix}_PASSWORD (or its _FILE/_COMMAND form).",
            f"UNIFI_API_KEY is set but not used: the host comes from UNIFI_{prefix}_HOST, "
            f"which differs from UNIFI_HOST; set UNIFI_{prefix}_API_KEY (or its _FILE/_COMMAND form).",
        ]
        self._assert_no_secret_logged(caplog)
        assert not any("invalid" in w for w in self._warnings(caplog))

    def test_no_shared_host_cuts_shared_credentials(self, caplog):
        self._shared_credentials()
        self._env(UNIFI_PROTECT_HOST="nas.invalid")
        with caplog.at_level(logging.WARNING):
            unifi = self._load().unifi
        assert (unifi.username, unifi.password, unifi.api_key) == ("", "", "")
        assert self._warnings(caplog)[1] == (
            "UNIFI_PASSWORD is set but not used: the host comes from UNIFI_PROTECT_HOST and UNIFI_HOST "
            "is not set; set UNIFI_PROTECT_PASSWORD (or its _FILE/_COMMAND form)."
        )

    @pytest.mark.parametrize(
        ("shared_host", "product_host"),
        [
            ("console.invalid", "console.invalid:443"),  # a port in the host is another string the core connects to
            ("console.invalid", "https://console.invalid"),  # the core builds https://https://console.invalid:443
            ("console.invalid", "console.invalid/"),
            ("console.invalid", "console.invalid."),
            ("::1", "[::1]"),
            (" console.invalid ", "console.invalid\t"),  # the core connects to the host as written
            ("console.invalid", " console.invalid"),
            ("  ", "  "),  # a blank host names no console
            ("\u00c4.invalid", "\u00e4.invalid"),  # only ASCII case is folded
        ],
    )
    def test_host_identity_is_the_host_as_written(self, shared_host, product_host):
        self._shared_credentials()
        self._env(UNIFI_HOST=shared_host, UNIFI_PROTECT_HOST=product_host)
        assert self._load().unifi.password == ""

    @pytest.mark.parametrize(
        ("variables"),
        [
            {"UNIFI_PROTECT_PORT": "7443"},
            {"UNIFI_PORT": "8443", "UNIFI_PROTECT_PORT": "443"},
        ],
    )
    def test_same_host_on_another_port_cuts(self, caplog, variables):
        self._shared_credentials()
        self._env(UNIFI_HOST="console.invalid", UNIFI_PROTECT_HOST="console.invalid", **variables)
        with caplog.at_level(logging.WARNING):
            assert self._load(keys=("host", "port", "password")).unifi.password == ""
        assert self._warnings(caplog) == [
            "UNIFI_PASSWORD is set but not used: the host comes from UNIFI_PROTECT_HOST, which names the "
            "UNIFI_HOST console on another port (UNIFI_PROTECT_PORT or UNIFI_PORT); set UNIFI_PROTECT_PASSWORD "
            "(or its _FILE/_COMMAND form)."
        ]

    def test_yaml_naming_the_shared_variables_cannot_bring_them_back(self, caplog):
        """A config written like the old Network one interpolates the shared names itself."""
        self._config(
            "unifi:\n"
            '  host: ${oc.env:UNIFI_HOST,""}\n'
            '  username: ${oc.env:UNIFI_USERNAME,""}\n'
            '  password: ${oc.env:UNIFI_PASSWORD,""}\n'
            '  api_key: ${oc.env:UNIFI_API_KEY,""}\n'
        )
        self._shared_credentials()
        self._env(UNIFI_HOST="gateway.invalid", UNIFI_NETWORK_HOST="other.invalid")
        with caplog.at_level(logging.DEBUG):
            unifi = self._load("NETWORK").unifi
        assert (unifi.username, unifi.password, unifi.api_key) == ("", "", "")
        self._assert_no_secret_logged(caplog)

    @pytest.mark.parametrize(
        "password",
        ['${oc.env:UNIFI_PASSWORD,""}', "{shared}"],  # interpolated, or the same literal written in the file
    )
    def test_isolated_keys_cannot_be_brought_back_by_the_yaml(self, caplog, password):
        password = password.replace("{shared}", self.shared["UNIFI_PASSWORD"])
        self._config(f'unifi:\n  host: ""\n  password: {password}\n')
        self._shared_credentials()
        with caplog.at_level(logging.WARNING):
            unifi = self._load("NETWORK", keys=("host", "password"), isolated_keys=("password",)).unifi
        assert unifi.password == ""
        assert self._warnings(caplog) == [
            "unifi.password in the config file has the value of UNIFI_PASSWORD, which this server does not "
            "use for it; the value is ignored. Set UNIFI_NETWORK_PASSWORD."
        ]
        self._assert_no_secret_logged(caplog)

    def test_cut_key_blanked_from_the_yaml_says_so(self, caplog):
        self._config('unifi:\n  host: ""\n  password: ${oc.env:UNIFI_PASSWORD,""}\n')
        self._shared_credentials()
        self._env(UNIFI_HOST="gateway.invalid", UNIFI_PROTECT_HOST="other.invalid")
        with caplog.at_level(logging.WARNING):
            assert self._load(keys=("host", "password")).unifi.password == ""
        assert self._warnings(caplog) == [
            "unifi.password in the config file has the value of UNIFI_PASSWORD, which this server does not "
            "use for it; the value is ignored. Set UNIFI_PROTECT_PASSWORD.",
            "UNIFI_PASSWORD is set but not used: the host comes from UNIFI_PROTECT_HOST, which differs from "
            "UNIFI_HOST; set UNIFI_PROTECT_PASSWORD (or its _FILE/_COMMAND form).",
        ]
        self._assert_no_secret_logged(caplog)

    def test_literal_username_in_a_config_file_is_kept_when_it_matches_the_shared_one(self, caplog):
        """A username is no secret; only an interpolated one is blanked."""
        self._config(f'unifi:\n  host: ""\n  username: {self.shared["UNIFI_USERNAME"]}\n  password: file-pass\n')
        self._shared_credentials()
        self._env(UNIFI_HOST="gateway.invalid", UNIFI_PROTECT_HOST="other.invalid")
        with caplog.at_level(logging.WARNING):
            unifi = self._load(keys=("host", "username", "password")).unifi
        assert (unifi.username, unifi.password) == (self.shared["UNIFI_USERNAME"], "file-pass")
        assert self._warnings(caplog) == []

    def test_operator_value_in_a_config_file_is_kept_when_it_is_not_the_shared_one(self, caplog):
        self._config('unifi:\n  host: ""\n  password: operator-file-value\n')
        self._shared_credentials()
        self._env(UNIFI_HOST="gateway.invalid", UNIFI_PROTECT_HOST="other.invalid")
        with caplog.at_level(logging.WARNING):
            assert self._load(keys=("host", "password")).unifi.password == "operator-file-value"
        # The file's own credential is used, so nothing is missing and no remedy is owed.
        assert self._warnings(caplog) == []

    def test_warning_names_the_spellings_actually_set(self, caplog):
        self._env(
            UNIFI_HOST="gateway.invalid",
            UNIFI_PROTECT_HOST="other.invalid",
            UNIFI_PASSWORD_FILE=str(self.tmp_path / "absent"),
        )
        with caplog.at_level(logging.WARNING):
            self._load(keys=("host", "password"))
        assert self._warnings(caplog) == [
            "UNIFI_PASSWORD_FILE is set but not used: the host comes from UNIFI_PROTECT_HOST, which differs "
            "from UNIFI_HOST; set UNIFI_PROTECT_PASSWORD (or its _FILE/_COMMAND form)."
        ]

    @pytest.mark.parametrize(("product_host", "used"), [("other.invalid", False), ("console.invalid", True)])
    def test_shared_command_runs_only_on_the_same_console(self, caplog, product_host, used):
        script, marker = self._helper()
        self._env(UNIFI_HOST="console.invalid", UNIFI_PROTECT_HOST=product_host, UNIFI_PASSWORD_COMMAND=str(script))
        with caplog.at_level(logging.DEBUG):
            password = self._load(keys=("host", "password")).unifi.password
        assert (password, marker.exists()) == (("helper-value", True) if used else ("", False))
        assert "helper-value" not in caplog.text

    def test_cut_shared_file_is_never_opened(self):
        """A path that does not exist refuses startup when it is read; when cut it is not read."""
        self._env(
            UNIFI_HOST="gateway.invalid",
            UNIFI_PROTECT_HOST="other.invalid",
            UNIFI_PASSWORD_FILE=str(self.tmp_path / "absent"),
        )
        assert self._load(keys=("host", "password")).unifi.password == ""

    def test_two_spellings_at_a_cut_shared_level_do_not_refuse_startup(self, caplog):
        script, marker = self._helper()
        self._env(
            UNIFI_HOST="gateway.invalid",
            UNIFI_PROTECT_HOST="other.invalid",
            UNIFI_PASSWORD=self.shared["UNIFI_PASSWORD"],
            UNIFI_PASSWORD_COMMAND=str(script),
        )
        with caplog.at_level(logging.WARNING):
            assert self._load(keys=("host", "password")).unifi.password == ""
        assert not marker.exists()
        [warning] = self._warnings(caplog)
        assert warning.startswith("UNIFI_PASSWORD and UNIFI_PASSWORD_COMMAND are both set but not used:")

    def test_cut_shared_command_from_a_dotenv_is_not_refused(self, caplog):
        from unifi_mcp_shared import bootstrap

        script, marker = self._helper()
        self._env(UNIFI_HOST="gateway.invalid", UNIFI_PROTECT_HOST="other.invalid", UNIFI_PASSWORD_COMMAND=str(script))
        self.monkeypatch.setattr(bootstrap, "_TRUSTED_VARS", frozenset({"UNIFI_HOST", "UNIFI_PROTECT_HOST"}))
        with caplog.at_level(logging.WARNING):
            assert self._load(keys=("host", "password")).unifi.password == ""
        assert not marker.exists()
        [warning] = self._warnings(caplog)
        assert warning.startswith("UNIFI_PASSWORD_COMMAND (from a .env file) is set but not used:")

    # -- guards: behaviour that holds before and after --------------------------

    def test_no_product_host_keeps_the_shared_credentials(self, caplog):
        self._shared_credentials()
        self._env(UNIFI_HOST="gateway.invalid")
        with caplog.at_level(logging.WARNING):
            unifi = self._load().unifi
        assert (unifi.host, unifi.password, unifi.api_key) == (
            "gateway.invalid",
            self.shared["UNIFI_PASSWORD"],
            self.shared["UNIFI_API_KEY"],
        )
        assert self._warnings(caplog) == []

    @pytest.mark.parametrize(
        ("shared_host", "product_host", "ports"),
        [
            ("console.invalid", "console.invalid", {}),
            ("Console.Invalid", "console.INVALID", {}),
            ("console.invalid", "console.invalid", {"UNIFI_PROTECT_PORT": "443"}),
            ("console.invalid", "console.invalid", {"UNIFI_PORT": "8443"}),
            ("console.invalid", "console.invalid", {"UNIFI_PORT": "8443", "UNIFI_PROTECT_PORT": "8443"}),
        ],
    )
    def test_same_console_keeps_the_shared_credentials(self, caplog, shared_host, product_host, ports):
        self._shared_credentials()
        self._env(UNIFI_HOST=shared_host, UNIFI_PROTECT_HOST=product_host, **ports)
        with caplog.at_level(logging.WARNING):
            unifi = self._load().unifi
        assert (unifi.username, unifi.password, unifi.api_key) == tuple(self.shared.values())
        assert self._warnings(caplog) == []

    @pytest.mark.parametrize("key", ["password", "api_key"])
    @pytest.mark.parametrize("spelling", ["", "_FILE", "_COMMAND"])
    def test_product_credentials_are_used_on_another_host(self, caplog, key, spelling):
        self._shared_credentials()
        product = f"product-{uuid.uuid4().hex[:8]}"
        if spelling == "_FILE":
            source = self.tmp_path / "product-secret"
            source.write_text(product + "\n")
            source.chmod(0o600)
            value = str(source)
        elif spelling == "_COMMAND":
            script, _ = self._helper()
            script.write_text(f"#!/bin/sh\necho {product}\n")
            value = str(script)
        else:
            value = product
        variable = f"UNIFI_{key.upper()}"
        self._env(
            UNIFI_HOST="gateway.invalid",
            UNIFI_PROTECT_HOST="nas.invalid",
            **{f"UNIFI_PROTECT_{key.upper()}{spelling}": value},
        )
        with caplog.at_level(logging.DEBUG):
            unifi = self._load().unifi
        assert unifi[key] == product
        assert not any(w.startswith(f"{variable} is") for w in self._warnings(caplog))
        self._assert_no_secret_logged(caplog)

    def test_shared_file_still_read_on_the_same_console(self):
        """Positive control for the never-opened test: the same spelling is read when it is used."""
        (self.tmp_path / "pw").write_text("shared-file-value\n")
        (self.tmp_path / "pw").chmod(0o600)
        self._env(
            UNIFI_HOST="console.invalid",
            UNIFI_PROTECT_HOST="console.invalid",
            UNIFI_PASSWORD_FILE=str(self.tmp_path / "pw"),
        )
        assert self._load(keys=("host", "password")).unifi.password == "shared-file-value"

    def test_product_password_file_beats_the_shared_password_on_the_same_host(self, caplog):
        (self.tmp_path / "pw").write_text("product-file-value\n")
        (self.tmp_path / "pw").chmod(0o600)
        self._shared_credentials()
        self._env(
            UNIFI_HOST="console.invalid",
            UNIFI_PROTECT_HOST="console.invalid",
            UNIFI_PROTECT_PASSWORD_FILE=str(self.tmp_path / "pw"),
        )
        with caplog.at_level(logging.WARNING):
            assert self._load().unifi.password == "product-file-value"
        assert self._warnings(caplog) == []

    def test_non_credential_keys_still_fall_back_when_credentials_are_cut(self):
        self._shared_credentials()
        self._env(
            UNIFI_HOST="gateway.invalid",
            UNIFI_PROTECT_HOST="nas.invalid",
            UNIFI_PORT="8443",
            UNIFI_SITE="shared-site",
            UNIFI_VERIFY_SSL="true",
        )
        unifi = self._load().unifi
        assert (unifi.port, unifi.site, unifi.verify_ssl, unifi.password) == ("8443", "shared-site", True, "")

    def test_empty_product_host_counts_as_unset(self, caplog):
        self._shared_credentials()
        self._env(UNIFI_HOST="gateway.invalid", UNIFI_PROTECT_HOST="")
        with caplog.at_level(logging.WARNING):
            unifi = self._load().unifi
        assert (unifi.host, unifi.password) == ("gateway.invalid", self.shared["UNIFI_PASSWORD"])
        assert self._warnings(caplog) == []

    def test_host_from_a_config_file_is_not_an_environment_level(self, caplog):
        """Deliberate limit: only environment levels decide; the operator owns CONFIG_PATH."""
        self._config('unifi:\n  host: file-host.invalid\n  password: ""\n')
        self._shared_credentials()
        with caplog.at_level(logging.WARNING):
            unifi = self._load(keys=("host", "password")).unifi
        assert (unifi.host, unifi.password) == ("file-host.invalid", self.shared["UNIFI_PASSWORD"])
        assert self._warnings(caplog) == []

    def test_keys_that_are_not_loaded_are_untouched(self, caplog):
        self._config('unifi:\n  host: ""\n  password: ""\n  username: file-user\n')
        self._shared_credentials()
        self._env(UNIFI_HOST="gateway.invalid", UNIFI_PROTECT_HOST="nas.invalid")
        with caplog.at_level(logging.WARNING):
            unifi = self._load(keys=("host", "password")).unifi
        assert unifi.username == "file-user"
        assert not any("USERNAME" in w for w in self._warnings(caplog))

    def test_username_file_spelling_is_not_a_username_source(self, caplog):
        self._env(
            UNIFI_HOST="gateway.invalid",
            UNIFI_PROTECT_HOST="nas.invalid",
            UNIFI_USERNAME_FILE=str(self.tmp_path / "absent"),
        )
        with caplog.at_level(logging.WARNING):
            self._load()
        assert self._warnings(caplog) == []

    def test_isolated_keys_log_no_host_warning_when_the_host_differs(self, caplog):
        self._shared_credentials()
        self._env(UNIFI_HOST="gateway.invalid", UNIFI_PROTECT_HOST="other.invalid")
        with caplog.at_level(logging.WARNING):
            unifi = self._load(isolated_keys=("password",)).unifi
        assert (unifi.username, unifi.password, unifi.api_key) == ("", "", "")
        warned = [w.split(" ", 1)[0] for w in self._warnings(caplog)]
        assert warned == ["UNIFI_USERNAME", "UNIFI_API_KEY"]

    def test_isolated_keys_log_no_host_warning(self, caplog):
        self._shared_credentials()
        self._env(UNIFI_HOST="console.invalid", UNIFI_PROTECT_HOST="console.invalid")
        with caplog.at_level(logging.WARNING):
            unifi = self._load(isolated_keys=("password",)).unifi
        assert unifi.password == ""
        assert unifi.username == self.shared["UNIFI_USERNAME"]
        assert self._warnings(caplog) == []

    def test_a_server_that_loads_no_host_is_untouched(self, caplog):
        """Site Manager's shape: nothing is loaded from the environment."""
        self._shared_credentials()
        self._env(UNIFI_HOST="gateway.invalid", UNIFI_SITEMANAGER_HOST="other.invalid")
        with caplog.at_level(logging.WARNING):
            self._load("SITEMANAGER", keys=())
        assert self._warnings(caplog) == []

    def test_product_file_from_a_dotenv_is_still_refused(self, caplog):
        from unifi_mcp_shared import bootstrap

        (self.tmp_path / "pw").write_text("x\n")
        self._env(
            UNIFI_HOST="gateway.invalid",
            UNIFI_PROTECT_HOST="other.invalid",
            UNIFI_PROTECT_PASSWORD_FILE=str(self.tmp_path / "pw"),
        )
        self.monkeypatch.setattr(bootstrap, "_TRUSTED_VARS", frozenset({"UNIFI_HOST", "UNIFI_PROTECT_HOST"}))
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._load(keys=("host", "password"))
        assert exc.value.code == EXIT_SECRET_UNRESOLVED

    # -- the cut warnings are kept for the server's login-failure error ---------

    @pytest.mark.parametrize(
        ("variables", "why"),
        [
            ({"UNIFI_HOST": "gateway.invalid"}, ", which differs from UNIFI_HOST"),
            ({}, " and UNIFI_HOST is not set"),
            (
                {"UNIFI_HOST": "nas.invalid", "UNIFI_PROTECT_PORT": "7443"},
                ", which names the UNIFI_HOST console on another port (UNIFI_PROTECT_PORT or UNIFI_PORT)",
            ),
        ],
        ids=["differs", "no-shared-host", "port"],
    )
    def test_cut_credentials_are_kept_as_the_warning_text(self, caplog, variables, why):
        from unifi_mcp_shared.bootstrap import credential_cut_hint

        self._shared_credentials()
        self._env(UNIFI_PROTECT_HOST="nas.invalid", **variables)
        with caplog.at_level(logging.WARNING):
            self._load()
        hint = credential_cut_hint("PROTECT")
        assert hint == " ".join(self._warnings(caplog))
        assert hint == (
            f"UNIFI_USERNAME is set but not used: the host comes from UNIFI_PROTECT_HOST{why}; "
            "set UNIFI_PROTECT_USERNAME. "
            f"UNIFI_PASSWORD is set but not used: the host comes from UNIFI_PROTECT_HOST{why}; "
            "set UNIFI_PROTECT_PASSWORD (or its _FILE/_COMMAND form). "
            f"UNIFI_API_KEY is set but not used: the host comes from UNIFI_PROTECT_HOST{why}; "
            "set UNIFI_PROTECT_API_KEY (or its _FILE/_COMMAND form)."
        )
        for value in [*self.shared.values(), "nas.invalid", "gateway.invalid", "7443"]:
            assert value not in hint

    def test_cut_hint_names_only_the_shared_spellings_that_are_set(self):
        from unifi_mcp_shared.bootstrap import credential_cut_hint

        self._env(UNIFI_HOST="gateway.invalid", UNIFI_PROTECT_HOST="nas.invalid", UNIFI_PASSWORD_FILE="/nonexistent")
        self._load()
        assert credential_cut_hint("PROTECT") == (
            "UNIFI_PASSWORD_FILE is set but not used: the host comes from UNIFI_PROTECT_HOST, which differs "
            "from UNIFI_HOST; set UNIFI_PROTECT_PASSWORD (or its _FILE/_COMMAND form)."
        )

    @pytest.mark.parametrize(
        "variables",
        [
            {"UNIFI_HOST": "console.invalid", "UNIFI_PROTECT_HOST": "console.invalid"},
            {"UNIFI_HOST": "console.invalid"},
            {"UNIFI_HOST": "gateway.invalid", "UNIFI_PROTECT_HOST": "nas.invalid", "UNIFI_PROTECT_PASSWORD": "own"},
        ],
        ids=["same-console", "no-product-host", "own-credentials"],
    )
    def test_no_cut_hint_when_nothing_was_ignored(self, variables):
        from unifi_mcp_shared.bootstrap import credential_cut_hint

        self._env(UNIFI_PASSWORD=self.shared["UNIFI_PASSWORD"], **variables)
        self._load(keys=("host", "password"))
        assert credential_cut_hint("PROTECT") is None

    def test_no_cut_hint_when_the_config_file_supplies_its_own_value(self):
        from unifi_mcp_shared.bootstrap import credential_cut_hint

        self._config('unifi:\n  host: ""\n  password: operator-value\n')
        self._shared_credentials()
        self._env(UNIFI_HOST="gateway.invalid", UNIFI_PROTECT_HOST="nas.invalid")
        assert self._load(keys=("host", "password")).unifi.password == "operator-value"
        assert credential_cut_hint("PROTECT") is None

    def test_cut_hint_follows_the_latest_load_of_each_server(self):
        from unifi_mcp_shared.bootstrap import credential_cut_hint

        self._shared_credentials()
        self._env(UNIFI_HOST="gateway.invalid", UNIFI_PROTECT_HOST="nas.invalid")
        self._load()
        self._load("NETWORK")
        assert credential_cut_hint("PROTECT") is not None
        assert credential_cut_hint("NETWORK") is None
        assert credential_cut_hint("ACCESS") is None

        self._env(UNIFI_PROTECT_HOST="gateway.invalid")
        self._load()
        assert credential_cut_hint("PROTECT") is None
