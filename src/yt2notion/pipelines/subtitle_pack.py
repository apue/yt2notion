"""Complete bilingual subtitle-package product composition."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yt2notion.pipelines.shared import workspace_base
from yt2notion.pipelines.transcribe import run_transcribe_pipeline
from yt2notion.runtime import RuntimeObserver

if TYPE_CHECKING:
    from yt2notion.config import AppConfig
    from yt2notion.content_preparation import ContentPreparation
    from yt2notion.media_source import SourceProvider
    from yt2notion.subtitle_pack import SubtitlePackResult, SubtitlePackService
    from yt2notion.transcribe.engine import TranscriptionEngine


def run_subtitle_pack_pipeline(
    url: str,
    *,
    config: AppConfig,
    source_provider: SourceProvider,
    transcription_engine: TranscriptionEngine,
    preparation: ContentPreparation,
    service: SubtitlePackService,
    workspace_dir: str | None = None,
    keep_video: bool = False,
    verbose: bool = False,
) -> SubtitlePackResult:
    """Transcribe and build a local subtitle package as one product run."""
    observer = RuntimeObserver(
        workspace_base(config, workspace_dir),
        run_name="subtitle_pack",
    )
    with observer.run():
        transcription = run_transcribe_pipeline(
            url,
            config=config,
            source_provider=source_provider,
            transcription_engine=transcription_engine,
            preparation=preparation,
            workspace_dir=workspace_dir,
            keep_video=keep_video,
            verbose=verbose,
            observer=observer,
        )
        with observer.span("node", "subtitle_pack"):
            return service.run(transcription, observer=observer)
