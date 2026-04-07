"""Model backend factory."""

from __future__ import annotations

from typing import Any


def create_summarizer(config: dict) -> Any:
    """Create a Summarizer instance based on config.

    Returns an object conforming to the Summarizer Protocol.
    """
    model_config = config.get("model", {})
    backend = model_config.get("backend", "claude_code")
    summarize_model = model_config.get("summarize_model", "sonnet")
    translate_model = model_config.get("translate_model", "opus")
    reasoning_effort = model_config.get("reasoning_effort", "low")
    runtime_cfg = model_config.get("_runtime", {})
    codex_workdir = runtime_cfg.get("codex_workdir")

    if backend == "claude_code":
        from yt2notion.models.claude_code import ClaudeCodeModel

        return ClaudeCodeModel(
            summarize_model=summarize_model,
            translate_model=translate_model,
        )
    elif backend in {"codex_cli", "openai_api"}:
        from yt2notion.models.codex_cli import CodexCLIModel

        return CodexCLIModel(
            summarize_model=summarize_model or "gpt-5.2",
            translate_model=translate_model or "gpt-5.2",
            reasoning_effort=reasoning_effort,
            workdir=codex_workdir,
        )
    elif backend == "anthropic_api":
        from yt2notion.models.anthropic_api import AnthropicAPIModel

        api_key = model_config.get("api_key", "")
        if not api_key:
            import os

            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError(
                "Anthropic API key required. "
                "Set model.api_key in config or ANTHROPIC_API_KEY env var."
            )
        return AnthropicAPIModel(
            api_key=api_key,
            summarize_model=summarize_model,
            translate_model=translate_model,
        )
    else:
        raise ValueError(f"Unknown model backend: {backend!r}")
