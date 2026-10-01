"""Tests for configuration loading and validation."""

from __future__ import annotations

import pytest

from yt2notion.config import AppConfig, ConfigError, load_config


def test_load_valid_config(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("model:\n  backend: claude_code\nstorage:\n  backend: obsidian\n")
    config = load_config(str(cfg_file))
    assert isinstance(config, AppConfig)
    assert config.model["backend"] == "claude_code"
    assert config.model["review_model"] == "haiku"
    assert config.model["translate_model"] == "opus"
    assert config.storage["backend"] == "obsidian"


def test_default_values(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("{}")  # empty config
    config = load_config(str(cfg_file))
    assert config.model["backend"] == "codex_cli"
    assert "summarize_model" not in config.model
    assert config.model["translate_model"] == "gpt-5.4"
    assert config.model["review_model"] == "gpt-5.4"
    assert config.model["timeout_seconds"] == 240
    assert config.model["reasoning_effort"] == "low"
    assert config.storage["backend"] == "obsidian"
    assert config.extract["subtitle_priority"] == ["zh-Hans", "zh-Hant", "en"]
    assert config.output["mode"] == "summary"
    assert config.output["chunk_duration_seconds"] == 120
    assert config.credit["always_include"] is True


def test_legacy_mapping_exposes_only_existing_helper_sections() -> None:
    config = AppConfig()

    mapping = config.to_legacy_mapping()

    assert mapping == {
        "extract": config.extract,
        "model": config.model,
        "storage": config.storage,
        "credit": config.credit,
        "output": config.output,
    }
    assert "workspace" not in mapping


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


def test_invalid_output_mode(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("output:\n  mode: transcript_only\n")
    with pytest.raises(ConfigError, match="output.mode"):
        load_config(str(cfg_file))


def test_unknown_media_source_backend_raises_config_error(tmp_path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("extract:\n  media_source:\n    backend: nope\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="Invalid media-source backend"):
        load_config(str(cfg_file))


def test_invalid_media_source_config_shape_raises_config_error(tmp_path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("extract:\n  media_source: yt_dlp\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="extract.media_source must be a mapping"):
        load_config(str(cfg_file))


def test_deep_merge_preserves_nested(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "storage:\n  backend: obsidian\n  obsidian:\n    summaries_dir: custom/notes\n"
    )
    config = load_config(str(cfg_file))
    assert config.storage["obsidian"]["summaries_dir"] == "custom/notes"
    assert config.storage["obsidian"]["vault_path"] == ""


def _write_yaml(path, data: dict) -> None:
    import yaml as _yaml

    path.write_text(_yaml.safe_dump(data))


def _base_config(**overrides) -> dict:
    base = {
        "model": {"backend": "claude_code"},
        "storage": {"backend": "obsidian", "obsidian": {"vault_path": ""}},
        "extract": {"asr": {"backend": "remote", "endpoint": "http://asr"}},
        "output": {"mode": "summary"},
    }
    for k, v in overrides.items():
        base[k] = v
    return base


def test_invalid_asr_backend_rejected(tmp_path):
    cfg_file = tmp_path / "c.yaml"
    data = _base_config()
    data["extract"]["asr"]["backend"] = "bogus"
    _write_yaml(cfg_file, data)
    with pytest.raises(ConfigError, match="Invalid ASR backend"):
        load_config(str(cfg_file))


def test_fallback_equals_primary_rejected(tmp_path):
    cfg_file = tmp_path / "c.yaml"
    data = _base_config()
    data["extract"]["asr"]["fallback_backend"] = "remote"
    _write_yaml(cfg_file, data)
    with pytest.raises(ConfigError, match="differ"):
        load_config(str(cfg_file))


def test_invalid_fallback_backend_rejected(tmp_path):
    cfg_file = tmp_path / "c.yaml"
    data = _base_config()
    data["extract"]["asr"] = {
        "backend": "groq",
        "fallback_backend": "nope",
        "groq": {"api_key": "sk-x"},
    }
    _write_yaml(cfg_file, data)
    with pytest.raises(ConfigError, match="Invalid ASR fallback_backend"):
        load_config(str(cfg_file))


def test_groq_requires_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    cfg_file = tmp_path / "c.yaml"
    data = _base_config()
    data["extract"]["asr"] = {"backend": "groq"}
    _write_yaml(cfg_file, data)
    with pytest.raises(ConfigError, match="api_key"):
        load_config(str(cfg_file))
