"""Lightweight LLM caller for one-shot text-in/text-out tasks.

Used by utility modules (review, topic_segment) that need
a single LLM call without the full Summarizer protocol machinery.
"""

from __future__ import annotations

import json
import subprocess
from typing import Protocol


class LLMCaller(Protocol):
    """Protocol for one-shot LLM calls."""

    def call(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 4000) -> str:
        """Send system + user prompt, return raw text response."""
        ...


class ClaudeCodeCaller:
    """LLM caller using the claude CLI (claude -p)."""

    def __init__(self, model: str = "haiku") -> None:
        self.model = model

    def call(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 4000) -> str:
        prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
        cmd = [
            "claude",
            "-p",
            "--model",
            self.model,
            "--max-turns",
            "1",
            "--output-format",
            "json",
        ]

        from yt2notion.retry import RetryExhaustedError, retry

        class _EmptyOutputError(Exception):
            pass

        def _run() -> str:
            try:
                result = subprocess.run(
                    cmd, input=prompt, capture_output=True, text=True, check=True, timeout=120
                )
            except FileNotFoundError:
                raise RuntimeError("'claude' CLI not found on PATH") from None
            raw = result.stdout
            if not raw or not raw.strip():
                raise _EmptyOutputError("claude returned empty output")
            try:
                output = json.loads(raw)
                return output.get("result", raw)
            except json.JSONDecodeError:
                return raw

        try:
            return retry(
                _run,
                max_retries=3,
                base_delay=5.0,
                retryable=(
                    subprocess.CalledProcessError,
                    subprocess.TimeoutExpired,
                    _EmptyOutputError,
                ),
                label=f"claude -p {self.model}",
            )
        except RetryExhaustedError:
            raise


def create_llm_caller(config: dict, *, model_key: str = "review_model") -> LLMCaller:
    """Create an LLMCaller from config.

    Args:
        config: Raw config dict (top-level, containing "model" key).
        model_key: Which model field to use (default: "review_model").
    """
    model_cfg = config.get("model", {})
    backend = model_cfg.get("backend", "claude_code")
    model = model_cfg.get(model_key, "haiku")
    reasoning_effort = model_cfg.get("reasoning_effort", "low")
    runtime_cfg = model_cfg.get("_runtime", {})
    codex_workdir = runtime_cfg.get("codex_workdir")
    codex_profile = runtime_cfg.get("codex_profile")

    if backend == "claude_code":
        return ClaudeCodeCaller(model=model)
    if backend in {"codex_cli", "openai_api"}:
        from yt2notion.models.codex_cli import CodexCLICaller

        return CodexCLICaller(
            model=model or "gpt-5.4",
            reasoning_effort=reasoning_effort,
            profile=codex_profile,
            workdir=codex_workdir,
        )

    raise ValueError(f"Unknown LLM backend: {backend!r}")
