"""Tests for the shared config module."""

import logging

import pytest
from unifi_core.config import load_yaml_config, setup_logging


class TestSetupLogging:
    """Tests for setup_logging."""

    def test_returns_named_logger(self):
        logger = setup_logging("test-app")
        assert logger.name == "test-app"
        assert isinstance(logger, logging.Logger)

    def test_sets_root_level(self):
        setup_logging("test-app", level="DEBUG")
        assert logging.getLogger().level == logging.DEBUG
        # Reset
        setup_logging("test-app", level="INFO")

    def test_defaults_to_info(self):
        setup_logging("test-app")
        assert logging.getLogger().level == logging.INFO

    def test_invalid_level_falls_back_to_info(self):
        setup_logging("test-app", level="NOTAREAL")
        assert logging.getLogger().level == logging.INFO


class TestLoadYamlConfig:
    """Tests for load_yaml_config."""

    def test_loads_valid_yaml(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("server:\n  port: 3000\n  host: localhost\n")

        cfg = load_yaml_config(config_file)

        assert cfg.server.port == 3000
        assert cfg.server.host == "localhost"

    def test_raises_on_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_yaml_config(tmp_path / "nonexistent.yaml")

    def test_accepts_string_path(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("key: value\n")

        cfg = load_yaml_config(str(config_file))
        assert cfg.key == "value"
