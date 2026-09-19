"""Top-level subtitle and audio transcription orchestration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

import typer

from yt2notion.domain import SegmentSpec, TranscriptSegment
from yt2notion.extract import ExtractionError
from yt2notion.process import SubtitleEntry, parse_subtitle_file
from yt2notion.transcribe.audio_plan import (
    ASR_CHUNK_PADDING_SECONDS,
    FULL_AUDIO_ASR_CHUNK_SECONDS,
    MIN_ASR_UPLOAD_CHUNK_SECONDS,
    build_full_audio_transcribe_plan,
    build_segment_transcribe_plan,
)
from yt2notion.transcribe.base import Transcriber
from yt2notion.transcribe.checkpoint import (
    describe_backend_outcome,
    entries_from_chunk_payload,
    load_or_create_transcribe_state,
    load_required_chunk_payload,
)
from yt2notion.transcribe.chunk_executor import (
    ProgressCallback,
    ProgressEvent,
    TranscriberFactory,
    execute_chunk_plan,
)

if TYPE_CHECKING:
    from yt2notion.models.base import VideoMeta
    from yt2notion.transcribe.contracts import TranscribeChunk
    from yt2notion.workspace import Workspace

__all__ = [
    "ASR_CHUNK_PADDING_SECONDS",
    "FULL_AUDIO_ASR_CHUNK_SECONDS",
    "MIN_ASR_UPLOAD_CHUNK_SECONDS",
    "PrimaryTranscriberFactory",
    "ProgressCallback",
    "ProgressEvent",
    "TranscriberFactory",
    "TranscriptionEngine",
    "describe_backend_outcome",
]

PrimaryTranscriberFactory: TypeAlias = Callable[[], Transcriber]


class TranscriptionEngine:
    """Own top-level subtitle/audio orchestration and backend attribution."""

    def __init__(
        self,
        config: dict,
        *,
        primary_transcriber: Transcriber | None = None,
        primary_transcriber_factory: PrimaryTranscriberFactory | None = None,
        primary_backend: str | None = None,
        fallback_backend: str | None = None,
        fallback_transcriber_factory: TranscriberFactory | None = None,
    ) -> None:
        self.config = config
        asr_cfg = config.get("extract", {}).get("asr", {})
        self.primary_backend = primary_backend or str(asr_cfg.get("backend", "remote"))
        self.fallback_backend = (
            fallback_backend if fallback_backend is not None else asr_cfg.get("fallback_backend")
        )
        self._primary_transcriber = primary_transcriber
        self._primary_transcriber_factory = primary_transcriber_factory
        self._fallback_transcriber_factory = fallback_transcriber_factory
        if self.fallback_backend and fallback_transcriber_factory is None:
            raise ValueError(
                "TranscriptionEngine requires an injected fallback Transcriber factory "
                "when fallback_backend is configured"
            )

    def transcribe_workspace(
        self,
        ws: Workspace,
        metadata: VideoMeta,
        segments: Sequence[SegmentSpec],
        *,
        verbose: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[TranscriptSegment, ...]:
        """Transcribe current workspace subtitles or audio into transcript segments."""
        if verbose:
            typer.echo("Transcribing...")

        if ws.subtitle_path:
            subtitle_source = ws.load_subtitle_source() or "subtitle"
            return _transcribe_from_subtitles(
                ws.subtitle_path,
                segments,
                metadata,
                self.config,
                verbose,
                source=subtitle_source,
            )
        if ws.audio_path is None:
            raise ExtractionError("No subtitles or audio found in workspace")

        return self.transcribe_audio(
            ws.audio_path,
            segments,
            metadata,
            ws,
            verbose=verbose,
            progress_callback=progress_callback,
        )

    def transcribe_audio(
        self,
        audio_path: Path,
        segments: Sequence[SegmentSpec],
        metadata: VideoMeta,
        ws: Workspace,
        *,
        verbose: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[TranscriptSegment, ...]:
        """Transcribe audio via the configured primary/fallback providers."""
        transcriber = self._primary_transcriber
        if transcriber is None:
            if self._primary_transcriber_factory is None:
                raise ValueError("TranscriptionEngine requires a primary Transcriber Adapter")
            transcriber = self._primary_transcriber_factory()
            self._primary_transcriber = transcriber

        return _transcribe_from_audio(
            audio_path,
            segments,
            metadata,
            self.config,
            ws,
            verbose,
            transcriber=transcriber,
            primary_backend=self.primary_backend,
            fallback_backend=self.fallback_backend,
            fallback_transcriber_factory=self._fallback_transcriber_factory,
            progress_callback=progress_callback,
        )

    def backend_outcome(self, ws: Workspace) -> str:
        """Return the actual ASR backend usage recorded in checkpoint state."""
        return describe_backend_outcome(ws, default_backend=self.primary_backend)


def _transcribe_from_subtitles(
    sub_path: Path,
    segments: Sequence[SegmentSpec],
    metadata: VideoMeta,
    config: dict,
    verbose: bool,
    *,
    source: str = "subtitle",
) -> tuple[TranscriptSegment, ...]:
    """Assign subtitle entries to segments, or create segments from entries."""
    entries = parse_subtitle_file(sub_path)
    if verbose:
        typer.echo(f"  Parsed {len(entries)} subtitle entries")

    if segments:
        return _assign_entries_to_segments(entries, segments, source=source)

    from yt2notion.segment import _split_by_duration

    max_seg = config.get("output", {}).get("max_segment_seconds", 900)
    split_segs = _split_by_duration(entries, max_seg)
    return tuple(
        TranscriptSegment(
            title=seg.title,
            start_seconds=seg.start_seconds,
            end_seconds=seg.end_seconds,
            text=seg.text,
            source=source,
        )
        for seg in split_segs
    )


def _assign_entries_to_segments(
    entries: list[SubtitleEntry],
    segments: Sequence[SegmentSpec],
    *,
    source: str = "subtitle",
) -> tuple[TranscriptSegment, ...]:
    """Assign subtitle entries to segments by timestamp."""
    result: list[TranscriptSegment] = []
    for segment in segments:
        segment_entries = [
            entry
            for entry in entries
            if entry.start_seconds >= segment.start_seconds
            and entry.start_seconds < segment.end_seconds
        ]
        result.append(
            TranscriptSegment(
                title=segment.title,
                start_seconds=segment.start_seconds,
                end_seconds=segment.end_seconds,
                text=" ".join(entry.text for entry in segment_entries).strip(),
                source=source,
            )
        )
    return tuple(result)


def _transcribe_from_audio(
    audio_path: Path,
    segments: Sequence[SegmentSpec],
    metadata: VideoMeta,
    config: dict,
    ws: Workspace,
    verbose: bool,
    *,
    transcriber: Transcriber,
    primary_backend: str = "remote",
    fallback_backend: str | None = None,
    fallback_transcriber_factory: TranscriberFactory | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[TranscriptSegment, ...]:
    """Transcribe audio via ASR, optionally per segment."""
    language = metadata.language or None
    if segments:
        plan = build_segment_transcribe_plan(
            ws=ws,
            audio_path=audio_path,
            segments=segments,
            preferred_backend=primary_backend,
        )
    else:
        if verbose:
            typer.echo("  ASR on full audio (no pre-segmentation)...")
        plan = build_full_audio_transcribe_plan(
            ws=ws,
            audio_path=audio_path,
            metadata=metadata,
            config=config,
            transcriber=transcriber,
            preferred_backend=primary_backend,
        )

    state = load_or_create_transcribe_state(ws, plan, job_mode=primary_backend)
    execute_chunk_plan(
        ws=ws,
        audio_path=audio_path,
        plan=plan,
        state=state,
        config=config,
        primary_backend=primary_backend,
        transcriber=transcriber,
        fallback_backend=fallback_backend,
        fallback_transcriber_factory=fallback_transcriber_factory,
        language=language,
        verbose=verbose,
        progress_callback=progress_callback,
    )

    if segments:
        return _segment_transcripts_from_plan(ws, plan)

    entries = _merged_chunk_entries(ws, plan)
    if verbose:
        typer.echo(f"  {len(entries)} ASR segments returned")

    from yt2notion.segment import _split_by_duration

    max_seg = config.get("output", {}).get("max_segment_seconds", 900)
    split_segs = _split_by_duration(entries, max_seg)
    return tuple(
        TranscriptSegment(
            title=seg.title,
            start_seconds=seg.start_seconds,
            end_seconds=seg.end_seconds,
            text=seg.text,
            source="asr",
        )
        for seg in split_segs
    )


def _segment_transcripts_from_plan(
    ws: Workspace,
    plan: list[TranscribeChunk],
) -> tuple[TranscriptSegment, ...]:
    result: list[TranscriptSegment] = []
    for chunk in plan:
        payload = load_required_chunk_payload(ws, chunk.chunk_id)
        entries = entries_from_chunk_payload(payload)
        result.append(
            TranscriptSegment(
                title=chunk.title,
                start_seconds=chunk.start_seconds,
                end_seconds=chunk.end_seconds,
                text=" ".join(entry.text for entry in entries).strip(),
                source="asr",
            )
        )
    return tuple(result)


def _merged_chunk_entries(ws: Workspace, plan: list[TranscribeChunk]) -> list[SubtitleEntry]:
    merged: list[SubtitleEntry] = []
    for chunk in plan:
        payload = load_required_chunk_payload(ws, chunk.chunk_id)
        merged.extend(entries_from_chunk_payload(payload))
    return merged
