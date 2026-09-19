from __future__ import annotations

from pathlib import Path

GUIDE = Path("docs/agent-install.md")
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
    assert "Devin Desktop" in guide
    assert "devin mcp add unifi-network" in guide
    assert "OpenCode npm plugin is worth a small packaging prototype" in guide
    assert "### Gemini CLI" not in guide
    assert "### Windsurf" not in guide


def test_agent_guardrails_preserve_secrets_and_confirmation_mode() -> None:
    guide = GUIDE.read_text(encoding="utf-8")

    assert "Do not ask the user to paste a password or API key into the chat" in guide
    assert "Keep the permission mode at its default, `confirm`" in guide
    assert "wait for confirmation" in guide
    assert "No secret was printed" in guide


def test_setup_skills_handle_standalone_skills_installs() -> None:
    for skill_path in SETUP_SKILLS:
        skill = skill_path.read_text(encoding="utf-8")
        assert "standalone `npx skills`" in skill
        assert "docs/agent-install.md" in skill
        assert "does not install or register the MCP server" in skill
