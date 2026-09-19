from __future__ import annotations

from pathlib import Path

GUIDE = Path("docs/agent-install.md")
RESEARCH = Path("docs/research/2026-09-19-agent-installation-options.md")
README = Path("README.md")
SETUP_SKILLS = (
    Path("plugins/unifi-network/skills/unifi-network-setup/SKILL.md"),
    Path("plugins/unifi-protect/skills/unifi-protect-setup/SKILL.md"),
    Path("plugins/unifi-access/skills/unifi-access-setup/SKILL.md"),
)


def test_readme_agent_prompt_points_to_canonical_guide() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "## Quick Start\n\n### Install with your agent" in readme
    assert "https://github.com/sirkirby/unifi-mcp/blob/main/docs/agent-install.md" in readme
    assert "Do not ask me to paste a password or API key into chat" in readme
    assert "Wait for my confirmation" in readme
    assert "explicitly deny create, update, and delete" in readme


def test_skills_install_examples_are_scoped_to_public_product_trees() -> None:
    guide = GUIDE.read_text(encoding="utf-8")

    for product in ("unifi-network", "unifi-protect", "unifi-access", "cross-product"):
        assert f"npx skills add https://github.com/sirkirby/unifi-mcp/tree/main/plugins/{product}" in guide

    assert "Do not use `npx skills add sirkirby/unifi-mcp`" in guide
    assert "These commands install instructions, not the MCP process" in guide


def test_current_manual_clients_are_named_accurately() -> None:
    guide = GUIDE.read_text(encoding="utf-8")

    assert "## Native OpenCode MCP setup" in guide
    assert "OpenCode supports local MCP servers directly" in guide
    assert "Antigravity CLI / IDE" in guide
    assert "Devin Local in Devin Desktop / Devin CLI" in guide
    assert "Cascade in Devin Desktop" in guide
    assert "devin mcp add unifi-network" in guide
    assert "Devin Settings > Cascade > MCP Servers" in guide
    assert "OpenCode npm plugin is worth a small packaging prototype" in guide
    assert "### Gemini CLI" not in guide
    assert "### Windsurf" not in guide


def test_antigravity_paths_match_current_official_documentation() -> None:
    research = RESEARCH.read_text(encoding="utf-8")

    assert "`~/.gemini/config/mcp_config.json` globally" in research
    assert "`.agents/mcp_config.json` per workspace" in research
    assert "~/.gemini/antigravity-cli/mcp_config.json" not in research


def test_agent_guardrails_preserve_secrets_and_confirmation_mode() -> None:
    guide = GUIDE.read_text(encoding="utf-8")

    assert "Do not ask the user to paste a password or API key into the chat" in guide
    assert "Explicitly set the selected server's permission mode to `confirm`" in guide
    assert "product-scoped category overrides" in guide
    assert "wait for confirmation" in guide
    assert "No secret was printed" in guide
    assert "When session authentication is selected" in guide
    assert "API-key-only setup does not require that" in guide


def test_setup_skills_handle_standalone_skills_installs() -> None:
    for skill_path in SETUP_SKILLS:
        skill = skill_path.read_text(encoding="utf-8")
        assert "standalone `npx skills`" in skill
        assert "docs/agent-install.md" in skill
        assert "does not install or register the MCP server" in skill


def test_setup_skills_never_request_or_pass_plaintext_secrets() -> None:
    forbidden = (
        "ask for the API key",
        "ask for the key",
        "PASSWORD=<password>",
        "API_KEY=<api-key>",
    )

    for skill_path in SETUP_SKILLS:
        skill = skill_path.read_text(encoding="utf-8")
        normalized_skill = " ".join(skill.split())
        assert "Never ask the user to send" in normalized_skill
        assert "_FILE=<absolute-path>" in skill
        for unsafe_text in forbidden:
            assert unsafe_text not in normalized_skill


def test_claude_migrations_clear_every_credential_provider_spelling() -> None:
    for product, skill_path in zip(("NETWORK", "PROTECT", "ACCESS"), SETUP_SKILLS, strict=True):
        skill = skill_path.read_text(encoding="utf-8")
        for secret in ("PASSWORD", "API_KEY"):
            for suffix in ("", "_FILE", "_COMMAND"):
                assert f"`UNIFI_{product}_{secret}{suffix}`" in skill

    protect_skill = SETUP_SKILLS[1].read_text(encoding="utf-8")
    assert "Before changing or skipping API-key setup" in protect_skill


def test_guided_setup_defaults_to_read_only_policy_gates() -> None:
    for product, skill_path in zip(("NETWORK", "PROTECT", "ACCESS"), SETUP_SKILLS, strict=True):
        skill = skill_path.read_text(encoding="utf-8")
        assert f"UNIFI_{product}_TOOL_PERMISSION_MODE=confirm" in skill
        assert f"UNIFI_POLICY_{product}_<CATEGORY>_<ACTION>" in skill
        assert "Remove every existing category-specific" in skill
        for action in ("CREATE", "UPDATE", "DELETE"):
            assert f"UNIFI_POLICY_{product}_{action}=false" in skill


def test_command_provider_assignments_are_shell_quoted() -> None:
    for product, skill_path in zip(("NETWORK", "PROTECT", "ACCESS"), SETUP_SKILLS, strict=True):
        skill = skill_path.read_text(encoding="utf-8")
        assert f"'UNIFI_{product}_PASSWORD_COMMAND=<absolute-argv>'" in skill
        assert f"'UNIFI_{product}_PASSWORD_FILE=<absolute-path>'" in skill
        assert f"'UNIFI_{product}_API_KEY_FILE=<absolute-path>'" in skill

    access_skill = SETUP_SKILLS[2].read_text(encoding="utf-8")
    assert "'UNIFI_ACCESS_API_KEY_COMMAND=<absolute-argv>'" in access_skill

    guide = GUIDE.read_text(encoding="utf-8")
    assert "--env 'UNIFI_NETWORK_PASSWORD_FILE=/absolute/path/to/password-file'" in guide


def test_opencode_scope_and_network_auth_are_accurate() -> None:
    guide = GUIDE.read_text(encoding="utf-8")

    assert "There is no `--global` switch" in guide
    assert "user-level configuration" in guide
    assert "API-key provider for limited inventory" in guide
    for action in ("CREATE", "UPDATE", "DELETE"):
        assert f"--env UNIFI_POLICY_NETWORK_{action}=false" in guide
    assert "--env UNIFI_NETWORK_TOOL_PERMISSION_MODE=confirm" in guide
    assert "For Network API-key-only setup" in guide
    assert "a mutation request is denied by policy" in guide


def test_setup_skills_describe_auth_by_tool_family() -> None:
    network_skill = SETUP_SKILLS[0].read_text(encoding="utf-8")
    access_skill = SETUP_SKILLS[2].read_text(encoding="utf-8")

    assert "legacy and session-backed tool families" in network_skill
    assert "Both for the widest tool coverage" in network_skill
    assert "session tools and full coverage" not in network_skill

    assert "Access Developer API visitor family" in access_skill
    assert "including visitor reads,\n  creation, and deletion" in access_skill
    assert "local-only management tool" in access_skill
    assert "read-oriented Access API calls" not in access_skill


def test_protect_setup_refers_to_password_provider_not_raw_password() -> None:
    skill = SETUP_SKILLS[1].read_text(encoding="utf-8")

    assert "username and password provider" in skill
    assert "After collecting username and password," not in skill
