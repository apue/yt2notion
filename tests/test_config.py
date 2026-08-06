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
    assert config.storage["backend"] == "obsidian"


def test_missing_config_raises():
    with pytest.raises(ConfigError, match="not found"):
        load_config("/nonexistent/config.yaml")


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


def test_deep_merge_preserves_nested(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "storage:\n  backend: obsidian\n  obsidian:\n    summaries_dir: custom/notes\n"
    )
    config = load_config(str(cfg_file))
    assert config.storage["obsidian"]["summaries_dir"] == "custom/notes"
    assert config.storage["obsidian"]["vault_path"] == ""


def test_codex_cli_model_backend_is_valid(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("model:\n  backend: codex_cli\nstorage:\n  backend: obsidian\n")
    config = load_config(str(cfg_file))
    assert config.model["backend"] == "codex_cli"


def test_openai_alias_model_backend_is_rejected(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("model:\n  backend: openai_api\n")
    with pytest.raises(ConfigError, match="Invalid model backend"):
        load_config(str(cfg_file))


def test_asr_restart_defaults_present(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("{}")
    config = load_config(str(cfg_file))
    asr = config.extract["asr"]
    assert asr["healthcheck_path"] == "/health"
    assert asr["restart_before_transcribe"] is False
    assert asr["restart_on_unhealthy"] is False
    assert asr["restart_command"] == ""


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


def test_remote_only_config_loads(tmp_path):
    cfg_file = tmp_path / "c.yaml"
    _write_yaml(cfg_file, _base_config())
    config = load_config(str(cfg_file))
    assert config.extract["asr"]["fallback_backend"] is None
    assert config.extract["asr"]["groq"]["model"] == "whisper-large-v3-turbo"


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


def test_groq_env_var_satisfies_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "sk-test")
    cfg_file = tmp_path / "c.yaml"
    data = _base_config()
    data["extract"]["asr"] = {"backend": "groq"}
    _write_yaml(cfg_file, data)
    config = load_config(str(cfg_file))
    assert config.extract["asr"]["backend"] == "groq"


def test_groq_primary_with_remote_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    cfg_file = tmp_path / "c.yaml"
    data = _base_config()
    data["extract"]["asr"] = {
        "backend": "groq",
        "fallback_backend": "remote",
        "endpoint": "http://asr",
        "groq": {"api_key": "sk-x"},
    }
    _write_yaml(cfg_file, data)
    config = load_config(str(cfg_file))
    assert config.extract["asr"]["backend"] == "groq"
    assert config.extract["asr"]["fallback_backend"] == "remote"
    assert config.extract["asr"]["groq"]["api_key"] == "sk-x"
