"""Configuration loading and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigError(Exception):
    """Raised when configuration is invalid or missing."""


VALID_MODEL_BACKENDS = {"claude_code", "anthropic_api", "openai_api"}
VALID_STORAGE_BACKENDS = {"notion", "obsidian", "markdown"}

DEFAULTS: dict = {
    "model": {
        "backend": "claude_code",
        "summarize_model": "sonnet",
        "translate_model": "opus",
        "review_model": "haiku",
    },
    "storage": {
        "backend": "notion",
        "notion": {"token": "", "database_id": "", "directory_rules": []},
    },
    "extract": {
        "subtitle_priority": ["zh-Hans", "zh-Hant", "en"],
        "auto_subtitle_fallback": True,
        "auto_subtitle_lang": "en",
        "cookies_from": "chrome",
        "asr": {
            "backend": "remote",
            "endpoint": "",
        },
    },
    "credit": {
        "always_include": True,
        "format": "来源：{channel} 「{title}」\n链接：{url}",
    },
    "output": {
        "chunk_duration_seconds": 120,
        "target_language": "zh-CN",
        "long_content_threshold_seconds": 1800,
        "max_segment_seconds": 900,
    },
    "workspace": {
        "base_dir": "./workspace",
    },
}


@dataclass
class AppConfig:
    """Strongly-typed application configuration."""

    model: dict = field(default_factory=lambda: dict(DEFAULTS["model"]))
    storage: dict = field(default_factory=lambda: dict(DEFAULTS["storage"]))
    extract: dict = field(default_factory=lambda: dict(DEFAULTS["extract"]))
    credit: dict = field(default_factory=lambda: dict(DEFAULTS["credit"]))
    output: dict = field(default_factory=lambda: dict(DEFAULTS["output"]))
    workspace: dict = field(default_factory=lambda: dict(DEFAULTS["workspace"]))


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, recursing into nested dicts."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str) -> AppConfig:
    """Load and validate configuration from a YAML file.

    Raises ConfigError if the file is missing or contains invalid values.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    merged = _deep_merge(DEFAULTS, raw)

    # Validate backends
    model_backend = merged.get("model", {}).get("backend", "")
    if model_backend not in VALID_MODEL_BACKENDS:
        raise ConfigError(
            f"Invalid model backend: {model_backend!r}. "
            f"Must be one of: {', '.join(sorted(VALID_MODEL_BACKENDS))}"
        )

    storage_backend = merged.get("storage", {}).get("backend", "")
    if storage_backend not in VALID_STORAGE_BACKENDS:
        raise ConfigError(
            f"Invalid storage backend: {storage_backend!r}. "
            f"Must be one of: {', '.join(sorted(VALID_STORAGE_BACKENDS))}"
        )

    return AppConfig(
        model=merged["model"],
        storage=merged["storage"],
        extract=merged["extract"],
        credit=merged["credit"],
        output=merged["output"],
        workspace=merged.get("workspace", DEFAULTS["workspace"]),
    )
