"""Compatibility facade for the application and extracted cohesive modules."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from yt2notion.application import (
    PreparedContent,
    ProgressCallback,
    ProgressEvent,
    Yt2Notion,
    emit_progress,
)
from yt2notion.content_preparation import (
    ContentPreparation,
    is_long_content,
    is_retries_exhausted,
    review_transcripts,
    segment_content,
    should_cleanup_transcript,
    should_topic_segment,
)
from yt2notion.content_preparation import (
    render_prepared_output as _render_prepared_output,
)
from yt2notion.media_source import create_media_source
from yt2notion.models import create_summarizer  # noqa: F401 - compatibility patch point
from yt2notion.note_bundle import build_note_bundle  # noqa: F401 - compatibility patch point
from yt2notion.storage import create_storage
from yt2notion.topic_segment import segment_transcript  # noqa: F401 - compatibility patch point
from yt2notion.transcribe import create_transcription_engine
from yt2notion.transcribe.engine import (
    ASR_CHUNK_PADDING_SECONDS as ASR_CHUNK_PADDING_SECONDS,
)
from yt2notion.transcribe.engine import (
    FULL_AUDIO_ASR_CHUNK_SECONDS as FULL_AUDIO_ASR_CHUNK_SECONDS,
)
from yt2notion.transcribe.engine import (
    MIN_ASR_UPLOAD_CHUNK_SECONDS as MIN_ASR_UPLOAD_CHUNK_SECONDS,
)
from yt2notion.transcript_artifacts import render_reviewed_transcript_markdown

if TYPE_CHECKING:
    from yt2notion.config import AppConfig
    from yt2notion.models.base import (
        VideoMeta,
    )
    from yt2notion.process import SubtitleEntry
    from yt2notion.transcribe.base import Transcriber
    from yt2notion.workspace import Workspace


class _PipelineCompatibilityTranscriptionEngine:
    """TranscriptionEngine adapter preserving `_step_transcribe` patch points."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.raw_config = {
            "extract": config.extract,
            "model": config.model,
            "storage": config.storage,
            "credit": config.credit,
            "output": config.output,
        }

    def transcribe_workspace(
        self,
        ws: Workspace,
        metadata: VideoMeta,
        segments: list[dict],
        *,
        verbose: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> list[dict]:
        return _step_transcribe(
            ws,
            metadata,
            segments,
            self.raw_config,
            verbose,
            progress_callback=progress_callback,
        )


def run_pipeline(
    url: str,
    config: AppConfig,
    *,
    verbose: bool = False,
    dry_run: bool = False,
    resume_from: str | None = None,
    workspace_dir: str | None = None,
    mode: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> str:
    """Compatibility facade preserving historical pipeline patch points."""
    app = _PipelineCompatibilityApplication(
        config,
        storage_factory=lambda raw_config: create_storage(raw_config),
    )
    return app.process(
        url,
        verbose=verbose,
        dry_run=dry_run,
        resume_from=resume_from,
        workspace_dir=workspace_dir,
        mode=mode,
        progress_callback=progress_callback,
    )


def prepare_content(
    url: str,
    config: AppConfig,
    *,
    verbose: bool = False,
    resume_from: str | None = None,
    workspace_dir: str | None = None,
    mode: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> PreparedContent:
    """Compatibility facade for Yt2Notion.prepare()."""
    return Yt2Notion(
        config,
        media_source=create_media_source(_raw_config(config), verbose=verbose),
        transcription_engine=_PipelineCompatibilityTranscriptionEngine(config),
        content_preparation=_compatibility_content_preparation(),
    ).prepare(
        url,
        verbose=verbose,
        resume_from=resume_from,
        workspace_dir=workspace_dir,
        mode=mode,
        progress_callback=progress_callback,
    )


# === Step implementations ===


class _PipelineCompatibilityApplication(Yt2Notion):
    """Route legacy process calls through the patchable prepare facade."""

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
        return prepare_content(
            url,
            self.config,
            verbose=verbose,
            resume_from=resume_from,
            workspace_dir=workspace_dir,
            mode=mode,
            progress_callback=progress_callback,
        )


def _compatibility_content_preparation() -> ContentPreparation:
    return ContentPreparation(
        segmenter=lambda metadata, config, verbose: _step_segment(metadata, config, verbose),
        reviewer=lambda transcripts, metadata, config, workspace, verbose: _step_review(
            transcripts, metadata, config, workspace, verbose
        ),
        topic_segmenter=lambda transcripts, metadata, config, max_seconds: segment_transcript(
            transcripts, metadata, config, max_seconds
        ),
        summarizer_factory=lambda config: create_summarizer(config),
        bundle_builder=lambda transcripts, metadata, summarizer: build_note_bundle(
            transcripts, metadata, summarizer
        ),
    )


def _raw_config(config: AppConfig) -> dict:
    return {
        "extract": config.extract,
        "model": config.model,
        "storage": config.storage,
        "credit": config.credit,
        "output": config.output,
    }


def _emit_progress(
    progress_callback: ProgressCallback | None,
    step: str,
    event: ProgressEvent,
    message: str | None = None,
) -> None:
    emit_progress(progress_callback, step, event, message)


def _step_segment(metadata: VideoMeta, config: dict, verbose: bool) -> list[dict]:
    """Compatibility wrapper for content preparation segmentation."""
    return segment_content(metadata, config, verbose)


def _step_transcribe(
    ws: Workspace,
    metadata: VideoMeta,
    segments: list[dict],
    config: dict,
    verbose: bool,
    progress_callback: ProgressCallback | None = None,
) -> list[dict]:
    """Compatibility helper for the canonical TranscriptionEngine."""
    return create_transcription_engine(config).transcribe_workspace(
        ws,
        metadata,
        segments,
        verbose=verbose,
        progress_callback=progress_callback,
    )


def _transcribe_from_subtitles(
    sub_path: Path,
    segments: list[dict],
    metadata: VideoMeta,
    config: dict,
    verbose: bool,
    *,
    source: str = "subtitle",
) -> list[dict]:
    """Compatibility wrapper around TranscriptionEngine subtitle assignment."""
    from yt2notion.transcribe.engine import transcribe_from_subtitles

    return transcribe_from_subtitles(
        sub_path,
        segments,
        metadata,
        config,
        verbose,
        source=source,
    )


def _transcribe_from_audio(
    audio_path: Path,
    segments: list[dict],
    metadata: VideoMeta,
    config: dict,
    ws: Workspace,
    verbose: bool,
    *,
    transcriber: Transcriber | None = None,
    primary_backend: str = "remote",
    fallback_backend: str | None = None,
    fallback_transcriber_factory: Callable[[], Transcriber | None] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[dict]:
    """Compatibility wrapper around TranscriptionEngine audio transcription."""
    from yt2notion.transcribe.engine import TranscriptionEngine

    engine = (
        create_transcription_engine(config)
        if transcriber is None
        else TranscriptionEngine(
            config,
            primary_transcriber=transcriber,
            primary_backend=primary_backend,
            fallback_backend=fallback_backend,
            fallback_transcriber_factory=fallback_transcriber_factory,
        )
    )
    return engine.transcribe_audio(
        audio_path,
        segments,
        metadata,
        ws,
        verbose=verbose,
        progress_callback=progress_callback,
    )


def _transcribe_full_audio_entries(
    audio_path: Path,
    metadata: VideoMeta,
    config: dict,
    transcriber: Transcriber,
    *,
    language: str | None,
    verbose: bool,
) -> list[SubtitleEntry]:
    """Compatibility wrapper around TranscriptionEngine full-audio helper."""
    from yt2notion.transcribe.engine import transcribe_full_audio_entries

    return transcribe_full_audio_entries(
        audio_path,
        metadata,
        config,
        transcriber,
        language=language,
        verbose=verbose,
    )


def _rebase_chunk_entries(entries: list[SubtitleEntry], chunk_spec: dict) -> list[SubtitleEntry]:
    """Compatibility wrapper around TranscriptionEngine timestamp rebasing."""
    from yt2notion.transcribe.engine import rebase_chunk_entries

    return rebase_chunk_entries(entries, chunk_spec)


def _should_cleanup_transcript(transcripts: list[dict]) -> bool:
    """Compatibility wrapper for transcript cleanup policy."""
    return should_cleanup_transcript(transcripts)


def _should_topic_segment(transcripts: list[dict]) -> bool:
    """Compatibility wrapper for topic segmentation policy."""
    return should_topic_segment(transcripts)


def _step_review(
    transcripts: list[dict],
    metadata: VideoMeta,
    config: dict,
    ws: Workspace,
    verbose: bool,
) -> list[dict]:
    """Compatibility wrapper for transcript review."""
    return review_transcripts(transcripts, metadata, config, ws, verbose)


def _is_long_content(metadata: VideoMeta, transcripts: list[dict], config: dict) -> bool:
    """Compatibility wrapper for long-content classification."""
    return is_long_content(metadata, transcripts, config)


def render_prepared_output(prepared: PreparedContent, config: AppConfig) -> str:
    """Compatibility wrapper for prepared-content rendering."""
    return _render_prepared_output(prepared, config)


def render_transcript_markdown(metadata: VideoMeta, transcript_segments: list[dict]) -> str:
    """Compatibility wrapper for the legacy reviewed-transcript renderer."""
    return render_reviewed_transcript_markdown(metadata, transcript_segments)


def _is_retries_exhausted(exc: Exception) -> bool:
    """Compatibility wrapper for retry-exhaustion detection."""
    return is_retries_exhausted(exc)
