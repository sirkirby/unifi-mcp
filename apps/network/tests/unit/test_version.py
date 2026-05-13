"""Test version detection via hatch-vcs.

This test ensures that the dynamic versioning from git tags is working correctly.
The version should be derived from git tags (e.g., v0.4.0 -> 0.4.0).
"""

import re
import subprocess
from pathlib import Path

import pytest


class TestVersion:
    """Tests for package versioning."""

    def test_version_is_available(self):
        """Verify that the package version can be retrieved."""
        from importlib.metadata import version

        pkg_version = version("unifi-network-mcp")
        assert pkg_version is not None
        assert len(pkg_version) > 0

    def test_version_format_is_valid(self):
        """Verify the version follows PEP 440 format."""
        from importlib.metadata import version

        pkg_version = version("unifi-network-mcp")

        # PEP 440 version pattern (simplified)
        # Matches: 0.4.0, 0.4.0.dev3, 0.4.0.dev3+gabc1234, 0.4.0+dirty, etc.
        pep440_pattern = r"^\d+\.\d+\.\d+(\.(dev|a|b|rc)\d+)?(\+[a-zA-Z0-9.]+)?$"

        assert re.match(pep440_pattern, pkg_version), (
            f"Version '{pkg_version}' does not match PEP 440 format.\n"
            f"Expected format like: 0.4.0, 0.4.0.dev3, 0.4.0.dev3+gabc1234"
        )

    def test_version_matches_git_tag(self):
        """Verify the version is derived from git tags."""
        from importlib.metadata import version

        pkg_version = version("unifi-network-mcp")

        # Get git describe output, scoped to this package's tag namespace so
        # sibling-package tags on the same commit (e.g. core/, api/) don't get
        # picked up as the closest tag. Mirrors the --match pattern that
        # hatch-vcs's git_describe_command uses in pyproject.toml.
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--match", "network/v*", "--match", "v*"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        if result.returncode != 0:
            pytest.skip("Git not available or no tags found")

        git_describe = result.stdout.strip()

        # Strip the network/v or leading v prefix to get a bare version string.
        git_version = git_describe
        for prefix in ("network/v", "v"):
            if git_version.startswith(prefix):
                git_version = git_version[len(prefix) :]
                break

        # Check if working tree is dirty (uncommitted changes)
        dirty_check = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )
        is_dirty = bool(dirty_check.stdout.strip())

        # The package version should be based on the git tag
        # For exact tag matches: v0.4.0 -> 0.4.0
        # For commits after tag: v0.4.0-3-gabc1234 -> 0.4.1.dev3+gabc1234
        # For dirty working tree: adds .dYYYYMMDD suffix and becomes dev version
        if is_dirty:
            # Dirty working tree - hatch-vcs generates dev version with date suffix
            assert ".d" in pkg_version or "dev" in pkg_version, (
                f"Package version '{pkg_version}' should be a dev version for dirty working tree"
            )
        elif "-" not in git_describe:
            # Exact tag match with clean tree - versions should be equal
            assert pkg_version == git_version, f"Package version '{pkg_version}' does not match git tag '{git_version}'"
        else:
            # Commits after tag - version should contain dev
            assert "dev" in pkg_version or "+" in pkg_version, (
                f"Package version '{pkg_version}' should be a dev version for git describe '{git_describe}'"
            )

    def test_pyproject_has_dynamic_version(self):
        """Verify pyproject.toml is configured for dynamic versioning."""
        import tomllib

        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"

        with open(pyproject_path, "rb") as f:
            pyproject = tomllib.load(f)

        # Check that version is in dynamic list
        assert "dynamic" in pyproject.get("project", {}), "pyproject.toml should have 'dynamic' field in [project]"
        assert "version" in pyproject["project"]["dynamic"], "pyproject.toml should have 'version' in dynamic list"

        # Check that hatch-vcs is configured
        assert "tool" in pyproject, "pyproject.toml should have [tool] section"
        assert "hatch" in pyproject["tool"], "pyproject.toml should have [tool.hatch] section"
        assert "version" in pyproject["tool"]["hatch"], "pyproject.toml should have [tool.hatch.version] section"
        assert pyproject["tool"]["hatch"]["version"].get("source") == "vcs", (
            "pyproject.toml should have source = 'vcs' in [tool.hatch.version]"
        )

    def test_hatch_vcs_in_build_requires(self):
        """Verify hatch-vcs is in build-system requires."""
        import tomllib

        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"

        with open(pyproject_path, "rb") as f:
            pyproject = tomllib.load(f)

        build_requires = pyproject.get("build-system", {}).get("requires", [])

        assert any("hatch-vcs" in req for req in build_requires), (
            "pyproject.toml should have 'hatch-vcs' in build-system.requires"
        )
