"""Intelligent transcript segmentation using all available structure."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from yt2notion.process import SubtitleEntry

if TYPE_CHECKING:
    from yt2notion.models.base import Chapter, VideoMeta


@dataclass
class Segment:
    """A segment of transcript for independent summarization."""

    title: str
    start_seconds: int
    end_seconds: int
    text: str
    parent_title: str | None = None  # set when subdivided from a long chapter


def segment(
    entries: list[SubtitleEntry],
    metadata: VideoMeta,
    *,
    max_segment_seconds: int = 900,
    config: dict | None = None,
) -> list[Segment]:
    """Segment transcript using best available structure.

    Decision waterfall:
    1. YouTube chapters → use as primary segments, subdivide if too long
    2. Description → LLM extracts chapters (falls back to regex)
    3. Fallback → split by duration + sentence boundaries
    """
    if not entries:
        return []

    # 1. YouTube chapters
    if metadata.chapters:
        return _segment_by_chapters(entries, metadata.chapters, max_segment_seconds)

    # 2. Description → LLM chapter extraction (with regex fallback)
    if metadata.description:
        chapters = _extract_chapters_from_description(
            metadata.description, metadata.duration_seconds, config
        )
        if chapters:
            return _segment_by_chapters(entries, chapters, max_segment_seconds)

    # 3. Pure duration + sentence boundary splitting
    return _split_by_duration(entries, max_segment_seconds)


def _extract_chapters_from_description(
    description: str,
    total_duration: int,
    config: dict | None,
) -> list:
    """Extract chapters from description, using LLM if config available."""
    if config:
        from yt2notion.chapter_extract import extract_chapters_llm

        return extract_chapters_llm(description, total_duration, config)

    # No config → regex-only fallback
    return _parse_description_timestamps(description, total_duration)


def _segment_by_chapters(
    entries: list[SubtitleEntry],
    chapters: list[Chapter],
    max_seconds: int,
) -> list[Segment]:
    """Create segments from chapters, subdividing oversized ones."""
    from yt2notion.process import _group_entries_by_chapters

    grouped = _group_entries_by_chapters(entries, chapters)
    segments: list[Segment] = []

    for chapter, texts in grouped:
        if not texts:
            continue
        full_text = " ".join(texts)
        duration = chapter.end_seconds - chapter.start_seconds

        if duration <= max_seconds:
            segments.append(
                Segment(
                    title=chapter.title,
                    start_seconds=chapter.start_seconds,
                    end_seconds=chapter.end_seconds,
                    text=full_text,
                )
            )
        else:
            # Subdivide: collect entries for this chapter, then split
            chapter_entries = [
                e
                for e in entries
                if e.start_seconds >= chapter.start_seconds
                and e.start_seconds < chapter.end_seconds
            ]
            sub_segments = _subdivide_entries(
                chapter_entries, max_seconds, parent_title=chapter.title
            )
            segments.extend(sub_segments)

    return segments


def _subdivide_entries(
    entries: list[SubtitleEntry],
    max_seconds: int,
    *,
    parent_title: str,
) -> list[Segment]:
    """Split a list of entries into segments of max_seconds, at sentence boundaries."""
    if not entries:
        return []

    segments: list[Segment] = []
    current_entries: list[SubtitleEntry] = []
    segment_start = int(entries[0].start_seconds)
    part_num = 1

    for entry in entries:
        current_entries.append(entry)
        elapsed = entry.end_seconds - segment_start

        if elapsed >= max_seconds:
            # Find sentence boundary to split
            texts = [e.text for e in current_entries]
            full_text = " ".join(texts)
            split_idx = _find_sentence_boundary(full_text)

            if split_idx and split_idx < len(full_text) - 10:
                seg_text = full_text[:split_idx].strip()
                remainder_text = full_text[split_idx:].strip()
            else:
                seg_text = full_text.strip()
                remainder_text = ""

            segments.append(
                Segment(
                    title=f"{parent_title} (Part {part_num})",
                    start_seconds=segment_start,
                    end_seconds=int(entry.end_seconds),
                    text=seg_text,
                    parent_title=parent_title,
                )
            )
            part_num += 1

            if remainder_text:
                # Carry remainder into next segment
                current_entries = [
                    SubtitleEntry(
                        start_seconds=entry.end_seconds,
                        end_seconds=entry.end_seconds,
                        text=remainder_text,
                    )
                ]
            else:
                current_entries = []
            segment_start = int(entry.end_seconds)

    # Flush remaining
    if current_entries:
        text = " ".join(e.text for e in current_entries).strip()
        if text:
            last_end = int(current_entries[-1].end_seconds)
            segments.append(
                Segment(
                    title=f"{parent_title} (Part {part_num})" if part_num > 1 else parent_title,
                    start_seconds=segment_start,
                    end_seconds=last_end,
                    text=text,
                    parent_title=parent_title if part_num > 1 else None,
                )
            )

    return segments


def _split_by_duration(
    entries: list[SubtitleEntry],
    max_seconds: int,
) -> list[Segment]:
    """Split entries by duration with sentence boundary snapping. No chapter info."""
    if not entries:
        return []

    segments: list[Segment] = []
    current_entries: list[SubtitleEntry] = []
    segment_start = int(entries[0].start_seconds)
    part_num = 1

    for entry in entries:
        current_entries.append(entry)
        elapsed = entry.end_seconds - segment_start

        if elapsed >= max_seconds and current_entries:
            text = " ".join(e.text for e in current_entries).strip()
            segments.append(
                Segment(
                    title=f"Part {part_num}",
                    start_seconds=segment_start,
                    end_seconds=int(entry.end_seconds),
                    text=text,
                )
            )
            part_num += 1
            current_entries = []
            segment_start = int(entry.end_seconds)

    if current_entries:
        text = " ".join(e.text for e in current_entries).strip()
        if text:
            segments.append(
                Segment(
                    title=f"Part {part_num}",
                    start_seconds=segment_start,
                    end_seconds=int(current_entries[-1].end_seconds),
                    text=text,
                )
            )

    return segments


# --- Description timestamp parsing ---

_TS_PATTERN = re.compile(
    r"^[\s\-•]*"
    r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})"
    r"[\s\-–—:]*"
    r"(.+)$",
    re.MULTILINE,
)


@dataclass
class _PseudoChapter:
    """Mimics Chapter interface for reuse with _segment_by_chapters."""

    title: str
    start_seconds: int
    end_seconds: int


def _parse_description_timestamps(
    description: str,
    total_duration: int,
) -> list[_PseudoChapter]:
    """Parse timestamps from video description text.

    Handles formats like:
      00:01:19 The normal one
      0:35:40 世界总不让我做Vision
      35:40 Some topic
      - 1:23:45 Topic name
    """
    matches = _TS_PATTERN.findall(description)
    if len(matches) < 2:
        return []

    raw: list[tuple[int, str]] = []
    for hours, minutes, seconds, title in matches:
        h = int(hours) if hours else 0
        total = h * 3600 + int(minutes) * 60 + int(seconds)
        title = title.strip()
        if title:
            raw.append((total, title))

    # Sort by time and deduplicate
    raw.sort(key=lambda x: x[0])

    chapters: list[_PseudoChapter] = []
    for i, (start, title) in enumerate(raw):
        end = raw[i + 1][0] if i + 1 < len(raw) else total_duration
        chapters.append(_PseudoChapter(title=title, start_seconds=start, end_seconds=end))

    return chapters


# --- Sentence boundary detection ---

_SENTENCE_END = re.compile(r"[。！？.!?]\s*")


def _find_sentence_boundary(text: str) -> int | None:
    """Find the last sentence boundary in the second half of text.

    Returns the character index right after the sentence-ending punctuation,
    or None if no boundary found.
    """
    midpoint = len(text) // 2
    best = None

    for match in _SENTENCE_END.finditer(text):
        pos = match.end()
        if pos >= midpoint:
            if best is None:
                best = pos
            break
        best = pos

    return best
