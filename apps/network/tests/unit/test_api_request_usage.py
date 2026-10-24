"""Regression tests to ensure ApiRequest is used correctly across the codebase.

The aiounifi library's ApiRequest dataclass only accepts 'data=' for request bodies,
not 'json='. This test prevents reintroduction of that bug.
"""

import ast
from pathlib import Path

import pytest
from aiounifi.models.api import ApiRequest


class TestApiRequestSignature:
    """Test that ApiRequest is used with correct parameters."""

    def test_api_request_does_not_accept_json_parameter(self):
        """Verify ApiRequest raises TypeError when 'json=' is used.

        This documents the expected behavior and will catch if aiounifi
        ever changes to support 'json=' (unlikely but good to track).
        """
        with pytest.raises(TypeError, match="unexpected keyword argument 'json'"):
            ApiRequest(method="post", path="/test", json={"key": "value"})

    def test_api_request_accepts_data_parameter(self):
        """Verify ApiRequest correctly accepts 'data=' parameter."""
        request = ApiRequest(method="post", path="/test", data={"key": "value"})
        assert request.data == {"key": "value"}
        assert request.method == "post"
        assert request.path == "/test"


class TestManagerFilesUseCorrectApiRequestSyntax:
    """Scan manager files to ensure ApiRequest is called with 'data=', not 'json='."""

    @pytest.fixture
    def manager_files(self) -> list[Path]:
        """Get all manager Python files."""
        managers_dir = (
            Path(__file__).parent.parent.parent.parent.parent
            / "packages"
            / "unifi-core"
            / "src"
            / "unifi_core"
            / "network"
            / "managers"
        )
        return list(managers_dir.glob("*.py"))

    def test_no_json_parameter_in_api_request_calls(self, manager_files: list[Path]):
        """Ensure no manager uses 'json=' when calling ApiRequest.

        This is a static analysis test that parses the AST of each manager file
        to find ApiRequest calls and verify they don't use 'json=' parameter.
        """
        violations = []

        for file_path in manager_files:
            if file_path.name == "__init__.py":
                continue

            source = file_path.read_text()
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                # Look for Call nodes where func is ApiRequest
                if isinstance(node, ast.Call):
                    func_name = None
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        func_name = node.func.attr

                    if func_name == "ApiRequest":
                        # Check keyword arguments for 'json'
                        for keyword in node.keywords:
                            if keyword.arg == "json":
                                violations.append(
                                    f"{file_path.name}:{node.lineno} - "
                                    f"ApiRequest called with 'json=' (should be 'data=')"
                                )

        assert not violations, (
            "Found ApiRequest calls using 'json=' parameter. "
            "The aiounifi ApiRequest only accepts 'data=' for request bodies.\n"
            "Violations:\n" + "\n".join(f"  - {v}" for v in violations)
        )

    def test_manager_files_exist(self, manager_files: list[Path]):
        """Sanity check that we're actually scanning manager files."""
        # We should have at least the core managers
        file_names = {f.name for f in manager_files}
        assert "client_manager.py" in file_names
        assert "device_manager.py" in file_names
        assert "network_manager.py" in file_names
