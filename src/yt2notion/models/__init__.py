"""Model composition root."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yt2notion.models.llm import create_llm_caller
from yt2notion.models.note_composer import NoteComposer

if TYPE_CHECKING:
    from yt2notion.models.base import Summarizer


def create_summarizer(config: dict) -> Summarizer:
    """Compose note behavior over the configured LLM provider adapter."""
    return NoteComposer(create_llm_caller(config, model_key="translate_model"))
