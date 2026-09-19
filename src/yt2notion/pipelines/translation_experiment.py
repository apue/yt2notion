"""Complete translation-experiment product composition."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yt2notion.pipelines.shared import workspace_base
from yt2notion.pipelines.transcribe import run_transcribe_pipeline
from yt2notion.runtime import RuntimeObserver

if TYPE_CHECKING:
    from yt2notion.config import AppConfig
    from yt2notion.content_preparation import ContentPreparation
    from yt2notion.media_source import SourceProvider
    from yt2notion.transcribe.engine import TranscriptionEngine
    from yt2notion.translation_experiment import (
        TranslationExperimentResult,
        TranslationExperimentRunner,
    )


def run_translation_experiment_pipeline(
    url: str,
    *,
    config: AppConfig,
    source_provider: SourceProvider,
    transcription_engine: TranscriptionEngine,
    preparation: ContentPreparation,
    runner: TranslationExperimentRunner,
    workspace_dir: str | None = None,
    keep_video: bool = False,
    verbose: bool = False,
) -> TranslationExperimentResult:
    """Transcribe and build a local translation experiment as one product run."""
    observer = RuntimeObserver(
        workspace_base(config, workspace_dir),
        run_name="translation_experiment",
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
        transcripts = transcription.workspace.load_transcripts()
        if transcripts is None:
            raise ValueError("translation experiment requires transcripts.json")
        with observer.span("node", "translation_experiment"):
            return runner.run(
                transcription.metadata,
                transcripts,
                transcription.workspace,
            )
