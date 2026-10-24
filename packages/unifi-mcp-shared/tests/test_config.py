"""Tests for the shared config module."""

import logging

import pytest
from unifi_core.config import load_yaml_config, setup_logging


class TestSetupLogging:
    """Tests for setup_logging."""

    @pytest.mark.parametrize(
        ("level_arg", "expected_level"),
        [
            ("DEBUG", logging.DEBUG),
            (None, logging.INFO),
            ("NOTAREAL", logging.INFO),
        ],
    )
    def test_setup_logging_returns_named_logger_and_sets_level(self, level_arg, expected_level):
        logger = setup_logging("test-app") if level_arg is None else setup_logging("test-app", level=level_arg)
        assert logger.name == "test-app"
        assert isinstance(logger, logging.Logger)
        assert logging.getLogger().level == expected_level
        setup_logging("test-app", level="INFO")


class TestLoadYamlConfig:
    """Tests for load_yaml_config."""

    def test_raises_on_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_yaml_config(tmp_path / "nonexistent.yaml")

    def test_accepts_string_path(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("key: value\n")

        cfg = load_yaml_config(str(config_file))
        assert cfg.key == "value"
