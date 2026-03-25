"""Lightweight LLM caller for one-shot text-in/text-out tasks.

Used by utility modules (review, chapter_extract, topic_segment) that need
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
            "--max-tokens",
            str(max_tokens),
        ]
        try:
            result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, check=True)
        except FileNotFoundError:
            raise RuntimeError("'claude' CLI not found on PATH") from None
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"claude CLI failed (exit {e.returncode}): {e.stderr[:200]}") from e
        try:
            output = json.loads(result.stdout)
            return output.get("result", result.stdout)
        except json.JSONDecodeError:
            return result.stdout


def create_llm_caller(config: dict, *, model_key: str = "review_model") -> LLMCaller:
    """Create an LLMCaller from config.

    Args:
        config: Raw config dict (top-level, containing "model" key).
        model_key: Which model field to use (default: "review_model").
    """
    model_cfg = config.get("model", {})
    backend = model_cfg.get("backend", "claude_code")
    model = model_cfg.get(model_key, "haiku")

    if backend == "claude_code":
        return ClaudeCodeCaller(model=model)

    raise ValueError(f"Unknown LLM backend: {backend!r}")
