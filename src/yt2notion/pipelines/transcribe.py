"""Complete local media transcription product composition."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yt2notion.content_preparation import is_retries_exhausted
from yt2notion.media_source import AcquisitionError, AcquisitionRequest, acquire_media
from yt2notion.pipelines.shared import workspace_base
from yt2notion.runtime import RuntimeObserver
from yt2notion.transcript_artifacts import (
    MediaTranscribeResult,
    render_media_transcript_markdown,
    resolve_transcript_source,
)

if TYPE_CHECKING:
    from yt2notion.config import AppConfig
    from yt2notion.content_preparation import ContentPreparation
    from yt2notion.media_source import SourceProvider
    from yt2notion.pipelines.contracts import TranscribePipelineRequest
    from yt2notion.transcribe.engine import TranscriptionEngine
    from yt2notion.workspace import Workspace


def run_transcribe_pipeline(
    request: TranscribePipelineRequest,
    *,
    config: AppConfig,
    source_provider: SourceProvider,
    transcription_engine: TranscriptionEngine,
    preparation: ContentPreparation,
    observer: RuntimeObserver | None = None,
) -> MediaTranscribeResult:
    """Acquire captions or media and stop after local transcript artifacts."""
    runtime = observer or RuntimeObserver(
        workspace_base(config, request.workspace_dir),
        run_name="transcribe",
    )
    if observer is not None:
        return _run_transcribe_pipeline(
            request,
            config=config,
            source_provider=source_provider,
            transcription_engine=transcription_engine,
            preparation=preparation,
            observer=runtime,
        )
    with runtime.run():
        return _run_transcribe_pipeline(
            request,
            config=config,
            source_provider=source_provider,
            transcription_engine=transcription_engine,
            preparation=preparation,
            observer=runtime,
        )


def _run_transcribe_pipeline(
    request: TranscribePipelineRequest,
    *,
    config: AppConfig,
    source_provider: SourceProvider,
    transcription_engine: TranscriptionEngine,
    preparation: ContentPreparation,
    observer: RuntimeObserver,
) -> MediaTranscribeResult:
    workspace: Workspace | None = None
    current_step = "download"
    try:
        with observer.span("node", "acquire"):
            try:
                acquired = acquire_media(
                    source_provider,
                    AcquisitionRequest(
                        request.url,
                        workspace_base(config, request.workspace_dir),
                        keep_video=request.keep_video,
                    ),
                )
            except AcquisitionError as failure:
                workspace = failure.workspace
                observer.relocate(workspace.dir)
                raise failure.cause from failure
        workspace = acquired.workspace
        observer.relocate(workspace.dir)
        metadata = acquired.metadata
        if not request.keep_video:
            workspace.discard_video_artifacts()
        workspace.discard_transcribe_artifacts(audio_path=acquired.audio_path)
        workspace.clear_asr_fallback_used()

        current_step = "segment"
        with observer.span("node", "segment"):
            segments = preparation.segment(metadata, config, request.verbose)
            workspace.save_segments(segments)

        current_step = "transcribe"
        with observer.span("node", "transcribe"):
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
            timings_seconds=observer.timing_summary(("acquire", "segment", "transcribe")),
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
