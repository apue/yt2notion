"""Configuration loading and validation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigError(Exception):
    """Raised when configuration is invalid or missing."""


VALID_MODEL_BACKENDS = {"claude_code", "anthropic_api", "codex_cli", "openai_api"}
VALID_STORAGE_BACKENDS = {"notion", "obsidian", "markdown"}
VALID_ASR_BACKENDS: set[str] = {"remote", "groq"}

DEFAULTS: dict = {
    "model": {
        "backend": "claude_code",
        "summarize_model": "sonnet",
        "translate_model": "opus",
        "review_model": "haiku",
        "reasoning_effort": "low",
    },
    "storage": {
        "backend": "notion",
        "notion": {"token": "", "database_id": "", "directory_rules": []},
        "obsidian": {
            "vault_path": "",
            "summaries_dir": "yt2notion/summaries",
            "transcripts_dir": "yt2notion/transcripts",
        },
    },
    "extract": {
        "subtitle_priority": ["zh-Hans", "zh-Hant", "en"],
        "auto_subtitle_fallback": True,
        "auto_subtitle_lang": "en",
        "cookies_from": "chrome",
        "asr": {
            "backend": "remote",
            "endpoint": "",
            "healthcheck_path": "/health",
            "healthcheck_timeout_seconds": 3.0,
            "restart_before_transcribe": False,
            "restart_on_unhealthy": False,
            "restart_command": "",
            "restart_readiness_timeout_seconds": 90.0,
            "restart_readiness_interval_seconds": 3.0,
            "restart_grace_seconds": 5.0,
            "fallback_backend": None,
            "groq": {
                "api_key": "",
                "model": "whisper-large-v3-turbo",
                "max_upload_bytes": 24_000_000,
                "endpoint": "https://api.groq.com/openai/v1/audio/transcriptions",
                "timeout_seconds": 600,
            },
        },
    },
    "credit": {
        "always_include": True,
        "format": "来源：{channel} 「{title}」\n链接：{url}",
    },
    "output": {
        "mode": "summary",
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

    output_mode = merged.get("output", {}).get("mode", "summary")
    if output_mode not in {"summary", "full"}:
        raise ConfigError("output.mode must be either 'summary' or 'full'")

    # Validate obsidian vault_path when backend is obsidian
    if storage_backend == "obsidian":
        vault_path = merged.get("storage", {}).get("obsidian", {}).get("vault_path", "")
        if not vault_path:
            raise ConfigError("storage.obsidian.vault_path is required when backend is 'obsidian'")
        vault = Path(vault_path)
        if not vault.is_dir():
            raise ConfigError(f"Obsidian vault path does not exist: {vault_path}")

    # Validate ASR backend(s)
    asr_cfg = merged.get("extract", {}).get("asr", {})
    primary = asr_cfg.get("backend", "remote")
    if primary not in VALID_ASR_BACKENDS:
        raise ConfigError(
            f"Invalid ASR backend: {primary!r}. Must be one of: {sorted(VALID_ASR_BACKENDS)}"
        )
    fallback = asr_cfg.get("fallback_backend")
    if fallback is not None:
        if fallback not in VALID_ASR_BACKENDS:
            raise ConfigError(
                f"Invalid ASR fallback_backend: {fallback!r}. "
                f"Must be one of: {sorted(VALID_ASR_BACKENDS)}"
            )
        if fallback == primary:
            raise ConfigError("extract.asr.fallback_backend must differ from extract.asr.backend")
    if "groq" in {primary, fallback}:
        api_key = asr_cfg.get("groq", {}).get("api_key", "") or os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            raise ConfigError(
                "extract.asr.groq.api_key is required when groq is used "
                "(or set GROQ_API_KEY env var)"
            )

    return AppConfig(
        model=merged["model"],
        storage=merged["storage"],
        extract=merged["extract"],
        credit=merged["credit"],
        output=merged["output"],
        workspace=merged.get("workspace", DEFAULTS["workspace"]),
    )
