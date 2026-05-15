"""Tests for path-scoped release note generation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_script_path = Path(__file__).parent.parent / "scripts" / "generate_release_notes.py"
_spec = importlib.util.spec_from_file_location("generate_release_notes", _script_path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

APP_CONFIGS = _mod.APP_CONFIGS
PLUGIN_SYNC_SUBJECT = _mod.PLUGIN_SYNC_SUBJECT
ClassifiedCommit = _mod.ClassifiedCommit
CommitInfo = _mod.CommitInfo
ReleaseTag = _mod.ReleaseTag
classify_commit = _mod.classify_commit
classify_commits = _mod.classify_commits
parse_release_tag = _mod.parse_release_tag
render_release_notes = _mod.render_release_notes
subject_with_links = _mod.subject_with_links


class TestParseReleaseTag:
    def test_prefixed_tag(self):
        tag = parse_release_tag("relay/v0.1.3")

        assert tag.package_key == "relay"
        assert tag.version == "0.1.3"

    def test_worker_tag(self):
        tag = parse_release_tag("worker/v1.3.1")

        assert tag.package_key == "worker"
        assert tag.version == "1.3.1"

    def test_legacy_plain_tag_maps_to_network(self):
        tag = parse_release_tag("v0.7.0")

        assert tag.package_key == "network"
        assert tag.version == "0.7.0"

    def test_rejects_unknown_prefix(self):
        with pytest.raises(ValueError, match="Unsupported release tag"):
            parse_release_tag("docs/v1.0.0")


class TestClassifyCommit:
    def test_relay_commit_matches_relay_group(self):
        commit = CommitInfo(
            sha="abc123",
            subject="fix(relay): handle reconnects",
            files=("packages/unifi-mcp-relay/src/unifi_mcp_relay/client.py",),
        )

        classified = classify_commit(commit, APP_CONFIGS["relay"])

        assert classified is not None
        assert classified.group_title == "Relay"

    def test_network_commit_does_not_match_relay(self):
        commit = CommitInfo(
            sha="abc123",
            subject="fix(network): update firewall",
            files=("apps/network/src/unifi_network_mcp/tools/firewall.py",),
        )

        assert classify_commit(commit, APP_CONFIGS["relay"]) is None

    def test_shared_commit_matches_relay_shared_group(self):
        commit = CommitInfo(
            sha="abc123",
            subject="feat(tool-index): add filtering (#145)",
            files=("packages/unifi-mcp-shared/src/unifi_mcp_shared/tool_index.py",),
        )

        classified = classify_commit(commit, APP_CONFIGS["relay"])

        assert classified is not None
        assert classified.group_title == "Shared Library"

    def test_other_product_commit_with_shared_file_does_not_match_relay(self):
        commit = CommitInfo(
            sha="abc123",
            subject="fix(network): firewall validator",
            files=(
                "apps/network/src/unifi_network_mcp/tools/firewall.py",
                "packages/unifi-mcp-shared/src/unifi_mcp_shared/validators.py",
            ),
        )

        assert classify_commit(commit, APP_CONFIGS["relay"]) is None

    def test_global_lockfile_only_commit_with_other_product_subject_is_omitted(self):
        commit = CommitInfo(
            sha="abc123",
            subject="chore(security): package security updates for protect mcp server",
            files=("uv.lock",),
        )

        assert classify_commit(commit, APP_CONFIGS["relay"]) is None

    def test_plugin_sync_commit_is_omitted_even_when_path_matches(self):
        commit = CommitInfo(
            sha="abc123",
            subject=PLUGIN_SYNC_SUBJECT,
            files=("plugins/unifi-network/.claude-plugin/plugin.json",),
        )

        assert classify_commit(commit, APP_CONFIGS["network"]) is None

    def test_worker_commit_matches_worker_group(self):
        commit = CommitInfo(
            sha="abc123",
            subject="fix(worker): preserve tool titles",
            files=("apps/worker/worker/src/relay-object.ts",),
        )

        classified = classify_commit(commit, APP_CONFIGS["worker"])

        assert classified is not None
        assert classified.group_title == "Worker"

    def test_worker_commit_does_not_match_relay(self):
        commit = CommitInfo(
            sha="abc123",
            subject="fix(worker): preserve tool titles",
            files=("apps/worker/worker/src/relay-object.ts",),
        )

        assert classify_commit(commit, APP_CONFIGS["relay"]) is None


class TestClassifyCommits:
    def test_splits_relevant_and_omitted(self):
        commits = [
            CommitInfo(
                sha="rel123",
                subject="fix(relay): reconnect cleanly",
                files=("packages/unifi-mcp-relay/src/unifi_mcp_relay/client.py",),
            ),
            CommitInfo(
                sha="net123",
                subject="fix(network): firewall",
                files=("apps/network/src/unifi_network_mcp/tools/firewall.py",),
            ),
        ]

        relevant, omitted = classify_commits(commits, APP_CONFIGS["relay"])

        assert [item.commit.sha for item in relevant] == ["rel123"]
        assert [commit.sha for commit in omitted] == ["net123"]


class TestRendering:
    def test_subject_links_pr_references(self):
        subject = subject_with_links("fix(network): firewall (#153)")

        assert "[#153](https://github.com/sirkirby/unifi-mcp/pull/153)" in subject

    def test_render_groups_changes_and_omitted_count(self):
        config = APP_CONFIGS["relay"]
        release_tag = ReleaseTag(tag="relay/v0.1.3", package_key="relay", version="0.1.3")
        relevant = [
            ClassifiedCommit(
                commit=CommitInfo(
                    sha="rel123456789",
                    subject="fix(relay): reconnect cleanly (#10)",
                    files=("packages/unifi-mcp-relay/src/unifi_mcp_relay/client.py",),
                ),
                group_title="Relay",
            )
        ]
        omitted = [
            CommitInfo(
                sha="net123",
                subject="fix(network): firewall",
                files=("apps/network/src/unifi_network_mcp/tools/firewall.py",),
            )
        ]

        notes = render_release_notes(release_tag, config, "relay/v0.1.2", relevant, omitted)

        assert "pip install unifi-mcp-relay==0.1.3" in notes
        assert "### Relay" in notes
        assert "fix(relay): reconnect cleanly" in notes
        assert "Omitted 1 unrelated monorepo commit" in notes
        assert "compare/relay/v0.1.2...relay/v0.1.3" in notes

    def test_render_no_relevant_changes(self):
        config = APP_CONFIGS["core"]
        release_tag = ReleaseTag(tag="core/v0.1.0", package_key="core", version="0.1.0")

        notes = render_release_notes(release_tag, config, None, [], [])

        assert "No package-scoped code changes were detected" in notes
        assert "commits/core/v0.1.0" in notes

    def test_render_worker_uses_npm_install_and_badge(self):
        config = APP_CONFIGS["worker"]
        release_tag = ReleaseTag(tag="worker/v1.3.1", package_key="worker", version="1.3.1")

        notes = render_release_notes(release_tag, config, None, [], [])

        assert "npm install -g unifi-mcp-worker@1.3.1" in notes
        assert "https://img.shields.io/npm/v/unifi-mcp-worker" in notes
        assert "https://www.npmjs.com/package/unifi-mcp-worker/v/1.3.1" in notes
