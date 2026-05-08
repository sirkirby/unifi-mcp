#!/usr/bin/env python3
"""Generate a firewall policy from a template.

Reads templates from references/policy-templates.yaml, substitutes
parameters, outputs the MCP tool call payload. Does NOT execute --
human confirms.

Usage:
    python apply-template.py --template iot-isolation --param iot_network=IoT --param private_network=Main
    python apply-template.py --list  # list available templates
"""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Template file lives in references/ relative to scripts/.
_scripts_dir = Path(__file__).resolve().parent
_references_dir = _scripts_dir.parent / "references"
DEFAULT_TEMPLATES_PATH = _references_dir / "policy-templates.yaml"


# -- Argument parsing ----------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate firewall policy from a template.")
    parser.add_argument(
        "--template",
        default=None,
        help="Template name to apply (e.g., iot-isolation)",
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        dest="params",
        help="Parameter KEY=VALUE (repeatable)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_templates",
        help="List available templates and exit",
    )
    parser.add_argument(
        "--templates-file",
        default=None,
        help="Path to policy-templates.yaml (default: references/policy-templates.yaml)",
    )
    return parser.parse_args(argv)


# -- Template loading ----------------------------------------------------------


def _load_yaml_simple(path: Path) -> dict:
    """Load YAML using PyYAML if available."""
    try:
        import yaml

        return yaml.safe_load(path.read_text()) or {}
    except ImportError:
        raise ImportError(
            "PyYAML is required for template loading. Install with: pip install pyyaml"
        )


def load_templates(path: Path) -> list[dict]:
    """Load and validate templates from a YAML file.

    Returns a list of template configs, each with at least 'name', 'params', and 'payload' or 'rules'.
    """
    if not path.exists():
        return []
    data = _load_yaml_simple(path)
    templates = data.get("templates", [])
    if not isinstance(templates, list):
        return []
    return templates


def get_template_by_name(templates: list[dict], name: str) -> dict | None:
    """Find a template by name in the templates list."""
    for t in templates:
        if t.get("name") == name:
            return t
    return None


def get_template_names(templates: list[dict]) -> list[str]:
    """Return sorted list of template names."""
    return sorted(t.get("name", "") for t in templates if t.get("name"))


# -- Template listing ----------------------------------------------------------


def list_templates(templates: list[dict]) -> list[dict[str, Any]]:
    """Return a summary list of available templates."""
    result = []
    for config in sorted(templates, key=lambda t: t.get("name", "")):
        required_params = [
            p["name"] for p in config.get("params", []) if p.get("required", False)
        ]
        result.append({
            "name": config.get("name", ""),
            "description": config.get("description", ""),
            "required_params": required_params,
        })
    return result


# -- Parameter parsing ---------------------------------------------------------


def parse_params(raw_params: list[str]) -> dict[str, str]:
    """Parse KEY=VALUE parameter strings into a dict."""
    result: dict[str, str] = {}
    for item in raw_params:
        if "=" not in item:
            print(json.dumps({
                "success": False,
                "error": f"Invalid parameter format: '{item}'. Expected KEY=VALUE.",
            }))
            sys.exit(1)
        key, value = item.split("=", 1)
        result[key.strip()] = value.strip()
    return result


# -- Template application ------------------------------------------------------


def _substitute(value: Any, params: dict[str, str]) -> Any:
    """Recursively substitute {param} placeholders in a value."""
    if isinstance(value, str):
        def replacer(match):
            param_name = match.group(1)
            return params.get(param_name, match.group(0))

        return re.sub(r"\{(\w+)\}", replacer, value)
    elif isinstance(value, dict):
        return {k: _substitute(v, params) for k, v in value.items()}
    elif isinstance(value, list):
        return [_substitute(item, params) for item in value]
    return value


def validate_params(
    template_config: dict,
    params: dict[str, str],
) -> list[str]:
    """Check that all required params are provided. Return list of missing param names."""
    required = [
        p["name"] for p in template_config.get("params", []) if p.get("required", False)
    ]
    return [p for p in required if p not in params]


def get_required_params(template_config: dict) -> list[str]:
    """Extract the list of required parameter names from a template config."""
    return [
        p["name"] for p in template_config.get("params", []) if p.get("required", False)
    ]


def apply_template(
    template_name: str,
    template_config: dict,
    params: dict[str, str],
) -> dict[str, Any]:
    """Substitute parameters into a template and return the tool call payload.

    For single-step templates (with 'payload'), returns:
        {"tool": "<tool_name>", "arguments": {...}, "preview": true}

    For multi-step templates (with 'rules'), returns:
        {"steps": [{"tool": ..., "arguments": ..., "preview": true}, ...]}
    """
    # Multi-step templates have 'rules' instead of 'payload'.
    if "rules" in template_config:
        steps = []
        for rule in template_config["rules"]:
            payload = rule.get("payload", {})
            resolved = _substitute(payload, params)
            tool = rule.get("tool", template_config.get("tool", "unifi_create_firewall_policy"))
            steps.append({
                "step": rule.get("step"),
                "description": _substitute(rule.get("description", ""), params),
                "tool": tool,
                "arguments": resolved,
                "preview": True,
            })
        return {"steps": steps}

    # Single-step template.
    payload = template_config.get("payload", {})
    resolved = _substitute(payload, params)
    tool = template_config.get("tool", "unifi_create_firewall_policy")

    return {
        "tool": tool,
        "arguments": resolved,
        "preview": True,
    }


# -- Entry point ---------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    templates_path = Path(args.templates_file) if args.templates_file else DEFAULT_TEMPLATES_PATH
    templates = load_templates(templates_path)

    if not templates:
        print(json.dumps({
            "success": False,
            "error": f"No templates found in {templates_path}.",
        }))
        sys.exit(1)

    available_names = get_template_names(templates)

    # --list mode.
    if args.list_templates:
        summaries = list_templates(templates)
        print(json.dumps({"success": True, "templates": summaries}, indent=2))
        return

    # --template mode requires a template name.
    if not args.template:
        print(json.dumps({
            "success": False,
            "error": "Specify --template NAME or --list. Available: " + ", ".join(available_names),
        }))
        sys.exit(1)

    template_config = get_template_by_name(templates, args.template)
    if template_config is None:
        print(json.dumps({
            "success": False,
            "error": f"Unknown template: '{args.template}'. Available: " + ", ".join(available_names),
        }))
        sys.exit(1)

    params = parse_params(args.params)

    # Validate required params.
    missing = validate_params(template_config, params)
    if missing:
        print(json.dumps({
            "success": False,
            "error": f"Missing required parameter(s): {', '.join(missing)}",
            "required_params": get_required_params(template_config),
            "provided_params": list(params.keys()),
        }))
        sys.exit(1)

    # Apply template.
    result = apply_template(args.template, template_config, params)

    print(json.dumps({"success": True, **result}, indent=2))


if __name__ == "__main__":
    main()
