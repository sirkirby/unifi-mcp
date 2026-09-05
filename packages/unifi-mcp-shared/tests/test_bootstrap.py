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


class TestResolveEnv:
    """Tests for resolve_env: plain, _FILE and _COMMAND spellings."""

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

    def test_returns_none_when_nothing_set(self):
        assert self._resolve() is None

    def test_plain_value_is_returned_unchanged(self, monkeypatch):
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD", "  p@ss  ")
        assert self._resolve() == "  p@ss  "

    def test_non_secret_key_ignores_file_spelling(self, monkeypatch, tmp_path):
        (tmp_path / "port").write_text("8443")
        monkeypatch.setenv("UNIFI_NETWORK_PORT_FILE", str(tmp_path / "port"))
        monkeypatch.setenv("UNIFI_PORT", "443")
        assert self._resolve("port") == "443"

    def test_file_contents_keep_leading_whitespace_and_drop_trailing_newline(self, monkeypatch, tmp_path):
        secret = tmp_path / "pw"
        secret.write_text(" a b\r\n")
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(secret))
        assert self._resolve() == " a b"

    def test_file_path_expands_user(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "pw").write_text("home-secret")
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", "~/pw")
        assert self._resolve() == "home-secret"

    def test_missing_file_refuses_to_start(self, monkeypatch, tmp_path, caplog):
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(tmp_path / "absent"))
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "UNIFI_NETWORK_PASSWORD_FILE" in caplog.text

    def test_empty_file_refuses_to_start(self, monkeypatch, tmp_path):
        secret = tmp_path / "pw"
        secret.write_text("\n")
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(secret))
        with pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6

    def test_command_stdout_is_used(self, monkeypatch):
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", "printf 'from-cmd\\n'")
        assert self._resolve() == "from-cmd"

    def test_command_is_not_run_through_a_shell(self, monkeypatch):
        # A shell would expand $HOME; argv execution passes it through literally.
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", "printf %s $HOME")
        assert self._resolve() == "$HOME"

    def test_failing_command_refuses_to_start_without_echoing_secret(self, monkeypatch, caplog):
        monkeypatch.setenv(
            "UNIFI_NETWORK_PASSWORD_COMMAND",
            "sh -c 'echo leaked-secret; echo vault: sealed >&2; exit 3'",
        )
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "UNIFI_NETWORK_PASSWORD_COMMAND" in caplog.text
        assert "exit status 3" in caplog.text
        assert "vault: sealed" in caplog.text
        assert "leaked-secret" not in caplog.text

    def test_command_with_empty_output_refuses_to_start(self, monkeypatch):
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", "true")
        with pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6

    def test_missing_executable_refuses_to_start(self, monkeypatch, caplog):
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", "definitely-not-a-real-binary-xyz")
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "definitely-not-a-real-binary-xyz" in caplog.text

    def test_unbalanced_quote_in_command_refuses_to_start(self, monkeypatch, caplog):
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", "pass show 'unifi")
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "UNIFI_NETWORK_PASSWORD_COMMAND" in caplog.text

    def test_whitespace_only_command_refuses_to_start(self, monkeypatch, caplog):
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", "   ")
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "UNIFI_NETWORK_PASSWORD_COMMAND" in caplog.text

    def test_non_executable_command_target_refuses_without_echoing_contents(self, monkeypatch, tmp_path, caplog):
        # Operator swapped _FILE and _COMMAND: the target is a plain secret file.
        secret = tmp_path / "pw"
        secret.write_text("swapped-secret\n")
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", str(secret))
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "UNIFI_NETWORK_PASSWORD_COMMAND" in caplog.text
        assert "swapped-secret" not in caplog.text

    def test_command_timeout_refuses_to_start(self, monkeypatch, caplog):
        from unifi_mcp_shared import bootstrap

        monkeypatch.setattr(bootstrap, "_SECRET_COMMAND_TIMEOUT_S", 0.2)
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", "sleep 5")
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "did not finish" in caplog.text

    def test_non_utf8_file_refuses_to_start(self, monkeypatch, tmp_path, caplog):
        secret = tmp_path / "pw"
        secret.write_bytes(b"p\xe4ss\n")  # Latin-1 "ä"
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(secret))
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "UNIFI_NETWORK_PASSWORD_FILE" in caplog.text

    def test_utf8_bom_in_file_is_dropped(self, monkeypatch, tmp_path):
        secret = tmp_path / "pw"
        secret.write_bytes(b"\xef\xbb\xbfhunter2\n")
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(secret))
        assert self._resolve() == "hunter2"

    def test_multiple_trailing_newlines_are_dropped(self, monkeypatch, tmp_path):
        secret = tmp_path / "pw"
        secret.write_text("pw\n\n\n")
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(secret))
        assert self._resolve() == "pw"

    @pytest.mark.parametrize("key", ["password", "api_key"])
    @pytest.mark.parametrize("level", ["NETWORK_", ""])
    def test_every_secret_key_and_level_accepts_command(self, monkeypatch, key, level):
        monkeypatch.setenv(f"UNIFI_{level}{key.upper()}_COMMAND", f"printf {key}-value")
        assert self._resolve(key) == f"{key}-value"

    def test_command_does_not_inherit_the_server_stdin(self, monkeypatch):
        # Under stdio transport the server's stdin is the MCP client's JSON-RPC pipe;
        # a prompting helper (gpg, op, sudo) must not be able to read from it.
        import subprocess

        from unifi_mcp_shared import bootstrap

        seen: dict = {}
        real_run = subprocess.run

        def spy(argv, **kwargs):
            seen.update(kwargs)
            return real_run(argv, **kwargs)

        monkeypatch.setattr(bootstrap.subprocess, "run", spy)
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", "printf ok")
        assert self._resolve() == "ok"
        assert seen["stdin"] is subprocess.DEVNULL

    def test_multi_line_command_output_refuses_to_start(self, monkeypatch, caplog):
        monkeypatch.setenv(
            "UNIFI_NETWORK_PASSWORD_COMMAND",
            "sh -c 'echo real-secret; echo WARNING: token expires soon'",
        )
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "UNIFI_NETWORK_PASSWORD_COMMAND" in caplog.text
        assert "real-secret" not in caplog.text

    def test_multi_line_file_refuses_to_start(self, monkeypatch, tmp_path, caplog):
        secret = tmp_path / "pw"
        secret.write_text("line-one\nline-two\n")
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(secret))
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "line-one" not in caplog.text

    def test_failing_command_stderr_is_truncated_in_log(self, monkeypatch, caplog):
        monkeypatch.setenv(
            "UNIFI_NETWORK_PASSWORD_COMMAND",
            "sh -c 'head -c 20000 /dev/zero | tr \"\\0\" x >&2; exit 1'",
        )
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit):
            self._resolve()
        assert len(caplog.text) < 2000
        assert "truncated" in caplog.text

    def test_empty_shared_non_secret_value_counts_as_unset(self, monkeypatch):
        monkeypatch.setenv("UNIFI_PORT", "")
        assert self._resolve("port") is None

    def test_command_runs_in_the_starting_environment_not_the_dotenv_one(self, monkeypatch):
        # A .env can set loader variables (PYTHONPATH, LD_PRELOAD) that the real env
        # lacks; the helper must not see them.
        from unifi_mcp_shared import bootstrap

        trusted = dict(os.environ)
        trusted["UNIFI_NETWORK_PASSWORD_COMMAND"] = "unused"
        monkeypatch.setattr(bootstrap, "_TRUSTED_ENV", trusted)
        monkeypatch.setenv("EVIL_FROM_DOTENV", "1")  # arrives after the snapshot
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", 'sh -c \'printf "%s" "${EVIL_FROM_DOTENV:-clean}"\'')
        assert self._resolve() == "clean"

    def test_indirection_from_dotenv_is_refused_when_snapshot_taken(self, monkeypatch, tmp_path, caplog):
        # Simulate: process started without the variable, then a .env in the cwd set it.
        from unifi_mcp_shared import bootstrap

        monkeypatch.setattr(bootstrap, "_TRUSTED_ENV", {"UNIFI_NETWORK_HOST": "h"})
        marker = tmp_path / "ran"
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", f"touch {marker}")
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert not marker.exists()
        assert "UNIFI_NETWORK_PASSWORD_COMMAND" in caplog.text
        assert ".env" in caplog.text

    def test_indirection_from_process_env_is_honoured_when_snapshot_taken(self, monkeypatch, tmp_path):
        from unifi_mcp_shared import bootstrap

        (tmp_path / "pw").write_text("trusted\n")
        monkeypatch.setattr(bootstrap, "_TRUSTED_ENV", {"UNIFI_NETWORK_PASSWORD_FILE": "x"})
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(tmp_path / "pw"))
        assert self._resolve() == "trusted"

    def test_plain_value_from_dotenv_is_still_accepted(self, monkeypatch):
        # Only the indirections are gated; a .env may still carry the value itself.
        from unifi_mcp_shared import bootstrap

        monkeypatch.setattr(bootstrap, "_TRUSTED_ENV", {})
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD", "from-dotenv")
        assert self._resolve() == "from-dotenv"

    def test_snapshot_process_env_records_current_names_once(self, monkeypatch):
        from unifi_mcp_shared import bootstrap

        monkeypatch.setattr(bootstrap, "_TRUSTED_ENV", None)
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", "/nonexistent")
        bootstrap.snapshot_process_env()
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", "true")
        bootstrap.snapshot_process_env()  # second call must not widen the snapshot
        assert "UNIFI_NETWORK_PASSWORD_FILE" in bootstrap._TRUSTED_ENV
        assert "UNIFI_NETWORK_PASSWORD_COMMAND" not in bootstrap._TRUSTED_ENV

    def test_unresolvable_home_in_file_path_refuses_to_start(self, monkeypatch, caplog):
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", "~nosuchuser_xyz_123/pw")
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "UNIFI_NETWORK_PASSWORD_FILE" in caplog.text

    def test_missing_file_message_says_it_does_not_exist(self, monkeypatch, tmp_path, caplog):
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(tmp_path / "absent"))
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit):
            self._resolve()
        assert "does not exist" in caplog.text

    def test_ambiguity_message_names_the_dotenv_origin(self, monkeypatch, tmp_path, caplog):
        from unifi_mcp_shared import bootstrap

        (tmp_path / "pw").write_text("x")
        monkeypatch.setattr(bootstrap, "_TRUSTED_ENV", {"UNIFI_NETWORK_PASSWORD_FILE": "x"})
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD", "your-password-here")  # left over in a copied .env
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(tmp_path / "pw"))
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit):
            self._resolve()
        assert "UNIFI_NETWORK_PASSWORD (from a .env file)" in caplog.text
        assert "UNIFI_NETWORK_PASSWORD_FILE (from a .env file)" not in caplog.text

    def test_oversized_command_output_refuses_to_start(self, monkeypatch, caplog):
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", "head -c 70000 /dev/zero")
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "UNIFI_NETWORK_PASSWORD_COMMAND" in caplog.text

    def test_non_regular_file_refuses_to_start(self, monkeypatch, tmp_path, caplog):
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(tmp_path))  # a directory
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "UNIFI_NETWORK_PASSWORD_FILE" in caplog.text

    def test_oversized_file_refuses_to_start(self, monkeypatch, tmp_path, caplog):
        secret = tmp_path / "pw"
        secret.write_bytes(b"x" * (64 * 1024 + 1))
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(secret))
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "UNIFI_NETWORK_PASSWORD_FILE" in caplog.text

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
    def test_group_or_world_readable_file_logs_a_warning(self, monkeypatch, tmp_path, caplog):
        secret = tmp_path / "pw"
        secret.write_text("s\n")
        secret.chmod(0o644)
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(secret))
        with caplog.at_level(logging.WARNING):
            assert self._resolve() == "s"
        assert "UNIFI_NETWORK_PASSWORD_FILE" in caplog.text
        assert "0644" in caplog.text or "644" in caplog.text

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
        (tmp_path / "pw").write_text("x")
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD", "plain")
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(tmp_path / "pw"))
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
            self._resolve()
        assert exc.value.code == 6
        assert "UNIFI_NETWORK_PASSWORD" in caplog.text
        assert "UNIFI_NETWORK_PASSWORD_FILE" in caplog.text
        assert "plain" not in caplog.text

    def test_server_file_beats_shared_plain(self, monkeypatch, tmp_path):
        (tmp_path / "pw").write_text("server-file")
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(tmp_path / "pw"))
        monkeypatch.setenv("UNIFI_PASSWORD", "shared-plain")
        assert self._resolve() == "server-file"

    def test_empty_plain_value_falls_through_to_shared_level(self, monkeypatch, tmp_path):
        # Plugin .mcp.json interpolates "${UNIFI_NETWORK_PASSWORD:-}", so an unset
        # client variable arrives as "" and must not shadow the shared level.
        (tmp_path / "pw").write_text("shared-file")
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD", "")
        monkeypatch.setenv("UNIFI_PASSWORD_FILE", str(tmp_path / "pw"))
        assert self._resolve() == "shared-file"


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

    def test_api_key_command_reaches_config(self, monkeypatch):
        monkeypatch.setenv("UNIFI_NETWORK_API_KEY_COMMAND", "printf api-key-value")
        assert self._load().unifi.api_key == "api-key-value"

    def test_plain_password_still_works(self, monkeypatch):
        monkeypatch.setenv("UNIFI_PASSWORD", "plainpw")
        assert self._load().unifi.password == "plainpw"

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
        monkeypatch.setenv("UNIFI_NETWORK_HOST", "10.0.0.1")
        monkeypatch.setenv("UNIFI_NETWORK_PASSWORD", "hunter2-plain")
        monkeypatch.setenv("UNIFI_NETWORK_API_KEY", "key-abc-123")
        with caplog.at_level(logging.DEBUG):
            self._load()
        assert "10.0.0.1" in caplog.text
        assert "hunter2-plain" not in caplog.text
        assert "key-abc-123" not in caplog.text


class TestSecretKeysContract:
    def test_secret_keys_match_the_redaction_vocabulary_for_every_default_key(self):
        import inspect

        from unifi_core.redaction import is_sensitive_key
        from unifi_mcp_shared.bootstrap import SECRET_KEYS

        default_keys = inspect.signature(load_server_config).parameters["keys"].default
        all_keys = set(default_keys) | {"controller_type"}  # Network adds this one
        assert {k for k in all_keys if is_sensitive_key(k)} == SECRET_KEYS
