"""Subtitle file processing: parsing, cleaning, chunking with timestamps."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class ProcessError(Exception):
    """Raised when subtitle processing fails."""


def seconds_to_display(s: int | float) -> str:
    """Convert seconds to M:SS display format. Shared utility."""
    minutes, secs = divmod(int(s), 60)
    return f"{minutes}:{secs:02d}"


@dataclass
class SubtitleEntry:
    """A single subtitle entry with timing."""

    start_seconds: float
    end_seconds: float
    text: str


@dataclass
class Chunk:
    """A time-windowed chunk of transcript text."""

    start_seconds: int
    text: str

    @property
    def timestamp_display(self) -> str:
        return seconds_to_display(self.start_seconds)


def _time_to_seconds(time_str: str) -> float:
    """Convert SRT/VTT time string to seconds.

    Handles both comma (SRT: 00:01:23,456) and dot (VTT: 00:01:23.456) formats.
    """
    time_str = time_str.replace(",", ".")
    parts = time_str.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return float(time_str)


def parse_srt(path: Path) -> list[SubtitleEntry]:
    """Parse an SRT subtitle file into entries."""
    if path.stat().st_size == 0:
        return []

    import pysrt

    subs = pysrt.open(str(path), encoding="utf-8")
    entries = []
    for sub in subs:
        start = (
            sub.start.hours * 3600
            + sub.start.minutes * 60
            + sub.start.seconds
            + sub.start.milliseconds / 1000
        )
        end = (
            sub.end.hours * 3600
            + sub.end.minutes * 60
            + sub.end.seconds
            + sub.end.milliseconds / 1000
        )
        text = clean_text(sub.text)
        if text:
            entries.append(SubtitleEntry(start_seconds=start, end_seconds=end, text=text))
    return entries


def parse_vtt(path: Path) -> list[SubtitleEntry]:
    """Parse a WebVTT subtitle file into entries."""
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        return []

    entries = []
    pattern = re.compile(r"(\d{1,2}:?\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{1,2}:?\d{2}:\d{2}[.,]\d{3})")

    lines = content.split("\n")
    i = 0
    while i < len(lines):
        match = pattern.match(lines[i].strip())
        if match:
            start = _time_to_seconds(match.group(1))
            end = _time_to_seconds(match.group(2))
            text_lines = []
            i += 1
            while i < len(lines) and lines[i].strip():
                text_lines.append(lines[i].strip())
                i += 1
            text = clean_text(" ".join(text_lines))
            if text:
                entries.append(SubtitleEntry(start_seconds=start, end_seconds=end, text=text))
        else:
            i += 1
    return entries


def parse_subtitle_file(path: Path) -> list[SubtitleEntry]:
    """Parse a subtitle file based on its extension."""
    suffix = path.suffix.lower()
    if suffix == ".srt":
        return parse_srt(path)
    elif suffix == ".vtt":
        return parse_vtt(path)
    else:
        raise ProcessError(f"Unsupported subtitle format: {suffix}")


def clean_text(text: str) -> str:
    """Clean subtitle text: strip HTML tags, collapse whitespace."""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def chunk_by_time(entries: list[SubtitleEntry], chunk_seconds: int = 120) -> list[Chunk]:
    """Group subtitle entries into time-windowed chunks."""
    if not entries:
        return []

    chunks: list[Chunk] = []
    current_start = int(entries[0].start_seconds)
    current_texts: list[str] = []
    chunk_boundary = current_start + chunk_seconds

    for entry in entries:
        if entry.start_seconds >= chunk_boundary and current_texts:
            chunks.append(Chunk(start_seconds=current_start, text=" ".join(current_texts)))
            current_start = int(entry.start_seconds)
            current_texts = []
            chunk_boundary = current_start + chunk_seconds
        current_texts.append(entry.text)

    if current_texts:
        chunks.append(Chunk(start_seconds=current_start, text=" ".join(current_texts)))

    return chunks


def _group_entries_by_chapters(
    entries: list[SubtitleEntry],
    chapters: list,
) -> list[tuple[object, list[str]]]:
    """Group subtitle entry texts by chapter boundaries in a single pass.

    Returns list of (chapter, [texts]) tuples.
    """
    if not entries or not chapters:
        return []

    result: list[tuple[object, list[str]]] = [(ch, []) for ch in chapters]
    ch_idx = 0

    for entry in entries:
        # Advance to the correct chapter
        while ch_idx < len(chapters) - 1 and entry.start_seconds >= chapters[ch_idx].end_seconds:
            ch_idx += 1
        ch = chapters[ch_idx]
        if entry.start_seconds >= ch.start_seconds and entry.start_seconds < ch.end_seconds:
            result[ch_idx][1].append(entry.text)

    return result


def format_chapters_transcript(
    entries: list[SubtitleEntry],
    chapters: list,
) -> str:
    """Format transcript grouped by author-defined chapters."""
    parts = []
    for ch, texts in _group_entries_by_chapters(entries, chapters):
        if texts:
            ts = seconds_to_display(ch.start_seconds)
            parts.append(f'[CHAPTER start={ts} title="{ch.title}"]\n{" ".join(texts)}')
    return "\n\n".join(parts)


def format_timestamped_transcript(entries: list[SubtitleEntry]) -> str:
    """Format full transcript with per-line timestamps for LLM segmentation."""
    return "\n".join(f"[{seconds_to_display(e.start_seconds)}] {e.text}" for e in entries)


def format_chunks(chunks: list[Chunk], video_id: str) -> str:
    """Format chunks into the prompt template format."""
    return "\n\n".join(f"[CHUNK start={chunk.timestamp_display}]\n{chunk.text}" for chunk in chunks)
