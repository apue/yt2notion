"""Cohesive in-process preparation logic used by application use cases."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Protocol

import typer

from yt2notion.domain import SegmentSpec, TranscriptSegment
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


Segmenter = Callable[[VideoMeta, dict, bool], tuple[SegmentSpec, ...]]
Reviewer = Callable[
    [Sequence[TranscriptSegment], VideoMeta, dict, Workspace, bool],
    tuple[TranscriptSegment, ...],
]
TopicSegmenter = Callable[
    [Sequence[TranscriptSegment], VideoMeta, dict, int], tuple[TranscriptSegment, ...]
]


class ContentPreparation:
    """Own segmentation, cleanup policy, review, and note-bundle composition."""

    def __init__(
        self,
        *,
        segmenter: Segmenter | None = None,
        reviewer: Reviewer | None = None,
        topic_segmenter: TopicSegmenter = segment_transcript,
        summarizer_factory: Callable[[dict], Summarizer] = create_summarizer,
        bundle_builder: Callable[
            [Sequence[TranscriptSegment], VideoMeta, Summarizer], NoteBundle
        ] = (build_note_bundle),
    ) -> None:
        self._segmenter = segmenter or segment_content
        self._reviewer = reviewer or review_transcripts
        self._topic_segmenter = topic_segmenter
        self._summarizer_factory = summarizer_factory
        self._bundle_builder = bundle_builder

    def segment(
        self,
        metadata: VideoMeta,
        config: AppConfig,
        verbose: bool,
    ) -> tuple[SegmentSpec, ...]:
        return self._segmenter(metadata, _config_mapping(config), verbose)

    def should_topic_segment(self, transcripts: Sequence[TranscriptSegment]) -> bool:
        return should_topic_segment(transcripts)

    def should_cleanup(self, transcripts: Sequence[TranscriptSegment]) -> bool:
        return should_cleanup_transcript(transcripts)

    def topic_segment(
        self,
        transcripts: Sequence[TranscriptSegment],
        metadata: VideoMeta,
        config: AppConfig,
        max_segment_seconds: int,
    ) -> tuple[TranscriptSegment, ...]:
        return self._topic_segmenter(
            transcripts,
            metadata,
            _config_mapping(config),
            max_segment_seconds,
        )

    def review(
        self,
        transcripts: Sequence[TranscriptSegment],
        metadata: VideoMeta,
        config: AppConfig,
        workspace: Workspace,
        verbose: bool,
    ) -> tuple[TranscriptSegment, ...]:
        return self._reviewer(
            transcripts,
            metadata,
            _config_mapping(config),
            workspace,
            verbose,
        )

    def summarize(
        self,
        transcripts: Sequence[TranscriptSegment],
        metadata: VideoMeta,
        config: AppConfig,
    ) -> NoteBundle:
        summarizer = self._summarizer_factory(_config_mapping(config))
        return self._bundle_builder(transcripts, metadata, summarizer)

    def is_long(
        self,
        metadata: VideoMeta,
        transcripts: Sequence[TranscriptSegment],
        config: AppConfig,
    ) -> bool:
        return is_long_content(metadata, transcripts, _config_mapping(config))


def _config_mapping(config: AppConfig) -> dict:
    """Adapt typed application config at the legacy model/helper boundary."""
    return {
        "extract": config.extract,
        "model": config.model,
        "storage": config.storage,
        "credit": config.credit,
        "output": config.output,
    }


def segment_content(metadata: VideoMeta, config: dict, verbose: bool) -> tuple[SegmentSpec, ...]:
    """Determine segments from chapters or description timestamps."""
    if verbose:
        typer.echo("Segmenting...")

    segments: list[SegmentSpec] = []
    if metadata.chapters:
        if verbose:
            typer.echo(f"  Using {len(metadata.chapters)} author chapters")
        segments = [
            SegmentSpec(
                title=chapter.title,
                start_seconds=chapter.start_seconds,
                end_seconds=chapter.end_seconds,
            )
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
            SegmentSpec(
                title=chapter.title,
                start_seconds=chapter.start_seconds,
                end_seconds=chapter.end_seconds,
            )
            for chapter in chapters
        ]
    if not segments and verbose:
        typer.echo("  No structural info — will segment after transcription")

    max_segment_seconds = config.get("output", {}).get("max_segment_seconds", 900)
    subdivided: list[SegmentSpec] = []
    for segment in segments:
        duration = segment.end_seconds - segment.start_seconds
        if duration <= max_segment_seconds:
            subdivided.append(segment)
            continue
        part_count = (duration + max_segment_seconds - 1) // max_segment_seconds
        part_length = duration // part_count
        for index in range(part_count):
            start = segment.start_seconds + index * part_length
            end = (
                segment.start_seconds + (index + 1) * part_length
                if index < part_count - 1
                else segment.end_seconds
            )
            subdivided.append(
                SegmentSpec(
                    title=f"{segment.title} (Part {index + 1})",
                    start_seconds=start,
                    end_seconds=end,
                    parent_title=segment.title,
                )
            )

    if verbose and subdivided:
        typer.echo(f"  {len(subdivided)} segments after subdivision")
    return tuple(subdivided)


MANUAL_TRANSCRIPT_SOURCES = {"manual_subtitle", "manual", "human_subtitle"}


def transcript_source(segment: TranscriptSegment) -> str:
    """Return the best available transcript origin marker."""
    return segment.source.strip().lower() or "subtitle"


def should_cleanup_transcript(transcripts: Sequence[TranscriptSegment]) -> bool:
    """Clean every transcript unless explicitly marked as manual subtitles."""
    if not transcripts:
        return False
    for segment in transcripts:
        if transcript_source(segment) in MANUAL_TRANSCRIPT_SOURCES:
            continue
        return True
    return False


def should_topic_segment(transcripts: Sequence[TranscriptSegment]) -> bool:
    """Topic-split the same ASR-like transcripts that require cleanup."""
    return should_cleanup_transcript(transcripts)


def review_transcripts(
    transcripts: Sequence[TranscriptSegment],
    metadata: VideoMeta,
    config: dict,
    workspace: Workspace,
    verbose: bool,
) -> tuple[TranscriptSegment, ...]:
    """Review transcripts while preserving partial progress."""
    if verbose:
        typer.echo("Reviewing transcripts...")
    from yt2notion.review import review_segment

    partial = workspace.load_reviewed()
    reviewed: list[TranscriptSegment] = list(partial) if partial else []
    start_from = len(reviewed)
    if start_from > 0 and verbose:
        typer.echo(f"  Resuming review from segment {start_from + 1}/{len(transcripts)}")

    for index, segment in enumerate(transcripts):
        if index < start_from:
            continue
        if verbose:
            typer.echo(f"  Review [{index + 1}/{len(transcripts)}] {segment.title}")
        cleaned_text = review_segment(segment.text, metadata, config)
        reviewed.append(
            TranscriptSegment(
                title=segment.title,
                start_seconds=segment.start_seconds,
                end_seconds=segment.end_seconds,
                text=cleaned_text,
                source=segment.source,
            )
        )
        workspace.save_reviewed(reviewed)
    return tuple(reviewed)


def is_long_content(
    metadata: VideoMeta, transcripts: Sequence[TranscriptSegment], config: dict
) -> bool:
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
