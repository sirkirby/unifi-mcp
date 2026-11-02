#!/usr/bin/env python3
"""Print the unifi-core and unifi-mcp-shared versions for a Docker build.

An image build has no git metadata, so hatch-vcs cannot work these out inside it.
A package unchanged since its tag gets that tag's version, even when other
packages have moved on. A changed package gets the next patch's dev version, the
scheme hatch-vcs uses, so it still satisfies a floor on the release it builds on.

Prints ``core=<version>`` and ``shared=<version>``, for ``$GITHUB_OUTPUT``. Needs
full history and tags.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

PACKAGES = {"core": "unifi-core", "shared": "unifi-mcp-shared"}
NO_TAG_VERSION = "0.0.0"
# Each package's ``tag_regex`` keeps only the leading numbers of a tag.
_RELEASE_RE = re.compile(r"\d+(?:\.\d+)*")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)


def next_dev_version(base: str, commits: int, sha: str) -> str:
    """The dev version of the patch after ``base``, which PEP 440 orders after ``base``."""
    *leading, patch = base.split(".")
    return ".".join([*leading, str(int(patch) + 1)]) + f".dev{commits}+g{sha}"


def package_version(root: Path, prefix: str, package: str) -> str:
    described = _git(root, "describe", "--tags", "--match", f"{prefix}/v*", "--abbrev=0", "HEAD")
    if described.returncode != 0:
        return NO_TAG_VERSION
    tag = described.stdout.strip()
    release = _RELEASE_RE.match(tag.removeprefix(f"{prefix}/v"))
    if release is None:
        return NO_TAG_VERSION
    base = release.group()
    paths = [f"packages/{package}/src", f"packages/{package}/pyproject.toml"]
    if _git(root, "diff", "--quiet", tag, "HEAD", "--", *paths).returncode == 0:
        return base
    commits = _git(root, "rev-list", "--count", f"{tag}..HEAD", "--", *paths).stdout.strip()
    sha = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()
    return next_dev_version(base, int(commits), sha)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    for prefix, package in PACKAGES.items():
        print(f"{prefix}={package_version(root, prefix, package)}")


if __name__ == "__main__":
    main()
