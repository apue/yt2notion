"""Post-ASR transcript review using LLM (Haiku or Sonnet with context)."""

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
    review_context: dict[str, str] | None = None,
) -> str:
    """Clean up a transcript segment.

    Without context: uses Haiku for basic ASR cleanup.
    With context: uses Sonnet + summary terminology anchors for higher quality.
    """
    if not text or not text.strip():
        return text

    del review_context
    system_prompt = render_prompt("review", title=metadata.title, channel=metadata.channel)
    model_key = "review_model"
    max_tokens = 8000
    caller = create_llm_caller(config, model_key=model_key)
    return caller.call(system_prompt, text, max_tokens=max_tokens).strip()
