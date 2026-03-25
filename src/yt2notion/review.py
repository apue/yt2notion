"""Post-ASR transcript review using LLM (Haiku)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yt2notion.models.llm import create_llm_caller
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

    system_prompt = render_prompt(
        "review",
        title=metadata.title,
        channel=metadata.channel,
    )

    caller = create_llm_caller(config)
    return caller.call(system_prompt, text, max_tokens=8000).strip()
