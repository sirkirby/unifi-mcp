"""Tests for server.json manifest generation (all 3 apps)."""

from __future__ import annotations

# Import the shared script as a module
import importlib.util
import json
from pathlib import Path

import pytest

_script_path = Path(__file__).parent.parent / "scripts" / "generate_server_manifest.py"
_spec = importlib.util.spec_from_file_location("generate_server_manifest", _script_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

build_server_manifest = _mod.build_server_manifest
write_server_manifest = _mod.write_server_manifest
APP_CONFIGS = _mod.APP_CONFIGS


@pytest.mark.parametrize("app_name", ["network", "protect", "access"])
class TestServerManifestAllApps:
    """Test that generated server.json conforms to MCP Registry schema for all apps."""

    def test_schema_url_present(self, app_name):
        manifest = build_server_manifest(app_name, "0.1.0")
        assert manifest["$schema"] == "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"

    def test_name_uses_reverse_dns(self, app_name):
        manifest = build_server_manifest(app_name, "0.1.0")
        assert manifest["name"] == f"io.github.sirkirby/unifi-{app_name}-mcp"

    def test_version_from_argument(self, app_name):
        manifest = build_server_manifest(app_name, "1.2.3")
        assert manifest["version"] == "1.2.3"

    def test_repository_includes_subfolder(self, app_name):
        manifest = build_server_manifest(app_name, "0.1.0")
        repo = manifest["repository"]
        assert repo["url"] == "https://github.com/sirkirby/unifi-mcp"
        assert repo["source"] == "github"
        assert repo["subfolder"] == f"apps/{app_name}"

    def test_pypi_package_entry(self, app_name):
        manifest = build_server_manifest(app_name, "0.1.0")
        packages = manifest["packages"]
        assert len(packages) == 1
        pkg = packages[0]
        assert pkg["registryType"] == "pypi"
        assert pkg["identifier"] == f"unifi-{app_name}-mcp"
        assert pkg["transport"] == {"type": "stdio"}

    def test_required_env_vars_present(self, app_name):
        manifest = build_server_manifest(app_name, "0.1.0")
        env_vars = manifest["packages"][0]["environmentVariables"]
        names = [v["name"] for v in env_vars]
        assert "UNIFI_HOST" in names
        assert "UNIFI_USERNAME" in names
        assert "UNIFI_PASSWORD" in names

    def test_secrets_marked_as_secret(self, app_name):
        manifest = build_server_manifest(app_name, "0.1.0")
        env_vars = manifest["packages"][0]["environmentVariables"]
        secret_vars = {v["name"]: v for v in env_vars if v.get("isSecret")}
        assert "UNIFI_USERNAME" in secret_vars
        assert "UNIFI_PASSWORD" in secret_vars
        assert "UNIFI_API_KEY" in secret_vars

    def test_output_is_valid_json(self, app_name, tmp_path):
        output = tmp_path / "server.json"
        write_server_manifest(app_name, "0.1.0", output)
        data = json.loads(output.read_text())
        assert data["name"] == f"io.github.sirkirby/unifi-{app_name}-mcp"


class TestAppSpecificConfigs:
    """Test app-specific configuration differences."""

    def test_network_has_site_var(self):
        manifest = build_server_manifest("network", "0.1.0")
        names = [v["name"] for v in manifest["packages"][0]["environmentVariables"]]
        assert "UNIFI_SITE" in names

    def test_protect_has_no_site_var(self):
        manifest = build_server_manifest("protect", "0.1.0")
        names = [v["name"] for v in manifest["packages"][0]["environmentVariables"]]
        assert "UNIFI_SITE" not in names

    def test_all_apps_configured(self):
        assert set(APP_CONFIGS.keys()) == {"network", "protect", "access"}

    def test_invalid_app_raises(self):
        with pytest.raises(ValueError, match="Unknown app"):
            build_server_manifest("invalid", "0.1.0")
