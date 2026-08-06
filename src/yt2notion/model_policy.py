"""Backend-specific defaults for text-generation providers."""

from __future__ import annotations

from typing import NotRequired, TypedDict, cast


class ModelConfig(TypedDict):
    """Normalized configuration shared by every LLM adapter."""

    backend: str
    translate_model: str
    review_model: str
    reasoning_effort: str
    timeout_seconds: float
    max_attempts: int
    api_key: NotRequired[str]


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


def default_model_config(backend: str = DEFAULT_MODEL_BACKEND) -> ModelConfig:
    """Return an independent model configuration for one backend."""
    return cast(
        "ModelConfig",
        {
            "backend": backend,
            **MODEL_BACKEND_DEFAULTS.get(backend, {}),
            "reasoning_effort": "low",
            "timeout_seconds": 240,
            "max_attempts": 1,
        },
    )


def resolve_model_config(config: dict[str, object]) -> ModelConfig:
    """Overlay caller-supplied model settings on backend-specific defaults."""
    overrides = config.get("model", {}) or {}
    if not isinstance(overrides, dict):
        overrides = {}
    backend = overrides.get("backend", DEFAULT_MODEL_BACKEND)
    return cast("ModelConfig", {**default_model_config(str(backend)), **overrides})
