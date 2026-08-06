"""Text-in/text-out LLM provider adapters."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Protocol

from yt2notion.model_policy import MODEL_BACKEND_DEFAULTS, resolve_model_config
from yt2notion.retry import retry


class LLMCaller(Protocol):
    """Perform one provider call and return raw text."""

    def call(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 4000) -> str: ...


class ClaudeCodeError(Exception):
    """Raised when the Claude CLI cannot complete a call."""


class LLMConfigError(ValueError):
    """Raised when an LLM adapter cannot be selected or configured."""


class ClaudeCodeCaller:
    """One-shot LLM caller using `claude -p`."""

    def __init__(
        self,
        model: str = "haiku",
        *,
        timeout_seconds: float = 120,
        max_attempts: int = 1,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts

    def call(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 4000) -> str:
        del max_tokens
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

        class _EmptyOutputError(Exception):
            pass

        def _run() -> str:
            try:
                result = subprocess.run(
                    cmd,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=self.timeout_seconds,
                )
            except FileNotFoundError as exc:
                raise ClaudeCodeError("'claude' CLI not found on PATH") from exc
            except subprocess.CalledProcessError as exc:
                detail = (exc.stdout or exc.stderr or str(exc)).strip()
                try:
                    payload = json.loads(detail)
                    detail = payload.get("result", detail)
                except json.JSONDecodeError:
                    pass
                raise ClaudeCodeError(f"claude CLI failed: {detail}") from exc
            if not result.stdout.strip():
                raise _EmptyOutputError("claude returned empty output")
            try:
                payload = json.loads(result.stdout)
                return payload.get("result", result.stdout)
            except json.JSONDecodeError:
                return result.stdout

        return retry(
            _run,
            max_retries=self.max_attempts,
            base_delay=5.0,
            retryable=(
                subprocess.TimeoutExpired,
                _EmptyOutputError,
            ),
            label=f"claude -p {self.model}",
        )


def create_llm_caller(config: dict, *, model_key: str = "review_model") -> LLMCaller:
    """Create an LLM provider adapter for the requested model role."""
    model_config = resolve_model_config(config)
    backend = model_config["backend"]
    if backend not in MODEL_BACKEND_DEFAULTS:
        raise LLMConfigError(f"Unknown LLM backend: {backend!r}")
    model = model_config[model_key]
    timeout_seconds = model_config["timeout_seconds"]
    max_attempts = model_config["max_attempts"]

    if backend == "claude_code":
        return ClaudeCodeCaller(
            model=model,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
    if backend == "codex_cli":
        from yt2notion.models.codex_cli import CodexCLICaller

        return CodexCLICaller(
            model=model,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            reasoning_effort=model_config.get("reasoning_effort", "low"),
        )
    if backend == "anthropic_api":
        from yt2notion.models.anthropic_api import AnthropicAPICaller

        api_key = model_config.get("api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise LLMConfigError(
                "Anthropic API key required. "
                "Set model.api_key in config or ANTHROPIC_API_KEY env var."
            )
        return AnthropicAPICaller(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
    raise AssertionError(f"Unhandled LLM backend: {backend!r}")
