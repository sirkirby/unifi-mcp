"""Docker images report each package's own version, from every workflow that builds one."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("package_versions", ROOT / "scripts" / "package_versions.py")
package_versions = importlib.util.module_from_spec(_spec)
sys.modules["package_versions"] = package_versions
_spec.loader.exec_module(package_versions)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(repo: Path, path: str, text: str) -> None:
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"change {path}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    _commit(tmp_path, "packages/unifi-core/src/core.py", "one\n")
    _git(tmp_path, "tag", "core/v0.4.83")
    return tmp_path


def test_a_package_on_its_tag_reports_the_tag(repo: Path) -> None:
    assert package_versions.package_version(repo, "core", "unifi-core") == "0.4.83"


def test_changes_elsewhere_leave_a_package_on_its_tag(repo: Path) -> None:
    _commit(repo, "apps/network/src/network.py", "one\n")
    _commit(repo, "packages/unifi-core/tests/test_core.py", "one\n")

    assert package_versions.package_version(repo, "core", "unifi-core") == "0.4.83"


@pytest.mark.parametrize(
    "changed",
    ["packages/unifi-core/src/core.py", "packages/unifi-core/pyproject.toml"],
    ids=["source", "metadata"],
)
def test_a_changed_package_sorts_after_the_release_it_builds_on(repo: Path, changed: str) -> None:
    _commit(repo, changed, "two\n")
    sha = _git(repo, "rev-parse", "--short", "HEAD")

    version = package_versions.package_version(repo, "core", "unifi-core")

    assert version == f"0.4.84.dev1+g{sha}"
    assert Version(version) > Version("0.4.83")
    assert version in SpecifierSet(">=0.4.83,<0.5", prereleases=True)


@pytest.mark.parametrize("tag", ["core/v0.4.85-rc1", "core/v0.4.85rc1", "core/v0.4.85-beta.2"])
def test_a_prerelease_tag_reads_as_its_release_as_the_package_does(repo: Path, tag: str) -> None:
    """Each package's ``tag_regex`` keeps only the leading numbers, and an image build must not crash on the rest."""
    _commit(repo, "packages/unifi-core/src/core.py", "two\n")
    _git(repo, "tag", tag)

    assert package_versions.package_version(repo, "core", "unifi-core") == "0.4.85"

    _commit(repo, "packages/unifi-core/src/core.py", "three\n")
    sha = _git(repo, "rev-parse", "--short", "HEAD")

    assert package_versions.package_version(repo, "core", "unifi-core") == f"0.4.86.dev1+g{sha}"


def test_a_tag_with_no_version_reports_the_fallback(repo: Path) -> None:
    _commit(repo, "packages/unifi-core/src/core.py", "two\n")
    _git(repo, "tag", "core/vnext")

    assert package_versions.package_version(repo, "core", "unifi-core") == "0.0.0"


def test_a_package_with_no_tag_reports_the_fallback(repo: Path) -> None:
    assert package_versions.package_version(repo, "shared", "unifi-mcp-shared") == "0.0.0"


def _image_builds() -> list[tuple[Path, Path]]:
    builds = []
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = workflow.read_text()
        if "docker/build-push-action" in text:
            for match in re.finditer(r"^\s+file:\s+(\S*Dockerfile)\s*$", text, re.MULTILINE):
                builds.append((workflow, ROOT / match.group(1)))
    return builds


def test_every_image_build_is_found() -> None:
    names = {workflow.name for workflow, _ in _image_builds()}

    for product in ("network", "protect", "access", "api", "relay"):
        assert f"docker-{product}.yml" in names
        assert f"release-{product}.yml" in names


@pytest.mark.parametrize(
    ("workflow", "dockerfile"),
    _image_builds(),
    ids=lambda path: f"{path.parent.name}/{path.name}",
)
def test_a_workflow_passes_every_package_version_its_image_declares(workflow: Path, dockerfile: Path) -> None:
    """A workflow that omits one publishes the Dockerfile's placeholder as the package's version."""
    declared = {"core": "CORE_VERSION", "shared": "SHARED_VERSION"}
    text = workflow.read_text()

    for output, arg in declared.items():
        passed = f"{arg}=${{{{ steps.package_versions.outputs.{output} }}}}" in text
        assert passed == (f"ARG {arg}=" in dockerfile.read_text()), f"{workflow.name} and {arg}"


def test_the_shared_build_step_is_used_wherever_versions_are_passed() -> None:
    for workflow, _ in _image_builds():
        assert "uses: ./.github/actions/package-versions" in workflow.read_text(), workflow.name
