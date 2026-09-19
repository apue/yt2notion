"""Local note preparation and explicit publishing product compositions."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from yt2notion.content_preparation import is_retries_exhausted
from yt2notion.media_source import AcquisitionError, acquire_media
from yt2notion.pipelines.contracts import (
    PreparedContent,
    ProgressCallback,
    StorageFactory,
    emit_progress,
)
from yt2notion.pipelines.shared import workspace_base
from yt2notion.runtime import RuntimeObserver, provider_call
from yt2notion.workspace import STEPS, Workspace

if TYPE_CHECKING:
    from yt2notion.config import AppConfig
    from yt2notion.content_preparation import ContentPreparation
    from yt2notion.media_source import SourceProvider
    from yt2notion.models.base import VideoMeta
    from yt2notion.transcribe.engine import TranscriptionEngine


def run_note_pipeline(
    url: str,
    *,
    config: AppConfig,
    source_provider: SourceProvider,
    transcription_engine: TranscriptionEngine,
    preparation: ContentPreparation,
    workspace_dir: str | None = None,
    resume_from: str | None = None,
    mode: str | None = None,
    verbose: bool = False,
    progress_callback: ProgressCallback | None = None,
    observer: RuntimeObserver | None = None,
) -> PreparedContent:
    """Acquire, transcribe, review, and compose a local source/A/B note bundle."""
    runtime = observer or RuntimeObserver(
        workspace_base(config, workspace_dir),
        run_name="note_prepare",
    )
    if observer is not None:
        return _run_note_pipeline(
            url,
            config=config,
            source_provider=source_provider,
            transcription_engine=transcription_engine,
            preparation=preparation,
            workspace_dir=workspace_dir,
            resume_from=resume_from,
            mode=mode,
            verbose=verbose,
            progress_callback=progress_callback,
            observer=runtime,
        )
    with runtime.run():
        return _run_note_pipeline(
            url,
            config=config,
            source_provider=source_provider,
            transcription_engine=transcription_engine,
            preparation=preparation,
            workspace_dir=workspace_dir,
            resume_from=resume_from,
            mode=mode,
            verbose=verbose,
            progress_callback=progress_callback,
            observer=runtime,
        )


def _run_note_pipeline(
    url: str,
    *,
    config: AppConfig,
    source_provider: SourceProvider,
    transcription_engine: TranscriptionEngine,
    preparation: ContentPreparation,
    workspace_dir: str | None,
    resume_from: str | None,
    mode: str | None,
    verbose: bool,
    progress_callback: ProgressCallback | None,
    observer: RuntimeObserver,
) -> PreparedContent:
    if mode not in {None, "summary"}:
        raise ValueError("source/A/B bundle output supports summary mode only")

    start_idx = _resume_index(resume_from)
    workspace: Workspace | None = None
    current_step = "download"
    try:
        if start_idx <= 0:
            emit_progress(progress_callback, "download", "started")
            try:
                with observer.span("node", "acquire"):
                    acquired = acquire_media(
                        source_provider,
                        url=url,
                        workspace_base_dir=workspace_base(config, workspace_dir),
                    )
            except AcquisitionError as failure:
                workspace = failure.workspace
                observer.relocate(workspace.dir)
                raise failure.cause from failure
            metadata = acquired.metadata
            workspace = acquired.workspace
            observer.relocate(workspace.dir)
            emit_progress(progress_callback, "download", "completed")
        else:
            with observer.span("node", "resume"):
                workspace, metadata = _resume_workspace(
                    url,
                    workspace_dir,
                    config=config,
                    verbose=verbose,
                )
            observer.relocate(workspace.dir)

        current_step = "segment"
        if start_idx <= 1:
            emit_progress(progress_callback, "segment", "started")
            with observer.span("node", "segment"):
                segments = preparation.segment(metadata, config, verbose)
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
            with observer.span("node", "transcribe"):
                transcripts = transcription_engine.transcribe_workspace(
                    workspace,
                    metadata,
                    segments,
                    verbose=verbose,
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
            with observer.span("node", "topic_segment"):
                transcripts = preparation.topic_segment(
                    transcripts,
                    metadata,
                    config,
                    max_segment_seconds,
                )
            if len(transcripts) != original_count:
                workspace.save_transcripts(transcripts)
                if verbose:
                    typer.echo(
                        f"  Topic segmentation: {original_count} -> {len(transcripts)} segments"
                    )
        elif verbose:
            typer.echo("  Skipping topic segmentation for manual subtitle transcript")

        current_step = "review"
        if preparation.should_cleanup(transcripts):
            if start_idx <= 3:
                emit_progress(progress_callback, "review", "started")
                with observer.span("node", "review"):
                    reviewed = preparation.review(
                        transcripts,
                        metadata,
                        config,
                        workspace,
                        verbose,
                    )
                    workspace.save_reviewed(reviewed)
                emit_progress(progress_callback, "review", "completed")
            else:
                reviewed = workspace.load_reviewed()
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
        with observer.span("node", "summarize"):
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
                url,
                current_step,
                exc,
                retries_exhausted=is_retries_exhausted(exc),
            )
        raise


def run_process_pipeline(
    url: str,
    *,
    config: AppConfig,
    source_provider: SourceProvider,
    transcription_engine: TranscriptionEngine,
    preparation: ContentPreparation,
    storage_factory: StorageFactory,
    workspace_dir: str | None = None,
    resume_from: str | None = None,
    mode: str | None = None,
    verbose: bool = False,
    dry_run: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> str:
    """Prepare and explicitly publish one note bundle under a shared run profile."""
    observer = RuntimeObserver(
        workspace_base(config, workspace_dir),
        run_name="process",
    )
    with observer.run():
        prepared = run_note_pipeline(
            url,
            config=config,
            source_provider=source_provider,
            transcription_engine=transcription_engine,
            preparation=preparation,
            workspace_dir=workspace_dir,
            resume_from=resume_from,
            mode=mode,
            verbose=verbose,
            progress_callback=progress_callback,
            observer=observer,
        )
        if dry_run:
            from yt2notion.content_preparation import render_prepared_output

            output = render_prepared_output(prepared, config)
            typer.echo(output)
            return output

        if verbose:
            typer.echo("Publishing to Obsidian...")

        def publish() -> str:
            storage = storage_factory(config.to_legacy_mapping())
            with provider_call("storage.save_note_bundle"):
                return storage.save_note_bundle(prepared.note_bundle, prepared.metadata)

        emit_progress(progress_callback, "publish", "started")
        with observer.span("node", "publish"):
            result_url = publish()
        emit_progress(progress_callback, "publish", "completed")
        if verbose:
            typer.echo(f"  Published: {result_url}")
        prepared.workspace.clear_failure()
        return result_url


def _resume_index(resume_from: str | None) -> int:
    if resume_from is None:
        return 0
    if resume_from not in STEPS:
        raise ValueError(f"Unknown step: {resume_from!r}. Valid: {', '.join(STEPS)}")
    return STEPS.index(resume_from)


def _resume_workspace(
    url: str,
    workspace_dir: str | None,
    *,
    config: AppConfig,
    verbose: bool,
) -> tuple[Workspace, VideoMeta]:
    from yt2notion.extract import extract_metadata

    base_dir = workspace_base(config, workspace_dir)
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
