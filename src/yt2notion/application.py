"""Explicit yt2notion application use cases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeAlias

import typer

from yt2notion.content_preparation import (
    ContentPreparation,
    is_retries_exhausted,
    render_prepared_output,
)
from yt2notion.media_source import (
    MediaAcquireRequest,
    MediaAcquisitionError,
    MediaSource,
    create_media_source,
)
from yt2notion.storage import create_storage
from yt2notion.timing import StageTimer
from yt2notion.transcribe import create_transcription_engine
from yt2notion.transcript_artifacts import (
    MediaTranscribeResult,
    render_media_transcript_markdown,
    resolve_transcript_source,
)
from yt2notion.workspace import STEPS, Workspace

if TYPE_CHECKING:
    from yt2notion.config import AppConfig
    from yt2notion.models.base import NoteBundle, VideoMeta
    from yt2notion.storage.base import Storage
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


def emit_progress(
    progress_callback: ProgressCallback | None,
    step: str,
    event: ProgressEvent,
    message: str | None = None,
) -> None:
    """Emit a typed progress event when a callback is configured."""
    if progress_callback is not None:
        progress_callback(step, event, message)


@dataclass
class PreparedContent:
    """Bundle-only application output before storage publish."""

    metadata: VideoMeta
    note_bundle: NoteBundle
    workspace: Workspace
    is_long: bool


class Yt2Notion:
    """Application interface for the supported use cases."""

    def __init__(
        self,
        config: AppConfig,
        *,
        media_source: MediaSource | None = None,
        transcription_engine: TranscriptionEngine | None = None,
        content_preparation: ContentPreparation | None = None,
        storage_factory: Callable[[dict], Storage] = create_storage,
        translation_experiment_runner: TranslationExperimentRunner | None = None,
    ) -> None:
        self.config = config
        self.raw_config = {
            "extract": config.extract,
            "model": config.model,
            "storage": config.storage,
            "credit": config.credit,
            "output": config.output,
        }
        self.media_source = media_source
        self.transcription_engine = transcription_engine or create_transcription_engine(
            self.raw_config
        )
        self.content_preparation = content_preparation or ContentPreparation()
        self.storage_factory = storage_factory
        self.translation_experiment_runner = translation_experiment_runner

    def prepare(
        self,
        url: str,
        *,
        verbose: bool = False,
        resume_from: str | None = None,
        workspace_dir: str | None = None,
        mode: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> PreparedContent:
        """Prepare source/A/B content without publishing."""
        if mode not in {None, "summary"}:
            raise ValueError("source/A/B bundle output supports summary mode only")

        start_idx = 0
        if resume_from:
            if resume_from not in STEPS:
                raise ValueError(f"Unknown step: {resume_from!r}. Valid: {', '.join(STEPS)}")
            start_idx = STEPS.index(resume_from)

        ws: Workspace | None = None
        current_step = "download"
        try:
            if start_idx <= 0:
                emit_progress(progress_callback, "download", "started")
                source = self._media_source(verbose=verbose)
                try:
                    acquired = source.acquire(
                        MediaAcquireRequest(
                            url=url,
                            workspace_base_dir=self._workspace_base(workspace_dir),
                        )
                    )
                except MediaAcquisitionError as failure:
                    ws = failure.workspace
                    raise failure.cause from failure
                metadata = acquired.metadata
                ws = acquired.workspace
                emit_progress(progress_callback, "download", "completed")
            else:
                ws, metadata = self._resume_workspace(url, workspace_dir, verbose=verbose)

            current_step = "segment"
            if start_idx <= 1:
                emit_progress(progress_callback, "segment", "started")
                segments = self.content_preparation.segment(metadata, self.raw_config, verbose)
                ws.save_segments(segments)
                emit_progress(progress_callback, "segment", "completed")
            else:
                segments = ws.load_segments()
                if segments is None:
                    raise ValueError("Cannot resume: no segments.json in workspace")

            current_step = "transcribe"
            if start_idx <= 2:
                if start_idx < 2:
                    ws.discard_transcribe_artifacts(audio_path=ws.audio_path)
                    ws.clear_asr_fallback_used()
                elif (
                    ws.load_transcribe_plan() is None
                    and ws.load_transcribe_state() is None
                    and not (ws.dir / "transcribe_chunks").exists()
                ):
                    ws.clear_asr_fallback_used()
                emit_progress(progress_callback, "transcribe", "started")
                transcripts = self.transcription_engine.transcribe_workspace(
                    ws,
                    metadata,
                    segments,
                    verbose=verbose,
                    progress_callback=progress_callback,
                )
                ws.save_transcripts(transcripts)
                emit_progress(progress_callback, "transcribe", "completed")
            else:
                transcripts = ws.load_transcripts()
                if transcripts is None:
                    raise ValueError("Cannot resume: no transcripts.json in workspace")

            if start_idx <= 2 and self.content_preparation.should_topic_segment(transcripts):
                max_seg_sec = self.raw_config.get("output", {}).get("max_segment_seconds", 600)
                original_count = len(transcripts)
                transcripts = self.content_preparation.topic_segment(
                    transcripts,
                    metadata,
                    self.raw_config,
                    max_seg_sec,
                )
                if len(transcripts) != original_count:
                    ws.save_transcripts(transcripts)
                    if verbose:
                        typer.echo(
                            f"  Topic segmentation: {original_count} -> {len(transcripts)} segments"
                        )
            elif verbose:
                typer.echo("  Skipping topic segmentation for manual subtitle transcript")

            current_step = "review"
            if self.content_preparation.should_cleanup(transcripts):
                if start_idx <= 3:
                    emit_progress(progress_callback, "review", "started")
                    reviewed = self.content_preparation.review(
                        transcripts, metadata, self.raw_config, ws, verbose
                    )
                    ws.save_reviewed(reviewed)
                    emit_progress(progress_callback, "review", "completed")
                else:
                    reviewed = ws.load_reviewed()
                    if reviewed is None:
                        raise ValueError("Cannot resume: no reviewed.json in workspace")
            else:
                reviewed = transcripts
                if verbose:
                    typer.echo("Skipping transcript cleanup for manual subtitle transcript")

            current_step = "summarize"
            emit_progress(progress_callback, "summarize", "started")
            if verbose:
                typer.echo("Summarizing source/A/B note bundle...")
            note_bundle = self.content_preparation.summarize(reviewed, metadata, self.raw_config)
            ws.save_note_bundle(note_bundle)
            ws.clear_failure()
            emit_progress(progress_callback, "summarize", "completed")

            return PreparedContent(
                metadata=metadata,
                note_bundle=note_bundle,
                workspace=ws,
                is_long=self.content_preparation.is_long(metadata, transcripts, self.raw_config),
            )
        except Exception as exc:
            if ws is not None:
                ws.save_failure(
                    url,
                    current_step,
                    exc,
                    retries_exhausted=is_retries_exhausted(exc),
                )
            raise

    def process(
        self,
        url: str,
        *,
        verbose: bool = False,
        dry_run: bool = False,
        resume_from: str | None = None,
        workspace_dir: str | None = None,
        mode: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> str:
        """Prepare and explicitly publish through the configured storage backend."""
        prepared = self.prepare(
            url,
            verbose=verbose,
            resume_from=resume_from,
            workspace_dir=workspace_dir,
            mode=mode,
            progress_callback=progress_callback,
        )

        if dry_run:
            output = render_prepared_output(prepared, self.config)
            typer.echo(output)
            return output

        if verbose:
            typer.echo("Publishing to Obsidian...")
        storage = self.storage_factory(self.raw_config)
        emit_progress(progress_callback, "publish", "started")
        result_url = storage.save_note_bundle(prepared.note_bundle, prepared.metadata)
        emit_progress(progress_callback, "publish", "completed")
        if verbose:
            typer.echo(f"  Published: {result_url}")
        prepared.workspace.clear_failure()
        return result_url

    def transcribe(
        self,
        url: str,
        *,
        workspace_dir: str | None = None,
        keep_video: bool = True,
        verbose: bool = False,
    ) -> MediaTranscribeResult:
        """Acquire captions or media and stop after local transcript artifacts."""
        source = self._media_source(verbose=verbose)
        timer = StageTimer()
        ws: Workspace | None = None
        current_step = "download"
        try:
            with timer.measure("acquire"):
                try:
                    acquired = source.acquire(
                        MediaAcquireRequest(
                            url=url,
                            workspace_base_dir=self._workspace_base(workspace_dir),
                            keep_video=keep_video,
                        )
                    )
                except MediaAcquisitionError as failure:
                    ws = failure.workspace
                    raise failure.cause from failure
            ws = acquired.workspace
            metadata = acquired.metadata
            if not keep_video:
                ws.discard_video_artifacts()
            ws.discard_transcribe_artifacts(audio_path=acquired.audio_path)
            ws.clear_asr_fallback_used()

            current_step = "segment"
            with timer.measure("segment"):
                segments = self.content_preparation.segment(metadata, self.raw_config, verbose)
                ws.save_segments(segments)

            current_step = "transcribe"
            with timer.measure("transcribe"):
                transcripts = self.transcription_engine.transcribe_workspace(
                    ws,
                    metadata,
                    segments,
                    verbose=verbose,
                )
                ws.save_transcripts(transcripts)

            backend = self.transcription_engine.backend_outcome(ws)
            transcript_source = resolve_transcript_source(transcripts, backend)
            markdown_path = ws.dir / "transcript.md"
            markdown_path.write_text(
                render_media_transcript_markdown(metadata, transcripts, transcript_source),
                encoding="utf-8",
            )
            ws.clear_failure()
            return MediaTranscribeResult(
                metadata=metadata,
                workspace=ws,
                video_path=acquired.video_path,
                audio_path=acquired.audio_path,
                transcripts_path=ws.dir / "transcripts.json",
                transcript_markdown_path=markdown_path,
                timings_seconds=timer.finish(),
            )
        except Exception as exc:
            if ws is not None:
                ws.save_failure(
                    url,
                    current_step,
                    exc,
                    retries_exhausted=is_retries_exhausted(exc),
                )
            raise

    def run_translation_experiment(
        self,
        url: str,
        *,
        workspace_dir: str | None = None,
        keep_video: bool = False,
        verbose: bool = False,
    ) -> TranslationExperimentResult:
        """Acquire a transcript and generate a local blind translation experiment."""
        transcription = self.transcribe(
            url,
            workspace_dir=workspace_dir,
            keep_video=keep_video,
            verbose=verbose,
        )
        transcripts = transcription.workspace.load_transcripts()
        if transcripts is None:
            raise ValueError("translation experiment requires transcripts.json")

        if self.translation_experiment_runner is None:
            from yt2notion.translation_experiment import create_translation_experiment_runner

            runner = create_translation_experiment_runner(self.raw_config)
        else:
            runner = self.translation_experiment_runner
        return runner.run(transcription.metadata, transcripts, transcription.workspace)

    def _workspace_base(self, workspace_dir: str | None) -> Path:
        workspace_base = workspace_dir or self.config.workspace.get("base_dir", "./workspace")
        return Path(workspace_base).expanduser()

    def _media_source(self, *, verbose: bool) -> MediaSource:
        if self.media_source is not None:
            return self.media_source
        return create_media_source(self.raw_config, verbose=verbose)

    def _resume_workspace(
        self,
        url: str,
        workspace_dir: str | None,
        *,
        verbose: bool,
    ) -> tuple[Workspace, VideoMeta]:
        from yt2notion.extract import extract_metadata

        base_dir = self._workspace_base(workspace_dir)
        if workspace_dir:
            ws_path = Path(workspace_dir)
            if (ws_path / "metadata.json").exists():
                ws = Workspace(ws_path.parent, ws_path.name)
            else:
                raise ValueError(f"No metadata.json found in {workspace_dir}")
        else:
            metadata = extract_metadata(url)
            ws = Workspace(base_dir, metadata.video_id)

        metadata = ws.load_metadata()
        if metadata is None:
            raise ValueError("Cannot resume: no metadata.json in workspace")
        if verbose:
            typer.echo(f"Resuming from step for: {metadata.title}")
        return ws, metadata


def create_yt2notion(config: AppConfig, *, verbose: bool = False) -> Yt2Notion:
    """Composition root for the application interface."""
    raw_config = {
        "extract": config.extract,
        "model": config.model,
        "storage": config.storage,
        "credit": config.credit,
        "output": config.output,
    }
    return Yt2Notion(
        config,
        media_source=create_media_source(raw_config, verbose=verbose),
        transcription_engine=create_transcription_engine(raw_config),
    )
