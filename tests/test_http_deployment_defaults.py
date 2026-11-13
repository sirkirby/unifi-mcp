"""Guard the packaged and Compose MCP exposure boundaries."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from omegaconf import OmegaConf

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("server", ["network", "protect", "access", "sitemanager"])
def test_packaged_http_is_opt_in_and_loopback(server, monkeypatch):
    monkeypatch.delenv("UNIFI_MCP_HOST", raising=False)
    monkeypatch.delenv("UNIFI_MCP_HTTP_ENABLED", raising=False)
    path = ROOT / f"apps/{server}/src/unifi_{server}_mcp/config/config.yaml"
    config = OmegaConf.load(path).server
    assert config.host == "127.0.0.1"
    assert str(config.http.enabled).lower() == "false"
    monkeypatch.setenv("UNIFI_MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("UNIFI_MCP_HTTP_ENABLED", "true")
    assert config.host == "0.0.0.0"
    assert str(config.http.enabled).lower() == "true"


def test_compose_publishes_only_loopback_and_keeps_relay_reachable():
    compose = yaml.safe_load((ROOT / "docker/docker-compose.yml").read_text())
    for server, port in [("network", 3000), ("protect", 3001), ("access", 3002)]:
        service = compose["services"][f"unifi-{server}-mcp"]
        assert service["ports"] == [f"127.0.0.1:{port}:{port}"]
        assert "UNIFI_MCP_HOST=0.0.0.0" in service["environment"]
        assert "UNIFI_MCP_HTTP_ENABLED=true" in service["environment"]
        relay_env = compose["services"]["unifi-mcp-relay"]["environment"]
        assert any(f"http://unifi-{server}-mcp:{port}" in value for value in relay_env)


SITEMANAGER_KEY_VARS = {
    "UNIFI_SITEMANAGER_API_KEY",
    "UNIFI_SITEMANAGER_API_KEY_FILE",
    "UNIFI_SITEMANAGER_API_KEY_COMMAND",
}


def test_compose_sitemanager_is_opt_in_loopback_and_outside_the_relay():
    compose = yaml.safe_load((ROOT / "docker/docker-compose.yml").read_text())
    service = compose["services"]["unifi-sitemanager-mcp"]
    assert service["profiles"] == ["sitemanager"]
    assert service["build"] == {"context": "..", "dockerfile": "apps/sitemanager/Dockerfile"}
    assert service["ports"] == ["127.0.0.1:3003:3003"]
    assert "env_file" not in service
    names = {entry.split("=", 1)[0] for entry in service["environment"]}
    assert names == SITEMANAGER_KEY_VARS | {
        "UNIFI_MCP_HTTP_ENABLED",
        "UNIFI_MCP_HTTP_TRANSPORT",
        "UNIFI_MCP_HOST",
        "UNIFI_MCP_PORT",
        "UNIFI_MCP_COMPOSE_ALLOWED_HOSTS_OVERRIDE",
        "UNIFI_MCP_COMPOSE_ALLOWED_HOSTS_OVERRIDE_SET",
        "UNIFI_MCP_INTERNAL_ALLOWED_HOSTS",
        "UNIFI_SITEMANAGER_MCP_HTTP_AUTH_TOKEN",
        "UNIFI_MCP_HTTP_AUTH_TOKEN",
    }
    # Passed through bare, so an unset token stays unset instead of empty.
    assert "UNIFI_SITEMANAGER_MCP_HTTP_AUTH_TOKEN" in service["environment"]
    assert "UNIFI_MCP_HTTP_AUTH_TOKEN" in service["environment"]
    assert "UNIFI_MCP_HTTP_TRANSPORT=streamable-http" in service["environment"]
    assert "UNIFI_MCP_PORT=3003" in service["environment"]

    relay = compose["services"]["unifi-mcp-relay"]
    assert "unifi-sitemanager-mcp" not in relay["depends_on"]
    assert not any("sitemanager" in value or ":3003" in value for value in relay["environment"])
    for name, other in compose["services"].items():
        if name != "unifi-sitemanager-mcp":
            assert "sitemanager" not in other.get("profiles", [])


def _resolved_compose_environments(
    tmp_path: Path,
    *,
    env_file_allowed_hosts: str | None,
    shell_allowed_hosts: str | None,
    profiles: tuple[str, ...] = (),
) -> dict[str, dict[str, str]]:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker is required to verify Compose environment precedence")

    docker_dir = tmp_path / "docker"
    run_dir = tmp_path / "run"
    docker_dir.mkdir(parents=True)
    run_dir.mkdir()
    compose_path = docker_dir / "docker-compose.yml"
    shutil.copy2(ROOT / "docker/docker-compose.yml", compose_path)

    env_lines = ["UNIFI_HOST=controller.example.com", "UNIFI_API_KEY=console-local-synthetic"]
    if env_file_allowed_hosts is not None:
        env_lines.append(f"UNIFI_MCP_ALLOWED_HOSTS={env_file_allowed_hosts}")
    (tmp_path / ".env").write_text("\n".join(env_lines) + "\n")

    command_env = os.environ.copy()
    command_env.pop("UNIFI_MCP_ALLOWED_HOSTS", None)
    if shell_allowed_hosts is not None:
        command_env["UNIFI_MCP_ALLOWED_HOSTS"] = shell_allowed_hosts

    result = subprocess.run(
        [
            docker,
            "compose",
            "-f",
            str(compose_path),
            *(arg for profile in profiles for arg in ("--profile", profile)),
            "config",
            "--format",
            "json",
        ],
        cwd=run_dir,
        env=command_env,
        check=True,
        capture_output=True,
        text=True,
    )
    services = json.loads(result.stdout)["services"]
    return {
        service_name: service["environment"]
        for service_name, service in services.items()
        if service_name in {"unifi-network-mcp", "unifi-protect-mcp", "unifi-access-mcp", "unifi-sitemanager-mcp"}
    }


@pytest.mark.parametrize(
    ("env_file_allowed_hosts", "shell_allowed_hosts"),
    [
        (None, None),
        ("env-file.example.com", None),
        ("env-file.example.com", "shell.example.com"),
        ("env-file.example.com", ""),
    ],
)
def test_compose_preserves_operator_allowed_hosts_and_required_internal_hosts(
    tmp_path: Path,
    env_file_allowed_hosts: str | None,
    shell_allowed_hosts: str | None,
):
    environments = _resolved_compose_environments(
        tmp_path,
        env_file_allowed_hosts=env_file_allowed_hosts,
        shell_allowed_hosts=shell_allowed_hosts,
    )

    for server, port in [("network", 3000), ("protect", 3001), ("access", 3002)]:
        environment = environments[f"unifi-{server}-mcp"]
        if env_file_allowed_hosts is None:
            assert "UNIFI_MCP_ALLOWED_HOSTS" not in environment
        else:
            assert environment["UNIFI_MCP_ALLOWED_HOSTS"] == env_file_allowed_hosts
        assert environment["UNIFI_MCP_COMPOSE_ALLOWED_HOSTS_OVERRIDE"] == (shell_allowed_hosts or "")
        assert environment["UNIFI_MCP_COMPOSE_ALLOWED_HOSTS_OVERRIDE_SET"] == (
            "true" if shell_allowed_hosts is not None else ""
        )

        internal_hosts = set(environment["UNIFI_MCP_INTERNAL_ALLOWED_HOSTS"].split(","))
        assert internal_hosts == {
            "localhost",
            f"localhost:{port}",
            "127.0.0.1",
            f"127.0.0.1:{port}",
            "host.docker.internal",
            f"host.docker.internal:{port}",
            f"unifi-{server}-mcp",
            f"unifi-{server}-mcp:{port}",
        }


@pytest.mark.parametrize("shell_allowed_hosts", [None, "shell.example.com", ""])
def test_compose_sitemanager_profile_resolves_with_only_its_own_variables(tmp_path: Path, shell_allowed_hosts):
    default = _resolved_compose_environments(
        tmp_path / "default", env_file_allowed_hosts=None, shell_allowed_hosts=None
    )
    assert len(default) == 3
    assert "unifi-sitemanager-mcp" not in default

    environments = _resolved_compose_environments(
        tmp_path / "profile",
        env_file_allowed_hosts="env-file.example.com",
        shell_allowed_hosts=shell_allowed_hosts,
        profiles=("sitemanager",),
    )
    assert len(environments) == 4
    environment = environments["unifi-sitemanager-mcp"]
    # The shared env file is not loaded: no console settings, no env-file hosts.
    for name in ("UNIFI_HOST", "UNIFI_API_KEY", "UNIFI_MCP_ALLOWED_HOSTS"):
        assert name not in environment
    assert environments["unifi-network-mcp"]["UNIFI_HOST"] == "controller.example.com"
    assert environment["UNIFI_MCP_COMPOSE_ALLOWED_HOSTS_OVERRIDE"] == (shell_allowed_hosts or "")
    assert environment["UNIFI_MCP_COMPOSE_ALLOWED_HOSTS_OVERRIDE_SET"] == (
        "true" if shell_allowed_hosts is not None else ""
    )
    assert set(environment["UNIFI_MCP_INTERNAL_ALLOWED_HOSTS"].split(",")) == {
        "localhost",
        "localhost:3003",
        "127.0.0.1",
        "127.0.0.1:3003",
        "host.docker.internal",
        "host.docker.internal:3003",
        "unifi-sitemanager-mcp",
        "unifi-sitemanager-mcp:3003",
    }
