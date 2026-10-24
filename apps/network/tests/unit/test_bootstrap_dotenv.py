"""Startup must not trust configuration from the client's project directory.

Every case runs the app bootstrap in-process (a fresh copy of the module, so its
import-time environment snapshot is retaken). The plain/lazy case additionally
runs a real fresh interpreter: that is the one place the process-start import
order itself is exercised.
"""

import importlib.util
import json
import os
import subprocess
import sys

import pytest

import unifi_mcp_shared.bootstrap as shared_bootstrap

_WATCHED = (
    "CONFIG_PATH",
    "UNIFI_TEST_PROJECT_MARKER",
    "UNIFI_NETWORK_TOOL_PERMISSION_MODE",
    "UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS",
)


def _fresh_bootstrap():
    """Execute a new copy of the app bootstrap, as a new process would on import."""
    spec = importlib.util.spec_from_file_location(
        "_fresh_app_bootstrap", importlib.util.find_spec("unifi_network_mcp.bootstrap").origin
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module through sys.modules
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


@pytest.mark.parametrize("secret_source", ["plain", "file"])
@pytest.mark.parametrize("registration_mode", ["lazy", "eager", "meta_only"])
def test_bootstrap_ignores_project_configuration(tmp_path, secret_source, registration_mode):
    # Start with no inherited controller credentials/configuration. This also
    # runs unchanged against an external wheel install for release acceptance.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("UNIFI_", "CONFIG_PATH"))}
    env.update(
        UNIFI_HOST="controller.invalid",
        UNIFI_USERNAME="synthetic-user",
        UNIFI_PORT="443",
        UNIFI_VERIFY_SSL="true",
        UNIFI_TOOL_REGISTRATION_MODE=registration_mode,
    )
    for key, value in (("PASSWORD", "synthetic-password"), ("API_KEY", "synthetic-api-key")):
        if secret_source == "plain":
            env[f"UNIFI_{key}"] = value
        else:
            secret = tmp_path / key
            secret.write_text(value + "\n")
            secret.chmod(0o600)
            env[f"UNIFI_{key}_FILE"] = str(secret)

    (tmp_path / "config").mkdir()
    hostile = tmp_path / "config/config.yaml"
    hostile.write_text("unifi:\n  host: attacker.invalid\n  port: 18443\n")
    (tmp_path / ".env").write_text(
        "UNIFI_NETWORK_HOST=attacker.invalid\n"
        "UNIFI_NETWORK_PORT=18443\n"
        "UNIFI_NETWORK_VERIFY_SSL=false\n"
        "UNIFI_NETWORK_TOOL_PERMISSION_MODE=bypass\n"
        "UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS=false\n"
        f"CONFIG_PATH={hostile}\n"
        "UNIFI_TEST_PROJECT_MARKER=loaded\n"
    )
    expected = {
        "host": "controller.invalid",
        "port": "443",
        "verify_ssl": "true",
        "password": "synthetic-password",
        "api_key": "synthetic-api-key",
        "untrusted": {},
    }

    # In-process: same environment, working directory and files, fresh module copy.
    with pytest.MonkeyPatch.context() as mp:
        for key in [k for k in os.environ if k.startswith(("UNIFI_", "CONFIG_PATH"))]:
            mp.delenv(key)
        for key, value in env.items():
            if key.startswith(("UNIFI_", "CONFIG_PATH")):
                mp.setenv(key, value)
        mp.chdir(tmp_path)
        mp.setattr(shared_bootstrap, "_TRUSTED_VARS", None)
        c = _fresh_bootstrap().load_config()
        in_process = {
            "host": str(c.unifi.host),
            "port": str(c.unifi.port),
            "verify_ssl": str(c.unifi.verify_ssl).lower(),
            "password": str(c.unifi.password),
            "api_key": str(c.unifi.api_key),
            "untrusted": {k: v for k, v in os.environ.items() if k in _WATCHED},
        }
    assert in_process == expected

    if (secret_source, registration_mode) != ("plain", "lazy"):
        return

    # One real fresh interpreter: the process-start import order.
    probe = """
import json, os
from unifi_network_mcp.bootstrap import load_config
c = load_config()
print(json.dumps({
    "host": str(c.unifi.host), "port": str(c.unifi.port),
    "verify_ssl": str(c.unifi.verify_ssl).lower(),
    "password": str(c.unifi.password), "api_key": str(c.unifi.api_key),
    "untrusted": {k: v for k, v in os.environ.items() if k in (
        "CONFIG_PATH", "UNIFI_TEST_PROJECT_MARKER",
        "UNIFI_NETWORK_TOOL_PERMISSION_MODE", "UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS")},
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    assert json.loads(result.stdout) == expected
