"""Orchestration helpers for source + A/B note bundles."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yt2notion.models.base import (
    NOTE_VARIANT_SOURCE,
    NoteBundle,
    NoteDocument,
    NoteMetadata,
)
from yt2notion.process import seconds_to_display

if TYPE_CHECKING:
    from yt2notion.models.base import Summarizer, VideoMeta


def resolve_note_targets(duration_seconds: int) -> tuple[int, int]:
    """Resolve guide/longform target lengths from content duration."""
    hours = max(0.0, float(duration_seconds)) / 3600.0
    delta_hours = max(0.0, hours - 1.0)
    guide_target = int(round(2000 + delta_hours * 500))
    longform_target = int(round(7000 + delta_hours * 500))
    guide_target = max(2000, min(4000, guide_target))
    longform_target = max(7000, min(9000, longform_target))
    return guide_target, longform_target


def format_note_bundle_transcript(reviewed: list[dict]) -> str:
    """Format reviewed transcript as a continuous note-bundle source text."""
    lines: list[str] = []
    for segment in reviewed:
        start = seconds_to_display(int(segment.get("start_seconds", 0)))
        title = str(segment.get("title", "")).strip()
        text = str(segment.get("text", "")).strip()
        lines.append(f"### [{start}] {title}")
        lines.append("")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip()


def build_source_note(
    metadata: VideoMeta,
    note_metadata: NoteMetadata,
    guide_note: NoteDocument,
    longform_note: NoteDocument,
) -> NoteDocument:
    """Build the lightweight source index note for the bundle."""
    source_title = note_metadata.source_title or metadata.title
    summary = note_metadata.source_summary.strip()
    topics = note_metadata.source_topics

    topic_lines = "\n".join(f"- {topic}" for topic in topics) if topics else "- 无"
    markdown = "\n\n".join(
        [
            f"# {source_title}",
            "## 来源定位 / 摘要",
            summary,
            "## 核心主题",
            topic_lines,
            "## 阅读入口",
            f"- 导读版：{guide_note.title}",
            f"- 扩展版：{longform_note.title}",
            "## 原始链接",
            metadata.url or "（未提供）",
        ]
    )

    return NoteDocument(
        title=source_title,
        markdown=markdown.strip(),
        tags=note_metadata.stable_tags,
        variant=NOTE_VARIANT_SOURCE,
    )


def build_note_bundle(
    reviewed: list[dict],
    metadata: VideoMeta,
    summarizer: Summarizer,
) -> NoteBundle:
    """Build the full source + A/B note bundle."""
    transcript = format_note_bundle_transcript(reviewed)
    guide_target, longform_target = resolve_note_targets(metadata.duration_seconds)

    guide_note = summarizer.compose_guide_note(
        transcript,
        metadata,
        target_chars=guide_target,
    )
    longform_note = summarizer.compose_longform_note(
        transcript,
        guide_note,
        metadata,
        target_chars=longform_target,
    )
    note_metadata = summarizer.compose_note_metadata(guide_note, longform_note, metadata)
    source_note = build_source_note(metadata, note_metadata, guide_note, longform_note)

    return NoteBundle(
        source=source_note,
        guide=guide_note,
        longform=longform_note,
        stable_tags=note_metadata.stable_tags,
        source_topics=note_metadata.source_topics,
    )
