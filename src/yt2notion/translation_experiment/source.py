"""Source-contract construction and deterministic semantic grouping."""

from __future__ import annotations

import re
from collections.abc import Sequence

from yt2notion.translation_experiment.models import (
    CanonicalTranscript,
    SourceBlock,
    SourceChapter,
)

DEFAULT_BLOCK_TARGET_CHARS = 700
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?。！？])\s+")


class SourceContractError(ValueError):
    """Raised when transcript input cannot form an experiment source."""


def build_source_chapters(
    transcripts: Sequence[CanonicalTranscript],
    *,
    block_target_chars: int = DEFAULT_BLOCK_TARGET_CHARS,
) -> tuple[SourceChapter, ...]:
    """Build stable chapter/block IDs from the canonical transcript artifact."""
    if block_target_chars < 20:
        raise ValueError("block_target_chars must be at least 20")
    if not transcripts:
        raise SourceContractError("translation experiment requires at least one transcript")

    chapters: list[SourceChapter] = []
    for chapter_index, transcript in enumerate(transcripts, start=1):
        title = _required_text(transcript, "title", chapter_index)
        source_text = _required_text(transcript, "text", chapter_index)
        start_seconds = _required_seconds(transcript, "start_seconds", chapter_index)
        end_seconds = _required_seconds(transcript, "end_seconds", chapter_index)
        if end_seconds < start_seconds:
            raise SourceContractError(f"chapter {chapter_index} ends before it starts")

        chapter_id = f"c{chapter_index:03d}"
        block_texts = _group_semantic_blocks(source_text, block_target_chars)
        blocks = tuple(
            SourceBlock(block_id=f"{chapter_id}-b{block_index:03d}", source_text=text)
            for block_index, text in enumerate(block_texts, start=1)
        )
        chapters.append(
            SourceChapter(
                chapter_id=chapter_id,
                title=title,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                source_text=source_text,
                blocks=blocks,
            )
        )
    return tuple(chapters)


def _required_text(transcript: CanonicalTranscript, field: str, chapter_index: int) -> str:
    value = transcript.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SourceContractError(f"chapter {chapter_index} has invalid {field!r}")
    return " ".join(value.split())


def _required_seconds(transcript: CanonicalTranscript, field: str, chapter_index: int) -> int:
    value = transcript.get(field)
    if not isinstance(value, int | float):
        raise SourceContractError(f"chapter {chapter_index} has invalid {field!r}")
    return int(value)


def _group_semantic_blocks(text: str, target_chars: int) -> list[str]:
    sentences = _SENTENCE_BOUNDARY.split(text)
    units: list[str] = []
    for sentence in sentences:
        normalized = " ".join(sentence.split())
        if not normalized:
            continue
        units.extend(_split_oversized_unit(normalized, target_chars))

    blocks: list[str] = []
    current: list[str] = []
    current_length = 0
    for unit in units:
        projected = current_length + len(unit) + (1 if current else 0)
        if current and projected > target_chars:
            blocks.append(" ".join(current))
            current = []
            current_length = 0
        current.append(unit)
        current_length += len(unit) + (1 if current_length else 0)
    if current:
        blocks.append(" ".join(current))
    return blocks


def _split_oversized_unit(text: str, target_chars: int) -> list[str]:
    if len(text) <= target_chars:
        return [text]
    words = text.split()
    if len(words) == 1:
        return [text[i : i + target_chars] for i in range(0, len(text), target_chars)]

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for word in words:
        projected = current_length + len(word) + (1 if current else 0)
        if current and projected > target_chars:
            chunks.append(" ".join(current))
            current = []
            current_length = 0
        current.append(word)
        current_length += len(word) + (1 if current_length else 0)
    if current:
        chunks.append(" ".join(current))
    return chunks
