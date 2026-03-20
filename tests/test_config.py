"""Tests for configuration loading and validation."""

from __future__ import annotations

import pytest

from yt2notion.config import AppConfig, ConfigError, load_config


def test_load_valid_config(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("model:\n  backend: claude_code\nstorage:\n  backend: notion\n")
    config = load_config(str(cfg_file))
    assert isinstance(config, AppConfig)
    assert config.model["backend"] == "claude_code"
    assert config.storage["backend"] == "notion"


def test_missing_config_raises():
    with pytest.raises(ConfigError, match="not found"):
        load_config("/nonexistent/config.yaml")


def test_default_values(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("{}")  # empty config
    config = load_config(str(cfg_file))
    assert config.model["backend"] == "claude_code"
    assert config.model["summarize_model"] == "sonnet"
    assert config.model["translate_model"] == "opus"
    assert config.storage["backend"] == "notion"
    assert config.extract["subtitle_priority"] == ["zh-Hans", "zh-Hant", "en"]
    assert config.output["chunk_duration_seconds"] == 120
    assert config.credit["always_include"] is True


def test_invalid_model_backend(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("model:\n  backend: invalid_backend\n")
    with pytest.raises(ConfigError, match="Invalid model backend"):
        load_config(str(cfg_file))


def test_invalid_storage_backend(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("storage:\n  backend: invalid_backend\n")
    with pytest.raises(ConfigError, match="Invalid storage backend"):
        load_config(str(cfg_file))


def test_deep_merge_preserves_nested(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("storage:\n  backend: notion\n  notion:\n    token: my_token\n")
    config = load_config(str(cfg_file))
    assert config.storage["notion"]["token"] == "my_token"
    # Default database_id should still be present
    assert config.storage["notion"]["database_id"] == ""
