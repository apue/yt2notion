"""Post-ASR transcript review using LLM (Haiku)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from yt2notion.prompts import render_prompt

if TYPE_CHECKING:
    from yt2notion.models.base import VideoMeta


def review_segment(
    text: str,
    metadata: VideoMeta,
    config: dict,
) -> str:
    """Clean up a transcript segment using Haiku.

    Fixes ASR errors, removes filler words, unifies terminology.
    Returns the cleaned text.
    """
    if not text or not text.strip():
        return text

    model_cfg = config.get("model", {})
    backend = model_cfg.get("backend", "claude_code")
    review_model = model_cfg.get("review_model", "haiku")

    system_prompt = render_prompt(
        "review",
        title=metadata.title,
        channel=metadata.channel,
    )

    if backend == "claude_code":
        return _call_claude_code(system_prompt, text, review_model)
    elif backend == "anthropic_api":
        return _call_anthropic_api(system_prompt, text, review_model, model_cfg)

    return text  # Unknown backend, return as-is


def _call_claude_code(system_prompt: str, user_prompt: str, model: str) -> str:
    """Call claude CLI for transcript review."""
    import subprocess

    prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
    cmd = [
        "claude",
        "-p",
        "--model",
        model,
        "--max-turns",
        "1",
        "--output-format",
        "json",
    ]
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, check=True)
    try:
        output = json.loads(result.stdout)
        return output.get("result", result.stdout).strip()
    except json.JSONDecodeError:
        return result.stdout.strip()


def _call_anthropic_api(system_prompt: str, user_prompt: str, model: str, model_cfg: dict) -> str:
    """Call Anthropic API for transcript review."""
    import anthropic

    model_map = {
        "haiku": "claude-haiku-4-5-20251001",
        "sonnet": "claude-sonnet-4-6",
        "opus": "claude-opus-4-6",
    }
    api_model = model_map.get(model, model)
    client = anthropic.Anthropic(api_key=model_cfg.get("api_key", ""))
    response = client.messages.create(
        model=api_model,
        max_tokens=8000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text.strip()
