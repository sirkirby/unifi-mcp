#!/usr/bin/env python3
"""Generate path-scoped GitHub release notes for this monorepo.

Usage:
    python scripts/generate_release_notes.py --tag network/v0.14.12
    python scripts/generate_release_notes.py --tag relay/v0.1.3 --output /tmp/notes.md

The GitHub generated-notes API is repository-scoped. In this monorepo that
pulls unrelated product changes into package releases, so this script scopes
the changelog to files relevant to the tagged package.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_URL = "https://github.com/sirkirby/unifi-mcp"
REPO_ROOT = Path(__file__).parent.parent if Path(__file__).parent.name == "scripts" else Path(__file__).parent

PLUGIN_SYNC_SUBJECT = "chore(plugins): sync plugin versions to current release tags"


@dataclass(frozen=True)
class PathGroup:
    """A named group of paths that matter to a package release."""

    title: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class PackageConfig:
    """Release-note configuration for one tagged package family."""

    key: str
    display_name: str
    pypi_package: str
    install_command: str
    path_groups: tuple[PathGroup, ...]
    legacy_plain_v_tags: bool = False
    badge_markdown: str | None = None


@dataclass(frozen=True)
class ReleaseTag:
    """Parsed tag metadata."""

    tag: str
    package_key: str
    version: str


@dataclass(frozen=True)
class CommitInfo:
    """Git commit metadata needed to render release notes."""

    sha: str
    subject: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class ClassifiedCommit:
    """A relevant commit assigned to a release-note section."""

    commit: CommitInfo
    group_title: str


COMMON_PACKAGE_PATHS = (
    "pyproject.toml",
    "uv.lock",
)

APP_CONFIGS = {
    "network": PackageConfig(
        key="network",
        display_name="UniFi Network MCP",
        pypi_package="unifi-network-mcp",
        install_command="uvx unifi-network-mcp=={version}",
        legacy_plain_v_tags=True,
        path_groups=(
            PathGroup("Network MCP", ("apps/network/", "plugins/unifi-network/")),
            PathGroup("Shared Libraries", ("packages/unifi-core/", "packages/unifi-mcp-shared/")),
            PathGroup(
                "Release Infrastructure",
                (
                    ".github/workflows/publish-network.yml",
                    ".github/workflows/docker-network.yml",
                    ".github/workflows/test-network.yml",
                    ".github/workflows/bump-plugin-versions.yml",
                    *COMMON_PACKAGE_PATHS,
                ),
            ),
        ),
    ),
    "protect": PackageConfig(
        key="protect",
        display_name="UniFi Protect MCP",
        pypi_package="unifi-protect-mcp",
        install_command="uvx unifi-protect-mcp=={version}",
        path_groups=(
            PathGroup("Protect MCP", ("apps/protect/", "plugins/unifi-protect/")),
            PathGroup("Shared Libraries", ("packages/unifi-core/", "packages/unifi-mcp-shared/")),
            PathGroup(
                "Release Infrastructure",
                (
                    ".github/workflows/publish-protect.yml",
                    ".github/workflows/docker-protect.yml",
                    ".github/workflows/test-protect.yml",
                    ".github/workflows/bump-plugin-versions.yml",
                    *COMMON_PACKAGE_PATHS,
                ),
            ),
        ),
    ),
    "access": PackageConfig(
        key="access",
        display_name="UniFi Access MCP",
        pypi_package="unifi-access-mcp",
        install_command="uvx unifi-access-mcp=={version}",
        path_groups=(
            PathGroup("Access MCP", ("apps/access/", "plugins/unifi-access/")),
            PathGroup("Shared Libraries", ("packages/unifi-core/", "packages/unifi-mcp-shared/")),
            PathGroup(
                "Release Infrastructure",
                (
                    ".github/workflows/publish-access.yml",
                    ".github/workflows/test-access.yml",
                    ".github/workflows/bump-plugin-versions.yml",
                    *COMMON_PACKAGE_PATHS,
                ),
            ),
        ),
    ),
    "core": PackageConfig(
        key="core",
        display_name="UniFi Core",
        pypi_package="unifi-core",
        install_command="pip install unifi-core=={version}",
        path_groups=(
            PathGroup("Core Library", ("packages/unifi-core/",)),
            PathGroup(
                "Release Infrastructure",
                (".github/workflows/publish-core.yml", *COMMON_PACKAGE_PATHS),
            ),
        ),
    ),
    "shared": PackageConfig(
        key="shared",
        display_name="UniFi MCP Shared",
        pypi_package="unifi-mcp-shared",
        install_command="pip install unifi-mcp-shared=={version}",
        path_groups=(
            PathGroup("Shared Library", ("packages/unifi-mcp-shared/",)),
            PathGroup(
                "Release Infrastructure",
                (".github/workflows/publish-shared.yml", *COMMON_PACKAGE_PATHS),
            ),
        ),
    ),
    "relay": PackageConfig(
        key="relay",
        display_name="UniFi MCP Relay",
        pypi_package="unifi-mcp-relay",
        install_command="pip install unifi-mcp-relay=={version}",
        path_groups=(
            PathGroup("Relay", ("packages/unifi-mcp-relay/",)),
            PathGroup("Shared Library", ("packages/unifi-mcp-shared/",)),
            PathGroup(
                "Release Infrastructure",
                (
                    ".github/workflows/publish-relay.yml",
                    ".github/workflows/docker-relay.yml",
                    *COMMON_PACKAGE_PATHS,
                ),
            ),
        ),
    ),
    "worker": PackageConfig(
        key="worker",
        display_name="UniFi MCP Worker",
        pypi_package="unifi-mcp-worker",
        install_command="npm install -g unifi-mcp-worker@{version}",
        path_groups=(
            PathGroup("Worker", ("apps/worker/",)),
            PathGroup(
                "Release Infrastructure",
                (
                    ".github/workflows/release-worker.yml",
                    ".github/workflows/test-worker.yml",
                ),
            ),
        ),
        badge_markdown="[![npm](https://img.shields.io/npm/v/unifi-mcp-worker)]"
        "(https://www.npmjs.com/package/unifi-mcp-worker/v/{version})",
    ),
}

PRIMARY_PATTERNS_BY_PACKAGE = {config.key: config.path_groups[0].patterns for config in APP_CONFIGS.values()}
PACKAGE_KEYWORDS = tuple(APP_CONFIGS)
PRODUCT_KEYS = ("network", "protect", "access", "relay", "worker")


def run_git(args: list[str]) -> str:
    """Run a git command and return stdout."""

    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def parse_release_tag(tag: str) -> ReleaseTag:
    """Parse a package release tag such as ``network/v0.14.12``."""

    match = re.match(
        r"^(?P<key>network|protect|access|core|shared|relay|worker)/v(?P<version>\d+(?:\.\d+)*(?:\S*)?)$",
        tag,
    )
    if match:
        return ReleaseTag(tag=tag, package_key=match.group("key"), version=match.group("version"))

    legacy_match = re.match(r"^v(?P<version>\d+(?:\.\d+)*(?:\S*)?)$", tag)
    if legacy_match:
        return ReleaseTag(tag=tag, package_key="network", version=legacy_match.group("version"))

    raise ValueError(f"Unsupported release tag '{tag}'")


def list_package_tags(config: PackageConfig) -> list[str]:
    """List tags for a package, newest version first."""

    tags = run_git(["tag", "--list", f"{config.key}/v*", "--sort=-version:refname"]).splitlines()
    if config.legacy_plain_v_tags:
        tags.extend(run_git(["tag", "--list", "v*.*.*", "--sort=-version:refname"]).splitlines())
    return [tag for tag in tags if tag]


def find_previous_tag(tag: str, config: PackageConfig) -> str | None:
    """Find the previous version tag for the same package family."""

    tags = list_package_tags(config)
    if tag not in tags:
        return None

    index = tags.index(tag)
    if index + 1 >= len(tags):
        return None
    return tags[index + 1]


def list_commits(start_tag: str | None, end_tag: str) -> list[CommitInfo]:
    """Return commits in release-note order for ``start_tag..end_tag``."""

    range_spec = f"{start_tag}..{end_tag}" if start_tag else end_tag
    output = run_git(["log", "--reverse", "--format=%H%x00%s", range_spec])
    if not output:
        return []

    commits: list[CommitInfo] = []
    for line in output.splitlines():
        sha, subject = line.split("\0", 1)
        files_output = run_git(["diff-tree", "--no-commit-id", "--name-only", "-r", sha])
        files = tuple(file for file in files_output.splitlines() if file)
        commits.append(CommitInfo(sha=sha, subject=subject, files=files))
    return commits


def path_matches(path: str, pattern: str) -> bool:
    """Return whether a changed file path matches a configured pattern."""

    if pattern.endswith("/"):
        return path.startswith(pattern)
    if any(char in pattern for char in "*?[]"):
        return fnmatch.fnmatch(path, pattern)
    return path == pattern


def classify_commit(commit: CommitInfo, config: PackageConfig) -> ClassifiedCommit | None:
    """Assign a commit to the first matching path group."""

    if commit.subject == PLUGIN_SYNC_SUBJECT:
        return None

    matched_primary = any(
        path_matches(path, pattern) for path in commit.files for pattern in PRIMARY_PATTERNS_BY_PACKAGE[config.key]
    )
    touched_other_primary = any(
        other_key in PRODUCT_KEYS
        and other_key != config.key
        and any(path_matches(path, pattern) for path in commit.files for pattern in patterns)
        for other_key, patterns in PRIMARY_PATTERNS_BY_PACKAGE.items()
    )

    if not matched_primary and touched_other_primary and config.key != "shared":
        return None

    subject_lower = commit.subject.lower()
    if not matched_primary and any(
        other_key != config.key and re.search(rf"\b{re.escape(other_key)}\b", subject_lower)
        for other_key in PACKAGE_KEYWORDS
    ):
        return None

    for group in config.path_groups:
        if any(path_matches(path, pattern) for path in commit.files for pattern in group.patterns):
            return ClassifiedCommit(commit=commit, group_title=group.title)
    return None


def classify_commits(
    commits: Iterable[CommitInfo], config: PackageConfig
) -> tuple[list[ClassifiedCommit], list[CommitInfo]]:
    """Split commits into relevant and omitted lists."""

    relevant: list[ClassifiedCommit] = []
    omitted: list[CommitInfo] = []

    for commit in commits:
        classified = classify_commit(commit, config)
        if classified:
            relevant.append(classified)
        else:
            omitted.append(commit)

    return relevant, omitted


def subject_with_links(subject: str) -> str:
    """Link PR references in a commit subject."""

    def replace(match: re.Match[str]) -> str:
        number = match.group(1)
        return f"[#{number}]({REPO_URL}/pull/{number})"

    return re.sub(r"#(\d+)", replace, subject)


def render_release_notes(
    release_tag: ReleaseTag,
    config: PackageConfig,
    previous_tag: str | None,
    relevant: list[ClassifiedCommit],
    omitted: list[CommitInfo],
) -> str:
    """Render release notes as Markdown."""

    lines = [
        "Install or upgrade:",
        "```bash",
        config.install_command.format(version=release_tag.version),
        "```",
        "",
        config.badge_markdown.format(version=release_tag.version)
        if config.badge_markdown
        else f"[![PyPI](https://img.shields.io/pypi/v/{config.pypi_package})]"
        f"(https://pypi.org/project/{config.pypi_package}/{release_tag.version}/)",
        "",
        "## What's Changed",
        "",
    ]

    if relevant:
        grouped: dict[str, list[CommitInfo]] = {}
        for item in relevant:
            grouped.setdefault(item.group_title, []).append(item.commit)

        for group in config.path_groups:
            commits = grouped.get(group.title, [])
            if not commits:
                continue
            lines.extend([f"### {group.title}", ""])
            for commit in commits:
                lines.append(f"* {subject_with_links(commit.subject)} ({commit.sha[:7]})")
            lines.append("")
    else:
        lines.extend(["No package-scoped code changes were detected for this tag.", ""])

    if omitted:
        lines.extend(
            [
                f"_Omitted {len(omitted)} unrelated monorepo commit"
                f"{'' if len(omitted) == 1 else 's'} from these notes._",
                "",
            ]
        )

    if previous_tag:
        lines.append(f"**Full Changelog**: {REPO_URL}/compare/{previous_tag}...{release_tag.tag}")
    else:
        lines.append(f"**Full Changelog**: {REPO_URL}/commits/{release_tag.tag}")

    return "\n".join(lines).rstrip() + "\n"


def generate_notes(tag: str) -> str:
    """Generate release notes for a tag."""

    release_tag = parse_release_tag(tag)
    config = APP_CONFIGS[release_tag.package_key]
    previous_tag = find_previous_tag(tag, config)
    commits = list_commits(previous_tag, tag)
    relevant, omitted = classify_commits(commits, config)
    return render_release_notes(release_tag, config, previous_tag, relevant, omitted)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate path-scoped release notes")
    parser.add_argument("--tag", required=True, help="Release tag, e.g. network/v0.14.12")
    parser.add_argument("--output", type=Path, help="Write notes to this file instead of stdout")
    args = parser.parse_args()

    try:
        notes = generate_notes(args.tag)
    except (subprocess.CalledProcessError, ValueError) as exc:
        print(f"Failed to generate release notes: {exc}", file=sys.stderr)
        return 1

    if args.output:
        args.output.write_text(notes, encoding="utf-8")
    else:
        print(notes, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
