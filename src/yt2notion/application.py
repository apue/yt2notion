"""Application facade and dependency composition for typed product pipelines."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import typer

from yt2notion.content_preparation import ContentPreparation, render_prepared_output
from yt2notion.media_source import SourceProvider, create_source_provider
from yt2notion.pipelines import (
    NotePipelineRequest,
    PreparedContent,
    ProgressCallback,
    TranscribePipelineRequest,
    emit_progress,
    run_note_pipeline,
    run_subtitle_pack_pipeline,
    run_transcribe_pipeline,
    run_translation_experiment_pipeline,
)
from yt2notion.storage import create_storage
from yt2notion.transcribe import create_transcription_engine

if TYPE_CHECKING:
    from yt2notion.config import AppConfig
    from yt2notion.storage.base import Storage
    from yt2notion.subtitle_pack import SubtitlePackResult, SubtitlePackService
    from yt2notion.transcribe.engine import TranscriptionEngine
    from yt2notion.transcript_artifacts import MediaTranscribeResult
    from yt2notion.translation_experiment import (
        TranslationExperimentResult,
        TranslationExperimentRunner,
    )


class Yt2Notion:
    """Thin application interface that assembles and invokes typed pipelines."""

    def __init__(
        self,
        config: AppConfig,
        *,
        source_provider: SourceProvider | None = None,
        transcription_engine: TranscriptionEngine | None = None,
        content_preparation: ContentPreparation | None = None,
        storage_factory: Callable[[dict], Storage] = create_storage,
        translation_experiment_runner: TranslationExperimentRunner | None = None,
        subtitle_pack_service: SubtitlePackService | None = None,
    ) -> None:
        self.config = config
        self.raw_config = {
            "extract": config.extract,
            "model": config.model,
            "storage": config.storage,
            "credit": config.credit,
            "output": config.output,
        }
        self.source_provider = source_provider
        self.transcription_engine = transcription_engine or create_transcription_engine(
            self.raw_config
        )
        self.content_preparation = content_preparation or ContentPreparation()
        self.storage_factory = storage_factory
        self.translation_experiment_runner = translation_experiment_runner
        self.subtitle_pack_service = subtitle_pack_service

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
        """Prepare source/A/B content locally without publishing."""
        return run_note_pipeline(
            NotePipelineRequest(
                url=url,
                workspace_dir=workspace_dir,
                resume_from=resume_from,
                mode=mode,
                verbose=verbose,
            ),
            config=self.config,
            source_provider=self._source_provider(verbose=verbose),
            transcription_engine=self.transcription_engine,
            preparation=self.content_preparation,
            progress_callback=progress_callback,
        )

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
        """Run the local transcript pipeline."""
        return run_transcribe_pipeline(
            TranscribePipelineRequest(
                url=url,
                workspace_dir=workspace_dir,
                keep_video=keep_video,
                verbose=verbose,
            ),
            config=self.config,
            source_provider=self._source_provider(verbose=verbose),
            transcription_engine=self.transcription_engine,
            preparation=self.content_preparation,
        )

    def run_translation_experiment(
        self,
        url: str,
        *,
        workspace_dir: str | None = None,
        keep_video: bool = False,
        verbose: bool = False,
    ) -> TranslationExperimentResult:
        """Transcribe and build a local blind translation experiment."""
        transcription = self.transcribe(
            url,
            workspace_dir=workspace_dir,
            keep_video=keep_video,
            verbose=verbose,
        )
        runner = self.translation_experiment_runner
        if runner is None:
            from yt2notion.translation_experiment import create_translation_experiment_runner

            runner = create_translation_experiment_runner(self.config)
        return run_translation_experiment_pipeline(transcription, runner)

    def create_subtitle_pack(
        self,
        url: str,
        *,
        workspace_dir: str | None = None,
        keep_video: bool = False,
        verbose: bool = False,
    ) -> SubtitlePackResult:
        """Transcribe and build a local cue-timed bilingual package."""
        transcription = self.transcribe(
            url,
            workspace_dir=workspace_dir,
            keep_video=keep_video,
            verbose=verbose,
        )
        service = self.subtitle_pack_service or self._create_subtitle_pack_service(verbose=verbose)
        return run_subtitle_pack_pipeline(transcription, service)

    def _source_provider(self, *, verbose: bool) -> SourceProvider:
        if self.source_provider is not None:
            return self.source_provider
        return create_source_provider(self.raw_config, verbose=verbose)

    def _create_subtitle_pack_service(self, *, verbose: bool) -> SubtitlePackService:
        from yt2notion.models.llm import create_llm_caller
        from yt2notion.subtitle_pack import SubtitlePackService

        model_config = self.config.model
        model_label = (
            f"{model_config['backend']}:{model_config['translate_model']}:"
            f"reasoning={model_config.get('reasoning_effort', 'low')}"
        )
        if verbose:
            typer.echo(
                f"Subtitle LLM: {model_label}; "
                f"timeout={model_config['timeout_seconds']}s per provider attempt",
                err=True,
            )
        return SubtitlePackService(
            create_llm_caller(self.raw_config, model_key="translate_model"),
            model_label=model_label,
            target_language=str(self.config.output.get("target_language", "zh-CN")),
            progress_callback=(lambda message: typer.echo(message, err=True)) if verbose else None,
        )


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
        source_provider=create_source_provider(raw_config, verbose=verbose),
        transcription_engine=create_transcription_engine(raw_config),
    )
