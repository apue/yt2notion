"""Cohesive in-process preparation logic used by application use cases."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

import typer

from yt2notion.models import create_summarizer
from yt2notion.models.base import VideoMeta
from yt2notion.note_bundle import build_note_bundle
from yt2notion.retry import RetryExhaustedError
from yt2notion.topic_segment import segment_transcript
from yt2notion.workspace import Workspace

if TYPE_CHECKING:
    from yt2notion.config import AppConfig
    from yt2notion.models.base import NoteBundle, Summarizer


class PreparedContentView(Protocol):
    """Minimum prepared-content shape required by the renderer."""

    metadata: VideoMeta
    note_bundle: NoteBundle


Segmenter = Callable[[VideoMeta, dict, bool], list[dict]]
Reviewer = Callable[[list[dict], VideoMeta, dict, Workspace, bool], list[dict]]
TopicSegmenter = Callable[[list[dict], VideoMeta, dict, int], list[dict]]


class ContentPreparation:
    """Own segmentation, cleanup policy, review, and note-bundle composition."""

    def __init__(
        self,
        *,
        segmenter: Segmenter | None = None,
        reviewer: Reviewer | None = None,
        topic_segmenter: TopicSegmenter = segment_transcript,
        summarizer_factory: Callable[[dict], Summarizer] = create_summarizer,
        bundle_builder: Callable[[list[dict], VideoMeta, Summarizer], NoteBundle] = (
            build_note_bundle
        ),
    ) -> None:
        self._segmenter = segmenter or segment_content
        self._reviewer = reviewer or review_transcripts
        self._topic_segmenter = topic_segmenter
        self._summarizer_factory = summarizer_factory
        self._bundle_builder = bundle_builder

    def segment(self, metadata: VideoMeta, config: dict, verbose: bool) -> list[dict]:
        return self._segmenter(metadata, config, verbose)

    def should_topic_segment(self, transcripts: list[dict]) -> bool:
        return should_topic_segment(transcripts)

    def should_cleanup(self, transcripts: list[dict]) -> bool:
        return should_cleanup_transcript(transcripts)

    def topic_segment(
        self,
        transcripts: list[dict],
        metadata: VideoMeta,
        config: dict,
        max_segment_seconds: int,
    ) -> list[dict]:
        return self._topic_segmenter(transcripts, metadata, config, max_segment_seconds)

    def review(
        self,
        transcripts: list[dict],
        metadata: VideoMeta,
        config: dict,
        workspace: Workspace,
        verbose: bool,
    ) -> list[dict]:
        return self._reviewer(transcripts, metadata, config, workspace, verbose)

    def summarize(
        self,
        transcripts: list[dict],
        metadata: VideoMeta,
        config: dict,
    ) -> NoteBundle:
        summarizer = self._summarizer_factory(config)
        return self._bundle_builder(transcripts, metadata, summarizer)

    def is_long(self, metadata: VideoMeta, transcripts: list[dict], config: dict) -> bool:
        return is_long_content(metadata, transcripts, config)


def segment_content(metadata: VideoMeta, config: dict, verbose: bool) -> list[dict]:
    """Determine segments from chapters or description timestamps."""
    if verbose:
        typer.echo("Segmenting...")

    segments: list[dict] = []
    if metadata.chapters:
        if verbose:
            typer.echo(f"  Using {len(metadata.chapters)} author chapters")
        segments = [
            {
                "title": chapter.title,
                "start_seconds": chapter.start_seconds,
                "end_seconds": chapter.end_seconds,
            }
            for chapter in metadata.chapters
        ]
    elif metadata.description:
        from yt2notion.segment import _extract_chapters_from_description

        chapters = _extract_chapters_from_description(
            metadata.description, metadata.duration_seconds, config
        )
        if verbose and chapters:
            typer.echo(f"  Found {len(chapters)} timestamp chapters in description")
        segments = [
            {
                "title": chapter.title,
                "start_seconds": chapter.start_seconds,
                "end_seconds": chapter.end_seconds,
            }
            for chapter in chapters
        ]
    if not segments and verbose:
        typer.echo("  No structural info — will segment after transcription")

    max_segment_seconds = config.get("output", {}).get("max_segment_seconds", 900)
    subdivided: list[dict] = []
    for segment in segments:
        duration = segment["end_seconds"] - segment["start_seconds"]
        if duration <= max_segment_seconds:
            subdivided.append(segment)
            continue
        part_count = (duration + max_segment_seconds - 1) // max_segment_seconds
        part_length = duration // part_count
        for index in range(part_count):
            start = segment["start_seconds"] + index * part_length
            end = (
                segment["start_seconds"] + (index + 1) * part_length
                if index < part_count - 1
                else segment["end_seconds"]
            )
            subdivided.append(
                {
                    "title": f"{segment['title']} (Part {index + 1})",
                    "start_seconds": start,
                    "end_seconds": end,
                    "parent_title": segment["title"],
                }
            )

    if verbose and subdivided:
        typer.echo(f"  {len(subdivided)} segments after subdivision")
    return subdivided


MANUAL_TRANSCRIPT_SOURCES = {"manual_subtitle", "manual", "human_subtitle"}


def transcript_source(segment: dict) -> str:
    """Return the best available transcript origin marker."""
    for key in ("origin", "transcript_origin", "source", "kind"):
        value = str(segment.get(key, "")).strip().lower()
        if value:
            return value
    return "subtitle"


def should_cleanup_transcript(transcripts: list[dict]) -> bool:
    """Clean every transcript unless explicitly marked as manual subtitles."""
    if not transcripts:
        return False
    for segment in transcripts:
        if segment.get("is_auto_generated") is True or segment.get("auto_caption") is True:
            return True
        if transcript_source(segment) in MANUAL_TRANSCRIPT_SOURCES:
            continue
        return True
    return False


def should_topic_segment(transcripts: list[dict]) -> bool:
    """Topic-split the same ASR-like transcripts that require cleanup."""
    return should_cleanup_transcript(transcripts)


def review_transcripts(
    transcripts: list[dict],
    metadata: VideoMeta,
    config: dict,
    workspace: Workspace,
    verbose: bool,
) -> list[dict]:
    """Review transcripts while preserving partial progress."""
    if verbose:
        typer.echo("Reviewing transcripts...")
    from yt2notion.review import review_segment

    partial = workspace.load_reviewed()
    reviewed: list[dict] = list(partial) if partial else []
    start_from = len(reviewed)
    if start_from > 0 and verbose:
        typer.echo(f"  Resuming review from segment {start_from + 1}/{len(transcripts)}")

    for index, segment in enumerate(transcripts):
        if index < start_from:
            continue
        if verbose:
            typer.echo(f"  Review [{index + 1}/{len(transcripts)}] {segment.get('title', '')}")
        cleaned_text = review_segment(segment["text"], metadata, config)
        reviewed.append({**segment, "text": cleaned_text})
        workspace.save_reviewed(reviewed)
    return reviewed


def is_long_content(metadata: VideoMeta, transcripts: list[dict], config: dict) -> bool:
    """Return whether content exceeds the configured long-content threshold."""
    threshold = config.get("output", {}).get("long_content_threshold_seconds", 1800)
    return metadata.duration_seconds >= threshold or len(transcripts) > 3


def render_prepared_output(prepared: PreparedContentView, config: AppConfig) -> str:
    """Render human-readable dry-run output from a prepared bundle."""
    credit_format = config.credit.get("format", "来源：{channel} 「{title}」\n链接：{url}")
    credit = credit_format.format(
        channel=prepared.metadata.channel,
        title=prepared.metadata.title,
        url=prepared.metadata.url,
    )
    return "\n\n".join(
        [
            credit,
            "# Source",
            prepared.note_bundle.source.markdown,
            "# A / Guide",
            prepared.note_bundle.guide.markdown,
            "# B / Longform",
            prepared.note_bundle.longform.markdown,
        ]
    )


def is_retries_exhausted(exc: Exception) -> bool:
    """Detect whether an exception chain contains RetryExhaustedError."""
    current: Exception | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        if isinstance(current, RetryExhaustedError):
            return True
        seen.add(id(current))
        next_exc = current.__cause__ or current.__context__
        current = next_exc if isinstance(next_exc, Exception) else None
    return False
