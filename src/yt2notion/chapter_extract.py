"""Extract chapters from description text using LLM (Haiku)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from yt2notion.prompts import render_prompt
from yt2notion.segment import _parse_description_timestamps

if TYPE_CHECKING:
    from yt2notion.models.base import Chapter


def extract_chapters_llm(
    description: str,
    total_duration: int,
    config: dict,
) -> list[Chapter]:
    """Use LLM to extract timestamped chapters from a description.

    Falls back to regex parsing if LLM fails or returns nothing.
    """
    from yt2notion.models.base import Chapter

    if not description or not description.strip():
        return []

    # Try LLM extraction first
    try:
        chapters = _call_llm(description, total_duration, config)
        if chapters:
            return chapters
    except Exception:
        pass  # Fall through to regex

    # Fallback: regex-based extraction
    pseudo = _parse_description_timestamps(description, total_duration)
    return [
        Chapter(title=p.title, start_seconds=p.start_seconds, end_seconds=p.end_seconds)
        for p in pseudo
    ]


def _call_llm(
    description: str,
    total_duration: int,
    config: dict,
) -> list[Chapter]:
    """Call the configured model backend to extract chapters."""

    model_cfg = config.get("model", {})
    backend = model_cfg.get("backend", "claude_code")
    review_model = model_cfg.get("review_model", "haiku")

    system_prompt = render_prompt("extract_chapters", total_duration=total_duration)

    if backend == "claude_code":
        raw = _call_claude_code(system_prompt, description, review_model)
    elif backend == "anthropic_api":
        raw = _call_anthropic_api(system_prompt, description, review_model, model_cfg)
    else:
        return []

    return _parse_chapters_json(raw, total_duration)


def _call_claude_code(system_prompt: str, user_prompt: str, model: str) -> str:
    """Call claude CLI for chapter extraction."""
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
        return output.get("result", result.stdout)
    except json.JSONDecodeError:
        return result.stdout


def _call_anthropic_api(system_prompt: str, user_prompt: str, model: str, model_cfg: dict) -> str:
    """Call Anthropic API for chapter extraction."""
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
        max_tokens=2000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text


def _parse_chapters_json(raw: str, total_duration: int) -> list[Chapter]:
    """Parse LLM output into validated Chapter list."""
    from yt2notion.models.base import Chapter

    # Extract JSON array from response
    text = raw.strip()
    # Handle markdown code fences
    if "```" in text:
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            text = text[start : end + 1]

    data = json.loads(text)
    if not isinstance(data, list) or not data:
        return []

    chapters: list[Chapter] = []
    for item in data:
        title = item.get("title", "").strip()
        start = int(item.get("start_seconds", 0))
        end = int(item.get("end_seconds", 0))
        if title and start >= 0 and end > start:
            chapters.append(Chapter(title=title, start_seconds=start, end_seconds=end))

    # Validate: timestamps should be ascending
    for i in range(1, len(chapters)):
        if chapters[i].start_seconds < chapters[i - 1].start_seconds:
            return []  # Invalid ordering, discard

    # Fix last chapter end to match total duration
    if chapters and total_duration > 0:
        chapters[-1] = Chapter(
            title=chapters[-1].title,
            start_seconds=chapters[-1].start_seconds,
            end_seconds=total_duration,
        )

    return chapters
