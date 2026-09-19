"""Readable typed Python composition for yt2notion product flows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeAlias

import typer

from yt2notion.content_preparation import is_retries_exhausted
from yt2notion.media_source import AcquisitionError, AcquisitionRequest, acquire_media
from yt2notion.timing import StageTimer
from yt2notion.transcript_artifacts import (
    MediaTranscribeResult,
    render_media_transcript_markdown,
    resolve_transcript_source,
)
from yt2notion.workspace import STEPS, Workspace

if TYPE_CHECKING:
    from yt2notion.config import AppConfig
    from yt2notion.content_preparation import ContentPreparation
    from yt2notion.media_source import SourceProvider
    from yt2notion.models.base import NoteBundle, VideoMeta
    from yt2notion.subtitle_pack import SubtitlePackResult, SubtitlePackService
    from yt2notion.transcribe.engine import TranscriptionEngine
    from yt2notion.translation_experiment import (
        TranslationExperimentResult,
        TranslationExperimentRunner,
    )

ProgressEvent: TypeAlias = Literal[
    "started",
    "completed",
    "skipped",
    "failed",
    "chunk_started",
    "chunk_completed",
    "hourly_wait",
    "daily_fallback_switch",
]
ProgressCallback: TypeAlias = Callable[[str, ProgressEvent, str | None], None]


@dataclass(frozen=True)
class NotePipelineRequest:
    """Inputs controlling local note preparation and resume behavior."""

    url: str
    workspace_dir: str | None = None
    resume_from: str | None = None
    mode: str | None = None
    verbose: bool = False


@dataclass(frozen=True)
class TranscribePipelineRequest:
    """Inputs controlling local transcript artifact creation."""

    url: str
    workspace_dir: str | None = None
    keep_video: bool = True
    verbose: bool = False


@dataclass
class PreparedContent:
    """Bundle-only pipeline output before explicit storage publish."""

    metadata: VideoMeta
    note_bundle: NoteBundle
    workspace: Workspace
    is_long: bool


def emit_progress(
    progress_callback: ProgressCallback | None,
    step: str,
    event: ProgressEvent,
    message: str | None = None,
) -> None:
    """Emit a typed progress event when a callback is configured."""
    if progress_callback is not None:
        progress_callback(step, event, message)


def run_note_pipeline(
    request: NotePipelineRequest,
    *,
    config: AppConfig,
    source_provider: SourceProvider,
    transcription_engine: TranscriptionEngine,
    preparation: ContentPreparation,
    progress_callback: ProgressCallback | None = None,
) -> PreparedContent:
    """Acquire, transcribe, review, and compose a local source/A/B note bundle."""
    if request.mode not in {None, "summary"}:
        raise ValueError("source/A/B bundle output supports summary mode only")

    start_idx = _resume_index(request.resume_from)
    workspace: Workspace | None = None
    current_step = "download"
    try:
        if start_idx <= 0:
            emit_progress(progress_callback, "download", "started")
            try:
                acquired = acquire_media(
                    source_provider,
                    AcquisitionRequest(
                        request.url,
                        _workspace_base(config, request.workspace_dir),
                    ),
                )
            except AcquisitionError as failure:
                workspace = failure.workspace
                raise failure.cause from failure
            metadata = acquired.metadata
            workspace = acquired.workspace
            emit_progress(progress_callback, "download", "completed")
        else:
            workspace, metadata = _resume_workspace(
                request.url,
                request.workspace_dir,
                config=config,
                verbose=request.verbose,
            )

        current_step = "segment"
        if start_idx <= 1:
            emit_progress(progress_callback, "segment", "started")
            segments = preparation.segment(metadata, config, request.verbose)
            workspace.save_segments(segments)
            emit_progress(progress_callback, "segment", "completed")
        else:
            segments = workspace.load_segments()
            if segments is None:
                raise ValueError("Cannot resume: no segments.json in workspace")

        current_step = "transcribe"
        if start_idx <= 2:
            if start_idx < 2:
                workspace.discard_transcribe_artifacts(audio_path=workspace.audio_path)
                workspace.clear_asr_fallback_used()
            elif (
                workspace.load_transcribe_plan() is None
                and workspace.load_transcribe_state() is None
                and not (workspace.dir / "transcribe_chunks").exists()
            ):
                workspace.clear_asr_fallback_used()
            emit_progress(progress_callback, "transcribe", "started")
            transcripts = transcription_engine.transcribe_workspace(
                workspace,
                metadata,
                segments,
                verbose=request.verbose,
                progress_callback=progress_callback,
            )
            workspace.save_transcripts(transcripts)
            emit_progress(progress_callback, "transcribe", "completed")
        else:
            transcripts = workspace.load_transcripts()
            if transcripts is None:
                raise ValueError("Cannot resume: no transcripts.json in workspace")

        if start_idx <= 2 and preparation.should_topic_segment(transcripts):
            max_segment_seconds = config.output.get("max_segment_seconds", 600)
            original_count = len(transcripts)
            transcripts = preparation.topic_segment(
                transcripts,
                metadata,
                config,
                max_segment_seconds,
            )
            if len(transcripts) != original_count:
                workspace.save_transcripts(transcripts)
                if request.verbose:
                    typer.echo(
                        f"  Topic segmentation: {original_count} -> {len(transcripts)} segments"
                    )
        elif request.verbose:
            typer.echo("  Skipping topic segmentation for manual subtitle transcript")

        current_step = "review"
        if preparation.should_cleanup(transcripts):
            if start_idx <= 3:
                emit_progress(progress_callback, "review", "started")
                reviewed = preparation.review(
                    transcripts,
                    metadata,
                    config,
                    workspace,
                    request.verbose,
                )
                workspace.save_reviewed(reviewed)
                emit_progress(progress_callback, "review", "completed")
            else:
                reviewed = workspace.load_reviewed()
                if reviewed is None:
                    raise ValueError("Cannot resume: no reviewed.json in workspace")
        else:
            reviewed = transcripts
            if request.verbose:
                typer.echo("Skipping transcript cleanup for manual subtitle transcript")

        current_step = "summarize"
        emit_progress(progress_callback, "summarize", "started")
        if request.verbose:
            typer.echo("Summarizing source/A/B note bundle...")
        note_bundle = preparation.summarize(reviewed, metadata, config)
        workspace.save_note_bundle(note_bundle)
        workspace.clear_failure()
        emit_progress(progress_callback, "summarize", "completed")
        return PreparedContent(
            metadata=metadata,
            note_bundle=note_bundle,
            workspace=workspace,
            is_long=preparation.is_long(metadata, transcripts, config),
        )
    except Exception as exc:
        if workspace is not None:
            workspace.save_failure(
                request.url,
                current_step,
                exc,
                retries_exhausted=is_retries_exhausted(exc),
            )
        raise


def run_transcribe_pipeline(
    request: TranscribePipelineRequest,
    *,
    config: AppConfig,
    source_provider: SourceProvider,
    transcription_engine: TranscriptionEngine,
    preparation: ContentPreparation,
) -> MediaTranscribeResult:
    """Acquire captions or media and stop after local transcript artifacts."""
    timer = StageTimer()
    workspace: Workspace | None = None
    current_step = "download"
    try:
        with timer.measure("acquire"):
            try:
                acquired = acquire_media(
                    source_provider,
                    AcquisitionRequest(
                        request.url,
                        _workspace_base(config, request.workspace_dir),
                        keep_video=request.keep_video,
                    ),
                )
            except AcquisitionError as failure:
                workspace = failure.workspace
                raise failure.cause from failure
        workspace = acquired.workspace
        metadata = acquired.metadata
        if not request.keep_video:
            workspace.discard_video_artifacts()
        workspace.discard_transcribe_artifacts(audio_path=acquired.audio_path)
        workspace.clear_asr_fallback_used()

        current_step = "segment"
        with timer.measure("segment"):
            segments = preparation.segment(metadata, config, request.verbose)
            workspace.save_segments(segments)

        current_step = "transcribe"
        with timer.measure("transcribe"):
            transcripts = transcription_engine.transcribe_workspace(
                workspace,
                metadata,
                segments,
                verbose=request.verbose,
            )
            workspace.save_transcripts(transcripts)

        backend = transcription_engine.backend_outcome(workspace)
        transcript_source = resolve_transcript_source(transcripts, backend)
        markdown_path = workspace.dir / "transcript.md"
        markdown_path.write_text(
            render_media_transcript_markdown(metadata, transcripts, transcript_source),
            encoding="utf-8",
        )
        workspace.clear_failure()
        return MediaTranscribeResult(
            metadata=metadata,
            workspace=workspace,
            video_path=acquired.video_path,
            audio_path=acquired.audio_path,
            transcripts_path=workspace.dir / "transcripts.json",
            transcript_markdown_path=markdown_path,
            timings_seconds=timer.finish(),
        )
    except Exception as exc:
        if workspace is not None:
            workspace.save_failure(
                request.url,
                current_step,
                exc,
                retries_exhausted=is_retries_exhausted(exc),
            )
        raise


def run_translation_experiment_pipeline(
    transcription: MediaTranscribeResult,
    runner: TranslationExperimentRunner,
) -> TranslationExperimentResult:
    """Build a local translation experiment from the typed transcript artifact."""
    transcripts = transcription.workspace.load_transcripts()
    if transcripts is None:
        raise ValueError("translation experiment requires transcripts.json")
    return runner.run(transcription.metadata, transcripts, transcription.workspace)


def run_subtitle_pack_pipeline(
    transcription: MediaTranscribeResult,
    service: SubtitlePackService,
) -> SubtitlePackResult:
    """Build a local bilingual subtitle package without a storage dependency."""
    return service.run(transcription)


def _resume_index(resume_from: str | None) -> int:
    if resume_from is None:
        return 0
    if resume_from not in STEPS:
        raise ValueError(f"Unknown step: {resume_from!r}. Valid: {', '.join(STEPS)}")
    return STEPS.index(resume_from)


def _workspace_base(config: AppConfig, workspace_dir: str | None) -> Path:
    workspace_base = workspace_dir or config.workspace.get("base_dir", "./workspace")
    return Path(workspace_base).expanduser()


def _resume_workspace(
    url: str,
    workspace_dir: str | None,
    *,
    config: AppConfig,
    verbose: bool,
) -> tuple[Workspace, VideoMeta]:
    from yt2notion.extract import extract_metadata

    base_dir = _workspace_base(config, workspace_dir)
    if workspace_dir:
        workspace_path = Path(workspace_dir)
        if (workspace_path / "metadata.json").exists():
            workspace = Workspace(workspace_path.parent, workspace_path.name)
        else:
            raise ValueError(f"No metadata.json found in {workspace_dir}")
    else:
        metadata = extract_metadata(url)
        workspace = Workspace(base_dir, metadata.video_id)

    metadata = workspace.load_metadata()
    if metadata is None:
        raise ValueError("Cannot resume: no metadata.json in workspace")
    if verbose:
        typer.echo(f"Resuming from step for: {metadata.title}")
    return workspace, metadata
