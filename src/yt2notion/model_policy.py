"""Backend-specific defaults for text-generation providers."""

from __future__ import annotations

from copy import deepcopy

DEFAULT_MODEL_BACKEND = "codex_cli"
MODEL_BACKEND_DEFAULTS: dict[str, dict[str, object]] = {
    "codex_cli": {
        "translate_model": "gpt-5.4",
        "review_model": "gpt-5.4",
    },
    "claude_code": {
        "translate_model": "opus",
        "review_model": "haiku",
    },
    "anthropic_api": {
        "translate_model": "opus",
        "review_model": "haiku",
    },
}


def default_model_config(backend: str = DEFAULT_MODEL_BACKEND) -> dict:
    """Return an independent model configuration for one backend."""
    return {
        "backend": backend,
        **deepcopy(MODEL_BACKEND_DEFAULTS.get(backend, {})),
        "reasoning_effort": "low",
        "timeout_seconds": 240,
        "max_attempts": 1,
    }


def resolve_model_config(config: dict) -> dict:
    """Overlay caller-supplied model settings on backend-specific defaults."""
    overrides = config.get("model", {}) or {}
    backend = overrides.get("backend", DEFAULT_MODEL_BACKEND)
    return {**default_model_config(backend), **overrides}
