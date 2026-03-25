"""Extract chapters from description text using LLM (Haiku)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yt2notion.models._parsers import extract_json_array
from yt2notion.models.llm import create_llm_caller
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
    system_prompt = render_prompt("extract_chapters", total_duration=total_duration)

    caller = create_llm_caller(config)
    raw = caller.call(system_prompt, description, max_tokens=2000)

    return _parse_chapters_json(raw, total_duration)


def _parse_chapters_json(raw: str, total_duration: int) -> list[Chapter]:
    """Parse LLM output into validated Chapter list."""
    from yt2notion.models.base import Chapter

    data = extract_json_array(raw)
    if not data:
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
