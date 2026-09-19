"""Post-ASR topic segmentation using LLM (Haiku).

Splits long transcript text into semantically coherent segments
by finding natural topic boundaries. Used when no outline/chapters
are available, or when existing segments exceed a duration threshold.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from yt2notion.domain import TranscriptSegment
from yt2notion.models._parsers import extract_json_array
from yt2notion.models.llm import create_llm_caller
from yt2notion.prompts import render_prompt
from yt2notion.runtime import provider_call

if TYPE_CHECKING:
    from yt2notion.models.base import VideoMeta


# Characters per second of speech (rough estimate for English)
_CHARS_PER_SECOND = 15


@dataclass(frozen=True)
class TopicBoundary:
    """Validated topic split returned by the LLM codec boundary."""

    title: str
    start_char: int


def segment_transcript(
    transcripts: Sequence[TranscriptSegment],
    metadata: VideoMeta,
    config: dict,
    max_segment_seconds: int = 600,
) -> tuple[TranscriptSegment, ...]:
    """Split transcript segments that exceed max_segment_seconds.

    For each oversized segment, uses Haiku to find natural topic
    boundaries in the text, then splits accordingly.

    Segments within the threshold are passed through unchanged.

    Returns a new list of transcript dicts with finer segmentation.
    """
    result: list[TranscriptSegment] = []

    for seg in transcripts:
        duration = seg.end_seconds - seg.start_seconds
        # If end_seconds is 0 (no timing info), estimate from text length
        if duration <= 0:
            duration = len(seg.text) / _CHARS_PER_SECOND

        if duration <= max_segment_seconds or len(seg.text) < 1500:
            result.append(seg)
            continue

        # This segment is too long — split it
        sub_segments = _split_segment(seg, metadata, config)
        result.extend(sub_segments)

    return tuple(result)


def _split_segment(
    seg: TranscriptSegment,
    metadata: VideoMeta,
    config: dict,
) -> tuple[TranscriptSegment, ...]:
    """Use Haiku to find topic boundaries within a single long segment."""
    text = seg.text
    if not text.strip():
        return (seg,)

    seg_start = seg.start_seconds
    seg_end = seg.end_seconds
    seg_duration = seg_end - seg_start
    if seg_duration <= 0:
        seg_duration = len(text) / _CHARS_PER_SECOND

    system_prompt = render_prompt(
        "topic_segment",
        channel=metadata.channel,
        title=metadata.title,
        duration_seconds=str(int(seg_duration)),
        char_count=str(len(text)),
    )

    caller = create_llm_caller(config)
    with provider_call("llm.topic_segment"):
        raw = caller.call(system_prompt, text)

    boundaries = _parse_boundaries(raw, len(text))
    if not boundaries or len(boundaries) < 2:
        # LLM failed to produce useful boundaries — return as-is
        return (seg,)

    return _apply_boundaries(seg, text, boundaries, seg_start, seg_duration)


def _parse_boundaries(raw: str, text_length: int) -> list[TopicBoundary]:
    """Parse LLM JSON output into typed topic boundaries."""
    data = extract_json_array(raw)
    if len(data) < 2:
        return []

    # Validate: start_char values must be ascending and within range
    boundaries: list[TopicBoundary] = []
    for item in data:
        sc = int(item.get("start_char", 0))
        title = item.get("title", "").strip()
        if sc < 0:
            sc = 0
        if sc >= text_length:
            continue
        boundaries.append(TopicBoundary(title=title, start_char=sc))

    # Ensure ascending order
    boundaries.sort(key=lambda boundary: boundary.start_char)

    # First boundary must start at 0
    if boundaries and boundaries[0].start_char != 0:
        boundaries[0] = TopicBoundary(title=boundaries[0].title, start_char=0)

    return boundaries


def _apply_boundaries(
    orig_seg: TranscriptSegment,
    text: str,
    boundaries: list[TopicBoundary],
    seg_start_seconds: float,
    seg_duration: float,
) -> tuple[TranscriptSegment, ...]:
    """Create new segment dicts from boundary positions."""
    total_chars = len(text)
    result: list[TranscriptSegment] = []

    for i, boundary in enumerate(boundaries):
        start_char = boundary.start_char
        end_char = boundaries[i + 1].start_char if i + 1 < len(boundaries) else total_chars

        chunk_text = text[start_char:end_char].strip()
        if not chunk_text:
            continue

        # Estimate time boundaries proportionally
        time_start = seg_start_seconds + (start_char / total_chars) * seg_duration
        time_end = seg_start_seconds + (end_char / total_chars) * seg_duration

        result.append(
            TranscriptSegment(
                title=boundary.title or f"Part {i + 1}",
                start_seconds=round(time_start),
                end_seconds=round(time_end),
                text=chunk_text,
                source=orig_seg.source,
            )
        )

    return tuple(result)
