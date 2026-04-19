"""Pipeline orchestrator: 5-step metadata-driven flow with workspace persistence."""

from __future__ import annotations

import json
import math
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeAlias

import typer

from yt2notion.extract import (
    ExtractionError,
    extract_audio,
    extract_metadata,
    extract_subtitles,
    extract_webpage_transcript,
    write_transcript_srt,
)
from yt2notion.models import create_summarizer
from yt2notion.models.llm import create_llm_caller
from yt2notion.note_bundle import build_note_bundle
from yt2notion.process import (
    SubtitleEntry,
    format_chapters_transcript,
    format_timestamped_transcript,
    parse_subtitle_file,
    seconds_to_display,
)
from yt2notion.retry import RetryExhaustedError
from yt2notion.storage import create_storage
from yt2notion.topic_segment import segment_transcript
from yt2notion.workspace import STEPS, Workspace

if TYPE_CHECKING:
    from yt2notion.config import AppConfig
    from yt2notion.models.base import (
        ChineseContent,
        ChunkSummary,
        EntityResult,
        NoteBundle,
        Summarizer,
        VideoMeta,
    )


FULL_AUDIO_ASR_CHUNK_SECONDS = 300
MIN_ASR_UPLOAD_CHUNK_SECONDS = 30
ASR_CHUNK_PADDING_SECONDS = 0.5
SUMMARY_GROUP_CHAR_LIMIT = 24_000
SUMMARY_GROUP_SEGMENT_LIMIT = 6
ENTITY_EXTRACT_SUBTITLE_SKIP_THRESHOLD = 300
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
ChunkResultPayload: TypeAlias = list[dict[str, object]]


@dataclass
class PreparedContent:
    """Structured pipeline output before storage publish."""

    metadata: VideoMeta
    chinese_content: ChineseContent | None
    transcript_segments: list[dict] | None
    entities: EntityResult | None
    workspace: Workspace
    is_long: bool
    output_mode: str
    note_bundle: NoteBundle | None = None


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
    """Run the pipeline and publish to the configured storage backend."""
    prepared = prepare_content(
        url,
        config,
        verbose=verbose,
        resume_from=resume_from,
        workspace_dir=workspace_dir,
        mode=mode,
        progress_callback=progress_callback,
    )

    if dry_run:
        output = render_prepared_output(prepared, config)
        typer.echo(output)
        return output

    storage_backend = config.storage.get("backend", "notion")
    if prepared.note_bundle is not None and storage_backend != "obsidian":
        raise ValueError("source_ab_bundle publish requires obsidian backend")

    if verbose:
        typer.echo(f"Publishing to {storage_backend}...")

    raw_config = {
        "extract": config.extract,
        "model": config.model,
        "storage": config.storage,
        "credit": config.credit,
        "output": config.output,
    }
    storage = create_storage(raw_config)

    transcript_segments = prepared.transcript_segments
    if prepared.is_long:
        transcript_segments = None

    _emit_progress(progress_callback, "publish", "started")
    if prepared.note_bundle is not None:
        result_url = storage.save_note_bundle(
            prepared.note_bundle,
            prepared.metadata,
            transcript_segments=transcript_segments,
            entities=prepared.entities,
        )
    else:
        result_url = storage.save(
            prepared.chinese_content,
            prepared.metadata,
            transcript_segments=transcript_segments,
            entities=prepared.entities,
        )
    _emit_progress(progress_callback, "publish", "completed")
    if verbose:
        typer.echo(f"  Published: {result_url}")

    prepared.workspace.clear_failure()

    if (
        prepared.note_bundle is None
        and prepared.is_long
        and prepared.output_mode == "full"
        and prepared.transcript_segments
    ):
        if verbose:
            typer.echo("  Adding transcript sub-page...")
        storage.add_transcript_subpage(result_url, prepared.transcript_segments, prepared.metadata)
        if verbose:
            typer.echo("  Transcript sub-page added.")

    return result_url


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
    """Run the processing pipeline and return artifacts without publishing."""
    raw_config = {
        "extract": config.extract,
        "model": config.model,
        "storage": config.storage,
        "credit": config.credit,
        "output": config.output,
    }
    output_mode = _resolve_output_mode(config, mode)
    note_mode = _resolve_note_mode(config)
    if output_mode == "full" and note_mode == "source_ab_bundle":
        raise ValueError("source_ab_bundle currently supports summary mode only")

    # Determine which steps to run
    start_idx = 0
    if resume_from:
        if resume_from not in STEPS:
            raise ValueError(f"Unknown step: {resume_from!r}. Valid: {', '.join(STEPS)}")
        start_idx = STEPS.index(resume_from)

    ws: Workspace | None = None
    current_step = "download"

    try:
        if start_idx <= 0:
            _emit_progress(progress_callback, "download", "started")
            metadata = _step_download(url, raw_config, verbose)
            base_dir = Path(workspace_dir or config.workspace.get("base_dir", "./workspace"))
            ws = Workspace(base_dir, metadata.video_id)
            ws.save_metadata(metadata)

            # Download content based on metadata signals
            if metadata.subtitles_available:
                if verbose:
                    typer.echo("Downloading subtitles...")
                try:
                    with tempfile.TemporaryDirectory() as tmp_dir:
                        sub_path = extract_subtitles(
                            url, raw_config, Path(tmp_dir), video_id=metadata.video_id
                        )
                        ws.save_subtitles(sub_path)
                        if verbose:
                            typer.echo(f"  Saved: subtitles{sub_path.suffix}")
                except ExtractionError:
                    if verbose:
                        typer.echo("  Subtitle download failed, downloading audio instead...")
                    if not _download_webpage_transcript(url, metadata, ws, verbose):
                        _download_audio(url, metadata, raw_config, ws, verbose)
            else:
                if not _download_webpage_transcript(url, metadata, ws, verbose):
                    _download_audio(url, metadata, raw_config, ws, verbose)
            _emit_progress(progress_callback, "download", "completed")
        else:
            # Resume: load workspace
            base_dir = Path(workspace_dir or config.workspace.get("base_dir", "./workspace"))
            # For resume, we need the video_id from an existing workspace
            # Try to find it from the URL or existing workspace
            if resume_from and workspace_dir:
                # workspace_dir might be the full path including video_id
                ws_path = Path(workspace_dir)
                if (ws_path / "metadata.json").exists():
                    ws = Workspace(ws_path.parent, ws_path.name)
                else:
                    raise ValueError(f"No metadata.json found in {workspace_dir}")
            else:
                # Extract video_id from URL to find workspace
                metadata = extract_metadata(url)
                ws = Workspace(base_dir, metadata.video_id)

            metadata = ws.load_metadata()
            if metadata is None:
                raise ValueError("Cannot resume: no metadata.json in workspace")
            if verbose:
                typer.echo(f"Resuming from step '{resume_from}' for: {metadata.title}")

        current_step = "segment"
        if start_idx <= 1:
            _emit_progress(progress_callback, "segment", "started")
            segments = _step_segment(metadata, raw_config, verbose)
            ws.save_segments(segments)
            _emit_progress(progress_callback, "segment", "completed")
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
            _emit_progress(progress_callback, "transcribe", "started")
            transcripts = _step_transcribe(
                ws,
                metadata,
                segments,
                raw_config,
                verbose,
                progress_callback=progress_callback,
            )
            ws.save_transcripts(transcripts)  # Final save after all chunk checkpoints complete
            _emit_progress(progress_callback, "transcribe", "completed")
        else:
            transcripts = ws.load_transcripts()
            if transcripts is None:
                raise ValueError("Cannot resume: no transcripts.json in workspace")

        # --- Step 3.5: TOPIC SEGMENTATION (refine coarse segments) ---
        if start_idx <= 2:
            source = transcripts[0].get("source", "subtitle") if transcripts else "subtitle"
            if source == "asr":
                max_seg_sec = raw_config.get("output", {}).get("max_segment_seconds", 600)
                original_count = len(transcripts)
                transcripts = segment_transcript(transcripts, metadata, raw_config, max_seg_sec)
                if len(transcripts) != original_count:
                    ws.save_transcripts(transcripts)
                    if verbose:
                        typer.echo(
                            f"  Topic segmentation: {original_count} → {len(transcripts)} segments"
                        )
            elif verbose:
                typer.echo("  Skipping topic segmentation for subtitle-derived transcript")

        # --- Step 4: REVIEW / ANALYSIS INPUT ---
        current_step = "review"
        is_long = _is_long_content(metadata, transcripts, raw_config)
        if output_mode == "full":
            if is_long:
                reviewed = transcripts
                if verbose:
                    typer.echo(
                        "Skipping blocking review (long content — will review after summary)"
                    )
            elif start_idx <= 3:
                _emit_progress(progress_callback, "review", "started")
                reviewed = _step_review(transcripts, metadata, raw_config, ws, verbose)
                ws.save_reviewed(reviewed)
                _emit_progress(progress_callback, "review", "completed")
            else:
                reviewed = ws.load_reviewed()
                if reviewed is None:
                    raise ValueError("Cannot resume: no reviewed.json in workspace")
        elif note_mode == "source_ab_bundle" and not is_long:
            if start_idx <= 3:
                _emit_progress(progress_callback, "review", "started")
                reviewed = _step_review(transcripts, metadata, raw_config, ws, verbose)
                ws.save_reviewed(reviewed)
                _emit_progress(progress_callback, "review", "completed")
            else:
                reviewed = ws.load_reviewed()
                if reviewed is None:
                    raise ValueError("Cannot resume: no reviewed.json in workspace")
        else:
            reviewed = transcripts
            if verbose:
                typer.echo("Skipping transcript artifact review (summary mode)")

        # --- Step 5: EXTRACT ENTITIES ---
        current_step = "extract"
        analysis_segments = reviewed if output_mode == "full" else transcripts
        if start_idx <= 4:
            _emit_progress(progress_callback, "extract", "started")
            analysis_source = (
                analysis_segments[0].get("source", "subtitle") if analysis_segments else "subtitle"
            )
            if output_mode == "summary" and analysis_source != "asr":
                if verbose:
                    typer.echo("Skipping entities for subtitle-derived summary mode")
                entities = _empty_entities()
            else:
                entities = _step_extract(analysis_segments, raw_config, verbose)
            ws.save_entities(entities)
            _emit_progress(progress_callback, "extract", "completed")
        else:
            entities = ws.load_entities()
            if entities is None:
                raise ValueError("Cannot resume: no entities.json in workspace")

        # --- Step 6: SUMMARIZE ---
        current_step = "summarize"
        _emit_progress(progress_callback, "summarize", "started")
        note_bundle: NoteBundle | None = None
        if note_mode == "source_ab_bundle":
            if verbose:
                typer.echo("Summarizing source/A/B note bundle...")
            summarizer = create_summarizer(raw_config)
            note_bundle = build_note_bundle(reviewed, metadata, summarizer)
            ws.save_note_bundle(note_bundle)
            chinese_content: ChineseContent | None = None
        else:
            chinese_content = _step_summarize(
                analysis_segments,
                metadata,
                raw_config,
                verbose,
                output_mode=output_mode,
            )
            ws.save_summary(chinese_content)
        _emit_progress(progress_callback, "summarize", "completed")

        transcript_segments: list[dict] | None = None
        if output_mode == "full":
            if is_long and note_mode == "single":
                current_step = "deferred_review"
                _emit_progress(progress_callback, "review", "started")
                transcript_segments = _review_transcript_with_summary_context(
                    transcripts,
                    chinese_content,
                    metadata,
                    raw_config,
                    ws,
                    verbose,
                )
                _emit_progress(progress_callback, "review", "completed")
            else:
                transcript_segments = reviewed

        if ws is None:
            raise RuntimeError("Workspace unexpectedly unavailable")

        return PreparedContent(
            metadata=metadata,
            chinese_content=chinese_content,
            transcript_segments=transcript_segments,
            entities=entities,
            workspace=ws,
            is_long=is_long,
            output_mode=output_mode,
            note_bundle=note_bundle,
        )
    except Exception as exc:
        if ws is not None:
            ws.save_failure(
                url,
                current_step,
                exc,
                retries_exhausted=_is_retries_exhausted(exc),
            )
        raise


# === Step implementations ===


def _emit_progress(
    progress_callback: ProgressCallback | None,
    step: str,
    event: ProgressEvent,
    message: str | None = None,
) -> None:
    if progress_callback is not None:
        progress_callback(step, event, message)


def _step_download(url: str, config: dict, verbose: bool) -> VideoMeta:
    """Step 1: Extract metadata."""
    if verbose:
        typer.echo("Extracting metadata...")
    metadata = extract_metadata(url)
    if verbose:
        typer.echo(f"  Title: {metadata.title}")
        typer.echo(f"  Channel: {metadata.channel}")
        duration = (
            seconds_to_display(metadata.duration_seconds)
            if metadata.duration_seconds
            else "unknown"
        )
        typer.echo(f"  Duration: {duration}")
        typer.echo(f"  Chapters: {len(metadata.chapters)} found")
        typer.echo(f"  Subtitles available: {metadata.subtitles_available}")
    return metadata


def _download_audio(
    url: str, metadata: VideoMeta, config: dict, ws: Workspace, verbose: bool
) -> None:
    """Download audio and update duration if missing."""
    if verbose:
        typer.echo("Downloading audio...")
    cookies_from = config.get("extract", {}).get("cookies_from")
    with tempfile.TemporaryDirectory() as tmp_dir:
        audio_path = extract_audio(
            url, Path(tmp_dir), video_id=metadata.video_id, cookies_from=cookies_from
        )
        saved = ws.save_audio(audio_path)
        if verbose:
            size_mb = saved.stat().st_size / 1e6
            typer.echo(f"  Saved: {saved.name} ({size_mb:.1f} MB)")

    # Fill in duration if missing (Apple Podcasts often have duration=null)
    if metadata.duration_seconds == 0:
        from yt2notion.audio import get_duration

        duration = get_duration(saved)
        metadata.duration_seconds = int(duration)
        ws.save_metadata(metadata)  # Update with duration
        if verbose:
            typer.echo(f"  Duration (from audio): {seconds_to_display(metadata.duration_seconds)}")


def _download_webpage_transcript(
    url: str, metadata: VideoMeta, ws: Workspace, verbose: bool
) -> bool:
    """Try to fetch a transcript from the source webpage or linked episode page."""
    try:
        entries = extract_webpage_transcript(url, metadata)
    except Exception:
        return False

    if not entries:
        return False

    with tempfile.TemporaryDirectory() as tmp_dir:
        transcript_path = Path(tmp_dir) / f"{metadata.video_id or 'transcript'}.srt"
        write_transcript_srt(entries, transcript_path)
        saved = ws.save_subtitles(transcript_path)

    if verbose:
        typer.echo(f"  Found webpage transcript: {saved.name} ({len(entries)} entries)")
    return True


def _step_segment(metadata: VideoMeta, config: dict, verbose: bool) -> list[dict]:
    """Step 2: Determine segments from chapters or description."""
    if verbose:
        typer.echo("Segmenting...")

    segments: list[dict] = []

    if metadata.chapters:
        if verbose:
            typer.echo(f"  Using {len(metadata.chapters)} author chapters")
        for ch in metadata.chapters:
            segments.append(
                {
                    "title": ch.title,
                    "start_seconds": ch.start_seconds,
                    "end_seconds": ch.end_seconds,
                }
            )
    elif metadata.description:
        if verbose:
            typer.echo("  Extracting chapters from description via LLM...")
        from yt2notion.chapter_extract import extract_chapters_llm

        chapters = extract_chapters_llm(metadata.description, metadata.duration_seconds, config)
        if chapters:
            if verbose:
                typer.echo(f"  Found {len(chapters)} chapters")
            for ch in chapters:
                segments.append(
                    {
                        "title": ch.title,
                        "start_seconds": ch.start_seconds,
                        "end_seconds": ch.end_seconds,
                    }
                )
        else:
            if verbose:
                typer.echo("  No chapters found in description")

    if not segments and verbose:
        typer.echo("  No structural info — will segment after transcription")

    # Subdivide long segments
    max_seg = config.get("output", {}).get("max_segment_seconds", 900)
    subdivided: list[dict] = []
    for seg in segments:
        duration = seg["end_seconds"] - seg["start_seconds"]
        if duration > max_seg:
            # Split into roughly equal parts
            n_parts = (duration + max_seg - 1) // max_seg
            part_len = duration // n_parts
            for j in range(n_parts):
                start = seg["start_seconds"] + j * part_len
                end = (
                    seg["start_seconds"] + (j + 1) * part_len
                    if j < n_parts - 1
                    else seg["end_seconds"]
                )
                subdivided.append(
                    {
                        "title": f"{seg['title']} (Part {j + 1})" if n_parts > 1 else seg["title"],
                        "start_seconds": start,
                        "end_seconds": end,
                        "parent_title": seg["title"] if n_parts > 1 else None,
                    }
                )
        else:
            subdivided.append(seg)

    if verbose and subdivided:
        typer.echo(f"  {len(subdivided)} segments after subdivision")

    return subdivided


def _step_transcribe(
    ws: Workspace,
    metadata: VideoMeta,
    segments: list[dict],
    config: dict,
    verbose: bool,
    progress_callback: ProgressCallback | None = None,
) -> list[dict]:
    """Step 3: Transcribe content (subtitles or ASR)."""
    if verbose:
        typer.echo("Transcribing...")

    sub_path = ws.subtitle_path
    audio_path = ws.audio_path

    if sub_path:
        return _transcribe_from_subtitles(sub_path, segments, metadata, config, verbose)
    if audio_path is None:
        raise ExtractionError("No subtitles or audio found in workspace")

    from yt2notion.transcribe import create_fallback_transcriber, create_transcriber

    asr_cfg = config.get("extract", {}).get("asr", {})
    primary_backend = asr_cfg.get("backend", "remote")
    fallback_backend = asr_cfg.get("fallback_backend")
    transcriber = create_transcriber(config)
    fallback_transcriber = None

    def _load_fallback_transcriber():
        nonlocal fallback_transcriber
        if not fallback_backend:
            return None
        if fallback_transcriber is None:
            fallback_transcriber = create_fallback_transcriber(config)
        return fallback_transcriber

    return _transcribe_from_audio(
        audio_path,
        segments,
        metadata,
        config,
        ws,
        verbose,
        transcriber=transcriber,
        primary_backend=primary_backend,
        fallback_backend=fallback_backend,
        fallback_transcriber_factory=_load_fallback_transcriber,
        progress_callback=progress_callback,
    )


def _current_time() -> datetime:
    return datetime.now().astimezone()


def _now() -> datetime:
    return _current_time()


def _iso_after_retry(retry_after_seconds: float) -> str:
    return (_now() + timedelta(seconds=max(0.0, retry_after_seconds))).isoformat(timespec="seconds")


def _wait_until_retryable_time(next_attempt_at: str | None, *, verbose: bool) -> None:
    if not next_attempt_at:
        return
    target = datetime.fromisoformat(next_attempt_at)
    while True:
        remaining = (target - _now()).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 60.0))


def _chunk_payload_from_entries(entries: list[SubtitleEntry]) -> ChunkResultPayload:
    return [
        {
            "start_seconds": entry.start_seconds,
            "end_seconds": entry.end_seconds,
            "text": entry.text,
            "source": "asr",
        }
        for entry in entries
    ]


def _entries_from_chunk_payload(payload: ChunkResultPayload) -> list[SubtitleEntry]:
    return [
        SubtitleEntry(
            start_seconds=float(entry["start_seconds"]),
            end_seconds=float(entry["end_seconds"]),
            text=str(entry["text"]),
        )
        for entry in payload
    ]


def _chunk_audio_ref(ws: Workspace, path: Path) -> str:
    try:
        return str(path.relative_to(ws.dir))
    except ValueError:
        return str(path)


def _resolve_chunk_audio_path(ws: Workspace, audio_ref: str) -> Path:
    path = Path(audio_ref)
    if path.is_absolute():
        return path
    return ws.dir / path


def _transcribe_progress_message(
    chunk: dict,
    *,
    index: int,
    total: int,
    backend: str,
    **extra: object,
) -> str:
    payload: dict[str, object] = {
        "chunk_id": str(chunk["chunk_id"]),
        "chunk_index": index + 1,
        "chunk_total": total,
        "title": str(chunk.get("title", "")),
        "start_seconds": float(chunk["start_seconds"]),
        "end_seconds": float(chunk["end_seconds"]),
        "start_label": seconds_to_display(float(chunk["start_seconds"])),
        "end_label": seconds_to_display(float(chunk["end_seconds"])),
        "backend": backend,
    }
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _initial_transcribe_state(plan: list[dict], *, job_mode: str) -> dict:
    timestamp = _now().isoformat(timespec="seconds")
    return {
        "version": 1,
        "job_mode": job_mode,
        "status": "running",
        "next_attempt_at": None,
        "last_error": None,
        "defer_reason": None,
        "ash_defer_count": 0,
        "chunks": [
            {
                "chunk_id": chunk["chunk_id"],
                "status": "pending",
                "backend_used": None,
                "result_relpath": None,
                "attempts": 0,
                "updated_at": timestamp,
            }
            for chunk in plan
        ],
    }


def _load_or_create_transcribe_state(ws: Workspace, plan: list[dict], *, job_mode: str) -> dict:
    state = ws.load_transcribe_state()
    if state is None or not _transcribe_state_matches_plan(state, plan):
        state = _initial_transcribe_state(plan, job_mode=job_mode)
    if _reconcile_transcribe_state_from_chunk_results(ws, plan, state):
        ws.save_transcribe_state(state)
    return state


def _chunk_state(state: dict, chunk_id: str) -> dict:
    for chunk in state.get("chunks", []):
        if chunk.get("chunk_id") == chunk_id:
            return chunk
    raise ValueError(f"Missing transcribe state for chunk {chunk_id!r}")


def _transcribe_state_matches_plan(state: dict, plan: list[dict]) -> bool:
    if not isinstance(state, dict):
        return False
    if state.get("version") != 1:
        return False
    state_chunk_ids = [chunk.get("chunk_id") for chunk in state.get("chunks", [])]
    plan_chunk_ids = [chunk.get("chunk_id") for chunk in plan]
    return state_chunk_ids == plan_chunk_ids


def _reconcile_transcribe_state_from_chunk_results(
    ws: Workspace, plan: list[dict], state: dict
) -> bool:
    changed = False
    for chunk in plan:
        chunk_id = str(chunk["chunk_id"])
        chunk_state = _chunk_state(state, chunk_id)
        payload = ws.load_transcribe_chunk_result(chunk_id)
        if payload is None:
            if str(chunk_state.get("status", "")).startswith("completed_"):
                _mark_chunk_payload_missing(state, chunk_id)
                changed = True
            continue
        if str(chunk_state.get("status", "")).startswith("completed_"):
            continue
        backend_used = str(chunk_state.get("backend_used") or chunk.get("preferred_backend", "asr"))
        chunk_state["backend_used"] = backend_used
        chunk_state["result_relpath"] = str(Path("transcribe_chunks") / f"{chunk_id}.json")
        chunk_state["status"] = f"completed_{backend_used}"
        chunk_state["updated_at"] = _now().isoformat(timespec="seconds")
        changed = True
    return changed


def _clear_wait_state(state: dict) -> None:
    state["status"] = "running"
    state["next_attempt_at"] = None
    state["defer_reason"] = None
    state["last_error"] = None


def _mark_hourly_wait(state: dict, chunk_id: str, error) -> None:
    chunk = _chunk_state(state, chunk_id)
    chunk["attempts"] = int(chunk.get("attempts", 0)) + 1
    chunk["updated_at"] = _now().isoformat(timespec="seconds")
    state["status"] = "waiting_ash"
    state["next_attempt_at"] = _iso_after_retry(error.retry_after_seconds)
    state["defer_reason"] = "ash"
    state["last_error"] = str(error)
    state["ash_defer_count"] = int(state.get("ash_defer_count", 0)) + 1


def _mark_chunk_payload_missing(state: dict, chunk_id: str) -> None:
    chunk = _chunk_state(state, chunk_id)
    state["status"] = "running"
    state["next_attempt_at"] = None
    state["defer_reason"] = None
    chunk["status"] = "pending"
    chunk["backend_used"] = None
    chunk["result_relpath"] = None
    chunk["updated_at"] = _now().isoformat(timespec="seconds")


def _mark_chunk_completed(
    ws: Workspace,
    state: dict,
    chunk_id: str,
    *,
    backend_used: str,
    entries: list[SubtitleEntry],
) -> None:
    ws.save_transcribe_chunk_result(chunk_id, _chunk_payload_from_entries(entries))
    chunk = _chunk_state(state, chunk_id)
    chunk["attempts"] = int(chunk.get("attempts", 0)) + 1
    chunk["backend_used"] = backend_used
    chunk["result_relpath"] = str(Path("transcribe_chunks") / f"{chunk_id}.json")
    chunk["status"] = f"completed_{backend_used}"
    chunk["updated_at"] = _now().isoformat(timespec="seconds")
    _clear_wait_state(state)
    ws.save_transcribe_state(state)


def _switch_remaining_chunks_to_backend(
    ws: Workspace,
    plan: list[dict],
    state: dict,
    *,
    start_index: int,
    backend: str,
    error: Exception,
) -> None:
    for chunk in plan[start_index:]:
        chunk_state = _chunk_state(state, str(chunk["chunk_id"]))
        if chunk_state.get("status") == "pending":
            chunk["preferred_backend"] = backend
    state["job_mode"] = "remote_remaining"
    state["status"] = "running"
    state["next_attempt_at"] = None
    state["defer_reason"] = None
    state["last_error"] = str(error)
    ws.save_transcribe_plan(plan)
    ws.save_transcribe_state(state)


def _transcribe_from_subtitles(
    sub_path: Path,
    segments: list[dict],
    metadata: VideoMeta,
    config: dict,
    verbose: bool,
) -> list[dict]:
    """Assign subtitle entries to segments, or create segments from entries."""
    entries = parse_subtitle_file(sub_path)
    if verbose:
        typer.echo(f"  Parsed {len(entries)} subtitle entries")

    if segments:
        # Assign entries to existing segments by time
        return _assign_entries_to_segments(entries, segments)
    else:
        # No segments — sentence-split the full transcript
        from yt2notion.segment import _split_by_duration

        max_seg = config.get("output", {}).get("max_segment_seconds", 900)
        split_segs = _split_by_duration(entries, max_seg)
        return [
            {
                "title": seg.title,
                "start_seconds": seg.start_seconds,
                "end_seconds": seg.end_seconds,
                "text": seg.text,
                "source": "subtitle",
            }
            for seg in split_segs
        ]


def _assign_entries_to_segments(entries: list[SubtitleEntry], segments: list[dict]) -> list[dict]:
    """Assign subtitle entries to segments by timestamp."""
    result: list[dict] = []
    for seg in segments:
        seg_entries = [
            e
            for e in entries
            if e.start_seconds >= seg["start_seconds"] and e.start_seconds < seg["end_seconds"]
        ]
        text = " ".join(e.text for e in seg_entries).strip()
        result.append(
            {
                "title": seg.get("title", ""),
                "start_seconds": seg["start_seconds"],
                "end_seconds": seg["end_seconds"],
                "text": text,
                "source": "subtitle",
            }
        )
    return result


def _build_segment_transcribe_plan(
    *,
    ws: Workspace,
    audio_path: Path,
    segments: list[dict],
    preferred_backend: str,
) -> list[dict]:
    existing = ws.load_transcribe_plan()
    if (
        isinstance(existing, list)
        and existing
        and len(existing) == len(segments)
        and all(
            isinstance(chunk, dict)
            and chunk.get("segment_index") == index
            and "audio_relpath" in chunk
            and "preferred_backend" in chunk
            for index, chunk in enumerate(existing)
        )
    ):
        return existing

    from yt2notion.audio import split_audio

    seg_dir = audio_path.parent / "segments"
    seg_files = split_audio(audio_path, segments, seg_dir)
    plan = [
        {
            "chunk_id": f"segment-{index + 1:03d}",
            "segment_index": index,
            "title": seg.get("title", f"Part {index + 1}"),
            "start_seconds": seg["start_seconds"],
            "end_seconds": seg["end_seconds"],
            "audio_relpath": _chunk_audio_ref(ws, seg_file),
            "preferred_backend": preferred_backend,
        }
        for index, (seg, seg_file) in enumerate(zip(segments, seg_files, strict=True))
    ]
    ws.save_transcribe_plan(plan)
    return plan


def _build_full_audio_transcribe_plan(
    *,
    ws: Workspace,
    audio_path: Path,
    metadata: VideoMeta,
    config: dict,
    transcriber,
    preferred_backend: str,
) -> list[dict]:
    existing = ws.load_transcribe_plan()
    if (
        isinstance(existing, list)
        and existing
        and all(
            isinstance(chunk, dict)
            and "segment_index" not in chunk
            and "audio_relpath" in chunk
            and "preferred_backend" in chunk
            for chunk in existing
        )
    ):
        return existing

    from yt2notion.audio import get_duration, split_audio
    from yt2notion.transcribe.errors import TranscriptionError

    duration_seconds = float(metadata.duration_seconds or get_duration(audio_path))
    configured_chunk_seconds = _resolve_full_audio_asr_chunk_seconds(config)
    chunk_seconds = configured_chunk_seconds
    max_upload_bytes = _transcriber_max_upload_bytes(transcriber)
    file_size = audio_path.stat().st_size
    oversize_full_audio = False

    if max_upload_bytes is not None and file_size > max_upload_bytes:
        oversize_full_audio = True
        chunk_seconds = _resolve_upload_budget_chunk_seconds(
            duration_seconds,
            file_size_bytes=file_size,
            configured_chunk_seconds=configured_chunk_seconds,
            max_upload_bytes=max_upload_bytes,
        )

    if duration_seconds <= chunk_seconds:
        if oversize_full_audio:
            raise TranscriptionError(
                f"ASR full audio {audio_path.name} ({file_size} bytes) exceeds "
                f"max_upload_bytes ({max_upload_bytes}) at minimum chunk size "
                f"({MIN_ASR_UPLOAD_CHUNK_SECONDS}s)"
            )
        plan = [
            {
                "chunk_id": "chunk-001",
                "title": "Chunk 1",
                "start_seconds": 0.0,
                "end_seconds": duration_seconds,
                "audio_relpath": _chunk_audio_ref(ws, audio_path),
                "preferred_backend": preferred_backend,
            }
        ]
    else:
        chunk_specs = _build_full_audio_chunk_specs(duration_seconds, chunk_seconds)
        chunk_dir = audio_path.parent / "full_audio_chunks"
        chunk_files = split_audio(audio_path, chunk_specs, chunk_dir)
        plan = [
            {
                "chunk_id": f"chunk-{index + 1:03d}",
                "title": chunk_spec["title"],
                "start_seconds": chunk_spec["start_seconds"],
                "end_seconds": chunk_spec["end_seconds"],
                "audio_relpath": _chunk_audio_ref(ws, chunk_file),
                "preferred_backend": preferred_backend,
            }
            for index, (chunk_spec, chunk_file) in enumerate(
                zip(chunk_specs, chunk_files, strict=True)
            )
        ]

    ws.save_transcribe_plan(plan)
    return plan


def _load_required_chunk_payload(ws: Workspace, chunk_id: str) -> ChunkResultPayload:
    from yt2notion.transcribe.errors import TranscriptionError

    payload = ws.load_transcribe_chunk_result(chunk_id)
    if payload is None:
        raise TranscriptionError(f"Missing transcribe chunk result for {chunk_id}")
    return payload


def _segment_transcripts_from_plan(ws: Workspace, plan: list[dict]) -> list[dict]:
    result: list[dict] = []
    for chunk in plan:
        payload = _load_required_chunk_payload(ws, str(chunk["chunk_id"]))
        entries = _entries_from_chunk_payload(payload)
        result.append(
            {
                "title": chunk["title"],
                "start_seconds": chunk["start_seconds"],
                "end_seconds": chunk["end_seconds"],
                "text": " ".join(entry.text for entry in entries).strip(),
                "source": "asr",
            }
        )
    return result


def _merged_chunk_entries(ws: Workspace, plan: list[dict]) -> list[SubtitleEntry]:
    merged: list[SubtitleEntry] = []
    for chunk in plan:
        payload = _load_required_chunk_payload(ws, str(chunk["chunk_id"]))
        merged.extend(_entries_from_chunk_payload(payload))
    return merged


def _resolve_chunk_transcriber(
    *,
    backend: str,
    primary_backend: str,
    primary_transcriber,
    fallback_backend: str | None,
    fallback_transcriber_factory: Callable[[], object | None] | None,
):
    from yt2notion.transcribe.errors import TranscriptionError

    if backend == primary_backend:
        return primary_transcriber
    if backend == fallback_backend and fallback_transcriber_factory is not None:
        resolved = fallback_transcriber_factory()
        if resolved is not None:
            return resolved
    raise TranscriptionError(f"No transcriber configured for backend {backend!r}")


def _execute_chunk_plan(
    *,
    ws: Workspace,
    audio_path: Path,
    plan: list[dict],
    state: dict,
    config: dict,
    primary_backend: str,
    transcriber,
    fallback_backend: str | None,
    fallback_transcriber_factory: Callable[[], object | None] | None,
    language: str | None,
    verbose: bool,
    progress_callback: ProgressCallback | None = None,
) -> None:
    from yt2notion.transcribe.errors import (
        TranscriptionDailyLimitError,
        TranscriptionHourlyLimitError,
    )

    configured_chunk_seconds = _resolve_full_audio_asr_chunk_seconds(config)
    for index, chunk in enumerate(plan):
        chunk_id = str(chunk["chunk_id"])
        chunk_state = _chunk_state(state, chunk_id)
        if chunk_state.get("status", "").startswith("completed_"):
            if ws.load_transcribe_chunk_result(chunk_id) is None:
                _mark_chunk_payload_missing(state, chunk_id)
                ws.save_transcribe_state(state)
            else:
                continue

        if state.get("status") == "waiting_ash" and state.get("next_attempt_at"):
            wait_target = str(state["next_attempt_at"])
            retry_after_seconds = max(
                0.0, (datetime.fromisoformat(wait_target) - _now()).total_seconds()
            )
            _emit_progress(
                progress_callback,
                "transcribe",
                "hourly_wait",
                _transcribe_progress_message(
                    chunk,
                    index=index,
                    total=len(plan),
                    backend=str(chunk.get("preferred_backend", primary_backend)),
                    retry_after_seconds=round(retry_after_seconds, 3),
                    next_attempt_at=wait_target,
                    resumed_from_state=True,
                    ash_defer_count=int(state.get("ash_defer_count", 0)),
                ),
            )
            _wait_until_retryable_time(state.get("next_attempt_at"), verbose=verbose)
            _clear_wait_state(state)
            ws.save_transcribe_state(state)

        while True:
            backend = str(chunk.get("preferred_backend", primary_backend))
            _emit_progress(
                progress_callback,
                "transcribe",
                "chunk_started",
                _transcribe_progress_message(
                    chunk,
                    index=index,
                    total=len(plan),
                    backend=backend,
                    attempt=int(chunk_state.get("attempts", 0)) + 1,
                ),
            )
            active_transcriber = _resolve_chunk_transcriber(
                backend=backend,
                primary_backend=primary_backend,
                primary_transcriber=transcriber,
                fallback_backend=fallback_backend,
                fallback_transcriber_factory=fallback_transcriber_factory,
            )
            chunk_file = _resolve_chunk_audio_path(ws, str(chunk["audio_relpath"]))
            should_rebase = "segment_index" not in chunk
            try:
                entries = _transcribe_segment_entries_with_byte_budget(
                    audio_path=audio_path,
                    segment=chunk,
                    segment_file=chunk_file,
                    transcriber=active_transcriber,
                    language=language,
                    configured_chunk_seconds=configured_chunk_seconds,
                    verbose=verbose,
                    should_rebase=should_rebase,
                )
            except TranscriptionHourlyLimitError as exc:
                _mark_hourly_wait(state, chunk_id, exc)
                ws.save_transcribe_state(state)
                _emit_progress(
                    progress_callback,
                    "transcribe",
                    "hourly_wait",
                    _transcribe_progress_message(
                        chunk,
                        index=index,
                        total=len(plan),
                        backend=backend,
                        retry_after_seconds=round(float(exc.retry_after_seconds), 3),
                        next_attempt_at=state.get("next_attempt_at"),
                        resumed_from_state=False,
                        ash_defer_count=int(state.get("ash_defer_count", 0)),
                    ),
                )
                _wait_until_retryable_time(state.get("next_attempt_at"), verbose=verbose)
                continue
            except TranscriptionDailyLimitError as exc:
                if backend != primary_backend:
                    raise
                fallback = (
                    fallback_transcriber_factory()
                    if fallback_transcriber_factory is not None
                    else None
                )
                if fallback_backend is None or fallback is None:
                    raise
                ws.mark_asr_fallback_used()
                affected_chunk_ids = [
                    str(pending_chunk["chunk_id"])
                    for pending_chunk in plan[index:]
                    if _chunk_state(
                        state, str(pending_chunk["chunk_id"])
                    ).get("status") == "pending"
                ]
                _switch_remaining_chunks_to_backend(
                    ws,
                    plan,
                    state,
                    start_index=index,
                    backend=fallback_backend,
                    error=exc,
                )
                _emit_progress(
                    progress_callback,
                    "transcribe",
                    "daily_fallback_switch",
                    _transcribe_progress_message(
                        chunk,
                        index=index,
                        total=len(plan),
                        backend=backend,
                        fallback_backend=fallback_backend,
                        affected_chunk_ids=affected_chunk_ids,
                        affected_chunk_count=len(affected_chunk_ids),
                    ),
                )
                continue

            _mark_chunk_completed(ws, state, chunk_id, backend_used=backend, entries=entries)
            _emit_progress(
                progress_callback,
                "transcribe",
                "chunk_completed",
                _transcribe_progress_message(
                    chunk,
                    index=index,
                    total=len(plan),
                    backend=backend,
                    entries_count=len(entries),
                    attempts=int(_chunk_state(state, chunk_id).get("attempts", 0)),
                ),
            )
            break

    state["status"] = "completed"
    state["next_attempt_at"] = None
    state["defer_reason"] = None
    state["last_error"] = None
    ws.save_transcribe_state(state)


def _transcribe_from_audio(
    audio_path: Path,
    segments: list[dict],
    metadata: VideoMeta,
    config: dict,
    ws: Workspace,
    verbose: bool,
    *,
    transcriber=None,
    primary_backend: str = "remote",
    fallback_backend: str | None = None,
    fallback_transcriber_factory: Callable[[], object | None] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[dict]:
    """Transcribe audio via ASR, optionally per-segment."""
    if transcriber is None:
        from yt2notion.transcribe import create_transcriber

        transcriber = create_transcriber(config)
    language = metadata.language or None

    if segments:
        plan = _build_segment_transcribe_plan(
            ws=ws,
            audio_path=audio_path,
            segments=segments,
            preferred_backend=primary_backend,
        )
        state = _load_or_create_transcribe_state(ws, plan, job_mode=primary_backend)
        _execute_chunk_plan(
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
        return _segment_transcripts_from_plan(ws, plan)

    if verbose:
        typer.echo("  ASR on full audio (no pre-segmentation)...")
    plan = _build_full_audio_transcribe_plan(
        ws=ws,
        audio_path=audio_path,
        metadata=metadata,
        config=config,
        transcriber=transcriber,
        preferred_backend=primary_backend,
    )
    state = _load_or_create_transcribe_state(ws, plan, job_mode=primary_backend)
    _execute_chunk_plan(
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
    entries = _merged_chunk_entries(ws, plan)
    if verbose:
        typer.echo(f"  {len(entries)} ASR segments returned")

    # Sentence-split into segments
    from yt2notion.segment import _split_by_duration

    max_seg = config.get("output", {}).get("max_segment_seconds", 900)
    split_segs = _split_by_duration(entries, max_seg)
    return [
        {
            "title": seg.title,
            "start_seconds": seg.start_seconds,
            "end_seconds": seg.end_seconds,
            "text": seg.text,
            "source": "asr",
        }
        for seg in split_segs
    ]


def _transcriber_max_upload_bytes(transcriber) -> int | None:
    raw_value = getattr(transcriber, "max_upload_bytes", None)
    if isinstance(raw_value, int) and raw_value > 0:
        return raw_value
    return None


def _resolve_upload_budget_chunk_seconds(
    duration_seconds: float,
    *,
    file_size_bytes: int,
    configured_chunk_seconds: int,
    max_upload_bytes: int,
) -> int:
    configured = max(MIN_ASR_UPLOAD_CHUNK_SECONDS, int(configured_chunk_seconds))
    if duration_seconds <= 0 or file_size_bytes <= 0 or max_upload_bytes <= 0:
        return configured

    budget_seconds = duration_seconds * (max_upload_bytes / file_size_bytes) * 0.9
    budget_chunk = max(MIN_ASR_UPLOAD_CHUNK_SECONDS, int(math.floor(budget_seconds)))
    return max(MIN_ASR_UPLOAD_CHUNK_SECONDS, min(configured, budget_chunk))


def _build_segment_subchunks(segment: dict, chunk_seconds: int) -> list[dict]:
    start = float(segment["start_seconds"])
    end = float(segment["end_seconds"])
    chunk = max(1.0, float(chunk_seconds))
    chunks: list[dict] = []
    index = 1
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + chunk, end)
        chunks.append(
            {
                "title": f"{segment.get('title', 'Segment')} chunk {index}",
                "start_seconds": cursor,
                "end_seconds": chunk_end,
            }
        )
        cursor = chunk_end
        index += 1
    return chunks


def _transcribe_segment_entries_with_byte_budget(
    *,
    audio_path: Path,
    segment: dict,
    segment_file: Path,
    transcriber,
    language: str | None,
    configured_chunk_seconds: int,
    verbose: bool,
    should_rebase: bool = False,
) -> list[SubtitleEntry]:
    from yt2notion.audio import split_audio
    from yt2notion.transcribe.errors import TranscriptionError

    max_upload_bytes = _transcriber_max_upload_bytes(transcriber)
    segment_duration = float(segment["end_seconds"] - segment["start_seconds"])
    segment_size = segment_file.stat().st_size if segment_file.exists() else 0
    if max_upload_bytes is not None and segment_file.exists() and segment_size > max_upload_bytes:
        if segment_duration <= MIN_ASR_UPLOAD_CHUNK_SECONDS:
            raise TranscriptionError(
                f"ASR chunk {segment_file.name} ({segment_size} bytes) exceeds "
                f"max_upload_bytes ({max_upload_bytes}) at minimum chunk size "
                f"({MIN_ASR_UPLOAD_CHUNK_SECONDS}s)"
            )

        chunk_seconds = _resolve_upload_budget_chunk_seconds(
            segment_duration,
            file_size_bytes=segment_size,
            configured_chunk_seconds=configured_chunk_seconds,
            max_upload_bytes=max_upload_bytes,
        )
        if chunk_seconds >= segment_duration:
            raise TranscriptionError(
                f"ASR chunk {segment_file.name} ({segment_size} bytes) exceeds "
                f"max_upload_bytes ({max_upload_bytes}); cannot subdivide further."
            )
        subchunks = _build_segment_subchunks(segment, chunk_seconds)
        if verbose:
            typer.echo(
                "    Segment exceeds upload budget; subdividing "
                f"into {len(subchunks)} chunk(s) (~{chunk_seconds}s)"
            )
        subchunk_dir = segment_file.parent / f"{segment_file.stem}_chunks"
        subchunk_files = split_audio(audio_path, subchunks, subchunk_dir)
        rebased_entries: list[SubtitleEntry] = []
        for subchunk, subchunk_file in zip(subchunks, subchunk_files, strict=True):
            rebased_entries.extend(
                _transcribe_segment_entries_with_byte_budget(
                    audio_path=audio_path,
                    segment=subchunk,
                    segment_file=subchunk_file,
                    transcriber=transcriber,
                    language=language,
                    configured_chunk_seconds=configured_chunk_seconds,
                    verbose=verbose,
                    should_rebase=True,
                )
            )
        return rebased_entries

    entries = transcriber.transcribe(segment_file, language=language)
    if should_rebase:
        return _rebase_chunk_entries(entries, segment)
    return entries


def _transcribe_full_audio_entries(
    audio_path: Path,
    metadata: VideoMeta,
    config: dict,
    transcriber,
    *,
    language: str | None,
    verbose: bool,
) -> list[SubtitleEntry]:
    """Transcribe full audio, chunking long files to keep remote ASR requests bounded."""
    from yt2notion.audio import get_duration, split_audio
    from yt2notion.transcribe.errors import TranscriptionError

    duration_seconds = float(metadata.duration_seconds or get_duration(audio_path))
    configured_chunk_seconds = _resolve_full_audio_asr_chunk_seconds(config)
    chunk_seconds = configured_chunk_seconds
    max_upload_bytes = _transcriber_max_upload_bytes(transcriber)
    file_size = audio_path.stat().st_size
    oversize_full_audio = False

    if max_upload_bytes is not None:
        if file_size <= max_upload_bytes:
            return transcriber.transcribe(audio_path, language=language)
        oversize_full_audio = True
        chunk_seconds = _resolve_upload_budget_chunk_seconds(
            duration_seconds,
            file_size_bytes=file_size,
            configured_chunk_seconds=configured_chunk_seconds,
            max_upload_bytes=max_upload_bytes,
        )

    if duration_seconds <= chunk_seconds:
        if oversize_full_audio:
            raise TranscriptionError(
                f"ASR full audio {audio_path.name} ({file_size} bytes) exceeds "
                f"max_upload_bytes ({max_upload_bytes}) at minimum chunk size "
                f"({MIN_ASR_UPLOAD_CHUNK_SECONDS}s)"
            )
        return transcriber.transcribe(audio_path, language=language)

    chunk_specs = _build_full_audio_chunk_specs(duration_seconds, chunk_seconds)
    chunk_dir = audio_path.parent / "full_audio_chunks"
    chunk_files = split_audio(audio_path, chunk_specs, chunk_dir)

    all_entries: list[SubtitleEntry] = []
    for index, (chunk_spec, chunk_file) in enumerate(zip(chunk_specs, chunk_files, strict=True)):
        if verbose:
            start_label = seconds_to_display(chunk_spec["start_seconds"])
            end_label = seconds_to_display(chunk_spec["end_seconds"])
            typer.echo(f"  ASR chunk [{index + 1}/{len(chunk_specs)}] {start_label}-{end_label}")

        chunk_entries = _transcribe_segment_entries_with_byte_budget(
            audio_path=audio_path,
            segment=chunk_spec,
            segment_file=chunk_file,
            transcriber=transcriber,
            language=language,
            configured_chunk_seconds=chunk_seconds,
            verbose=verbose,
            should_rebase=True,
        )
        all_entries.extend(chunk_entries)

    return all_entries


def _resolve_full_audio_asr_chunk_seconds(config: dict) -> int:
    """Choose a safe chunk size for long full-audio ASR uploads."""
    asr_cfg = config.get("extract", {}).get("asr", {})
    configured = asr_cfg.get("chunk_seconds")
    if isinstance(configured, int) and configured > 0:
        return configured

    max_segment = config.get("output", {}).get("max_segment_seconds", FULL_AUDIO_ASR_CHUNK_SECONDS)
    return max(1, min(int(max_segment), FULL_AUDIO_ASR_CHUNK_SECONDS))


def _build_full_audio_chunk_specs(duration_seconds: float, chunk_seconds: int) -> list[dict]:
    """Create synthetic contiguous segments for chunked full-audio ASR."""
    chunks: list[dict] = []
    start = 0.0
    index = 1
    while start < duration_seconds:
        end = min(start + chunk_seconds, duration_seconds)
        chunks.append(
            {
                "title": f"Chunk {index}",
                "start_seconds": start,
                "end_seconds": end,
            }
        )
        start = end
        index += 1
    return chunks


def _rebase_chunk_entries(entries: list[SubtitleEntry], chunk_spec: dict) -> list[SubtitleEntry]:
    """Map chunk-local ASR timestamps back to the original timeline and drop overlap duplicates."""
    chunk_start = float(chunk_spec["start_seconds"])
    chunk_end = float(chunk_spec["end_seconds"])
    clip_start = max(0.0, chunk_start - ASR_CHUNK_PADDING_SECONDS)

    rebased: list[SubtitleEntry] = []
    for entry in entries:
        adjusted_start = clip_start + entry.start_seconds
        adjusted_end = clip_start + entry.end_seconds
        midpoint = (adjusted_start + adjusted_end) / 2
        if midpoint < chunk_start or midpoint >= chunk_end:
            continue

        rebased.append(
            SubtitleEntry(
                start_seconds=max(chunk_start, adjusted_start),
                end_seconds=min(chunk_end, adjusted_end),
                text=entry.text,
            )
        )

    return rebased


def _step_review(
    transcripts: list[dict],
    metadata: VideoMeta,
    config: dict,
    ws: Workspace,
    verbose: bool,
) -> list[dict]:
    """Step 4: Review/clean transcripts using Haiku."""
    if verbose:
        typer.echo("Reviewing transcripts...")

    # Skip review for subtitle-sourced content (already clean)
    source = transcripts[0].get("source", "subtitle") if transcripts else "subtitle"
    if source == "subtitle":
        if verbose:
            typer.echo("  Subtitle source — skipping review")
        return transcripts

    from yt2notion.review import review_segment

    # Load partial progress if available
    partial = ws.load_reviewed()
    reviewed: list[dict] = list(partial) if partial else []
    start_from = len(reviewed)

    if start_from > 0 and verbose:
        typer.echo(f"  Resuming review from segment {start_from + 1}/{len(transcripts)}")

    for i, seg in enumerate(transcripts):
        if i < start_from:
            continue
        if verbose:
            typer.echo(f"  Review [{i + 1}/{len(transcripts)}] {seg.get('title', '')}")
        cleaned_text = review_segment(seg["text"], metadata, config)
        reviewed.append({**seg, "text": cleaned_text})
        ws.save_reviewed(reviewed)

    return reviewed


def _step_extract(
    reviewed: list[dict],
    config: dict,
    verbose: bool,
) -> EntityResult:
    """Step 5: Extract entities from reviewed transcripts."""
    if verbose:
        typer.echo("Extracting entities...")

    source = reviewed[0].get("source", "subtitle") if reviewed else "subtitle"
    if source != "asr" and len(reviewed) > ENTITY_EXTRACT_SUBTITLE_SKIP_THRESHOLD:
        if verbose:
            typer.echo("  Skipping entity extraction for large subtitle-derived transcript")
        return _empty_entities()

    from yt2notion.entity_extract import extract_entities

    caller = create_llm_caller(config, model_key="review_model")
    result = extract_entities(reviewed, caller, max_workers=_llm_parallel_workers(config))

    if verbose:
        typer.echo(f"  Found {len(result.entities)} entities ({result.domain})")

    return result


def _empty_entities() -> EntityResult:
    from yt2notion.models.base import EntityResult

    return EntityResult(
        domain="",
        is_entity_centric=False,
        entity_types=[],
        entities=[],
        relations=[],
    )


def _step_summarize(
    reviewed: list[dict],
    metadata: VideoMeta,
    config: dict,
    verbose: bool,
    *,
    output_mode: str,
) -> ChineseContent:
    """Step 6: Summarize reviewed transcripts."""
    if verbose:
        typer.echo("Summarizing...")

    source = reviewed[0].get("source", "subtitle") if reviewed else "subtitle"
    summarizer = create_summarizer(config)

    if (
        output_mode == "summary"
        and source == "asr"
        and not _is_long_content(metadata, reviewed, config)
    ):
        return _summarize_short_asr_single_pass(reviewed, metadata, summarizer, config, verbose)

    if not _is_long_content(metadata, reviewed, config):
        return _summarize_short(reviewed, metadata, summarizer, config, verbose)

    return _summarize_long(
        reviewed,
        metadata,
        summarizer,
        verbose,
        max_workers=_llm_parallel_workers(config),
    )


def _summarize_short(
    reviewed: list[dict],
    metadata: VideoMeta,
    summarizer: Summarizer,
    config: dict,
    verbose: bool,
) -> ChineseContent:
    """Single-pass summarization for short content."""
    # Reconstruct entries for formatting
    entries = [
        SubtitleEntry(
            start_seconds=seg["start_seconds"],
            end_seconds=seg["end_seconds"],
            text=seg["text"],
        )
        for seg in reviewed
    ]

    if metadata.chapters:
        transcript = format_chapters_transcript(entries, metadata.chapters)
        prompt_name = "summarize"
    else:
        transcript = format_timestamped_transcript(entries)
        prompt_name = "summarize_freeform"

    if verbose:
        typer.echo(f"  Short content — single pass ({prompt_name})")
    summary = summarizer.summarize(transcript, metadata, prompt_name=prompt_name)
    if verbose:
        typer.echo(f"  {len(summary.sections)} sections → generating Chinese content...")
    return summarizer.to_chinese(summary, metadata)


def _summarize_short_asr_single_pass(
    transcripts: list[dict],
    metadata: VideoMeta,
    summarizer: Summarizer,
    config: dict,
    verbose: bool,
) -> ChineseContent:
    """Summarize raw ASR in one analysis call that internally reviews the text first."""
    entries = [
        SubtitleEntry(
            start_seconds=seg["start_seconds"],
            end_seconds=seg["end_seconds"],
            text=seg["text"],
        )
        for seg in transcripts
    ]

    if metadata.chapters:
        transcript = format_chapters_transcript(entries, metadata.chapters)
        prompt_name = "summarize_reviewed"
    else:
        transcript = format_timestamped_transcript(entries)
        prompt_name = "summarize_reviewed_freeform"

    if verbose:
        typer.echo(f"  Summary mode — internal review + summary ({prompt_name})")

    result = summarizer.review_and_summarize(transcript, metadata, prompt_name=prompt_name)
    summary = result.summary

    if verbose:
        typer.echo(f"  {len(summary.sections)} sections → generating Chinese content...")
    return summarizer.to_chinese(summary, metadata)


def _summarize_long(
    reviewed: list[dict],
    metadata: VideoMeta,
    summarizer: Summarizer,
    verbose: bool,
    *,
    max_workers: int = 1,
) -> ChineseContent:
    """Map-reduce summarization for long content.

    Merges fine-grained segments into ~8-12 groups before the map phase
    to reduce the number of LLM calls (e.g. 89 segments → 9 groups).
    """
    groups = _merge_segments_into_groups(reviewed)
    if verbose:
        typer.echo(f"  Long content — map-reduce ({len(reviewed)} segments → {len(groups)} groups)")

    # Map phase: one Sonnet call per group
    def _summarize_group(i: int, group: dict):
        segment_info = {
            "segment_title": group["title"],
            "start_time": seconds_to_display(group["start_seconds"]),
            "end_time": seconds_to_display(group["end_seconds"]),
            "segment_index": str(i + 1),
            "total_segments": str(len(groups)),
        }
        return i, summarizer.summarize_chunk(group["text"], metadata, segment_info)

    chunk_summaries: list[ChunkSummary | None] = [None] * len(groups)
    worker_count = max(1, min(max_workers, len(groups)))

    if worker_count == 1:
        for i, group in enumerate(groups):
            _, cs = _summarize_group(i, group)
            chunk_summaries[i] = cs
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(_summarize_group, i, group) for i, group in enumerate(groups)
            ]
            for future in as_completed(futures):
                i, cs = future.result()
                chunk_summaries[i] = cs

    finalized_chunk_summaries = [cs for cs in chunk_summaries if cs is not None]

    for i, cs in enumerate(finalized_chunk_summaries):
        if verbose:
            typer.echo(f"  Map [{i + 1}/{len(groups)}] {cs.segment_title}")

    # Reduce phase
    if verbose:
        typer.echo("  Reduce: synthesizing global summary...")
    return summarizer.synthesize(finalized_chunk_summaries, metadata)


def _is_long_content(metadata: VideoMeta, transcripts: list[dict], config: dict) -> bool:
    """Determine if content should use the long (map-reduce) path."""
    threshold = config.get("output", {}).get("long_content_threshold_seconds", 1800)
    return metadata.duration_seconds >= threshold or len(transcripts) > 3


def _llm_parallel_workers(config: dict) -> int:
    """Allow more concurrency for slower CLI backends during independent map phases."""
    backend = config.get("model", {}).get("backend", "claude_code")
    if backend in {"codex_cli", "openai_api"}:
        return int(config.get("model", {}).get("parallel_workers", 3))
    return 1


def _merge_segments_into_groups(segments: list[dict]) -> list[dict]:
    """Merge fine-grained segments into larger groups for efficient map-reduce.

    Bound group size so CLI backends do not receive oversized prompts.
    """
    groups: list[dict] = []
    current_batch: list[dict] = []
    current_chars = 0

    def _flush(batch: list[dict]) -> None:
        if not batch:
            return
        titles = [segment.get("title", "") for segment in batch if segment.get("title")]
        combined_title = titles[0] if len(titles) == 1 else f"{titles[0]} — {titles[-1]}"
        groups.append(
            {
                "title": combined_title,
                "start_seconds": batch[0]["start_seconds"],
                "end_seconds": batch[-1]["end_seconds"],
                "text": "\n\n".join(segment.get("text", "") for segment in batch),
                "source": batch[0].get("source", "asr"),
                "segment_count": len(batch),
            }
        )

    for segment in segments:
        segment_chars = len(segment.get("text", ""))
        exceeds_char_limit = current_chars + segment_chars > SUMMARY_GROUP_CHAR_LIMIT
        exceeds_segment_limit = len(current_batch) >= SUMMARY_GROUP_SEGMENT_LIMIT

        if current_batch and (exceeds_char_limit or exceeds_segment_limit):
            _flush(current_batch)
            current_batch = []
            current_chars = 0

        current_batch.append(segment)
        current_chars += segment_chars

    _flush(current_batch)

    return groups


def _build_review_context(chinese_content: ChineseContent) -> dict[str, str]:
    """Extract review context from completed summary."""
    key_terms: list[str] = []
    for kp in chinese_content.key_points:
        title = kp.get("title", "")
        if title:
            key_terms.append(title)

    return {
        "overview": chinese_content.overview,
        "key_terms": ", ".join(key_terms),
        "tags": ", ".join(chinese_content.tags),
    }


def _review_transcript_with_summary_context(
    transcripts: list[dict],
    chinese_content: ChineseContent,
    metadata: VideoMeta,
    config: dict,
    ws: Workspace,
    verbose: bool,
) -> list[dict]:
    """Review transcript after summary generation using summary-derived terminology anchors."""
    source = transcripts[0].get("source", "subtitle") if transcripts else "subtitle"
    if source == "subtitle":
        if verbose:
            typer.echo("  Subtitle source — skipping async review")
        return transcripts

    if verbose:
        typer.echo("Async review: context-aware transcript cleanup...")

    from yt2notion.review import review_segment

    review_context = _build_review_context(chinese_content)
    groups = _merge_segments_into_groups(transcripts)
    reviewed_groups: list[str] = []

    try:
        for i, group in enumerate(groups):
            if verbose:
                typer.echo(f"  Review [{i + 1}/{len(groups)}] {group.get('title', '')}")
            cleaned = review_segment(group["text"], metadata, config, review_context)
            reviewed_groups.append(cleaned)
    except RetryExhaustedError as exc:
        typer.echo(
            f"  Warning: review retries exhausted ({exc}), using unreviewed transcript",
            err=True,
        )
        reviewed = _prepend_review_failure_note(transcripts)
        ws.save_reviewed(reviewed)
        return reviewed

    reviewed = _redistribute_reviewed_text(transcripts, groups, reviewed_groups)
    ws.save_reviewed(reviewed)
    return reviewed


def _prepend_review_failure_note(transcripts: list[dict]) -> list[dict]:
    """Add a warning note before unreviewed transcript content."""
    note = {
        "title": "⚠️ 逐字稿未经校对（校对步骤失败）",
        "start_seconds": 0,
        "end_seconds": 0,
        "text": "逐字稿使用原始 ASR 输出，未经过校对。",
        "source": "review_failed",
    }
    return [note, *transcripts]


def _resolve_output_mode(config: AppConfig, override: str | None) -> str:
    """Resolve output mode from CLI override or config, validating the value."""
    mode = override or config.output.get("mode", "summary")
    if mode not in {"summary", "full"}:
        raise ValueError(f"Unknown output mode: {mode!r}. Valid: summary, full")
    return mode


def _resolve_note_mode(config: AppConfig) -> str:
    """Resolve the note generation mode from config."""
    mode = config.output.get("note_mode")
    if mode is None:
        storage_backend = config.storage.get("backend", "notion")
        mode = "source_ab_bundle" if storage_backend == "obsidian" else "single"
    if mode not in {"single", "source_ab_bundle"}:
        raise ValueError(f"Unknown note mode: {mode!r}. Valid: single, source_ab_bundle")
    return mode


def render_prepared_output(prepared: PreparedContent, config: AppConfig) -> str:
    """Render human-readable dry-run output from prepared content."""
    credit_format = config.credit.get("format", "来源：{channel} 「{title}」\n链接：{url}")
    credit = credit_format.format(
        channel=prepared.metadata.channel,
        title=prepared.metadata.title,
        url=prepared.metadata.url,
    )
    if prepared.note_bundle is not None:
        parts = [
            credit,
            "# Source",
            prepared.note_bundle.source.markdown,
            "# A / Guide",
            prepared.note_bundle.guide.markdown,
            "# B / Longform",
            prepared.note_bundle.longform.markdown,
        ]
    else:
        if prepared.chinese_content is None:
            raise RuntimeError("Prepared content is missing summary output")
        parts = [credit, prepared.chinese_content.raw_markdown]
    if prepared.output_mode == "full" and prepared.transcript_segments:
        parts.append(render_transcript_markdown(prepared.metadata, prepared.transcript_segments))
    return "\n\n".join(parts)


def render_transcript_markdown(metadata: VideoMeta, transcript_segments: list[dict]) -> str:
    """Render reviewed transcript for dry-run and agent JSON output."""
    lines = [f"## 逐字稿：{metadata.title}", ""]
    for seg in transcript_segments:
        start = int(seg.get("start_seconds", 0))
        lines.append(f"### [{seconds_to_display(start)}] {seg.get('title', '').strip()}")
        lines.append("")
        lines.append(seg.get("text", "").strip())
        lines.append("")
    return "\n".join(lines).strip()


def _is_retries_exhausted(exc: Exception) -> bool:
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


def _redistribute_reviewed_text(
    original_segments: list[dict],
    groups: list[dict],
    reviewed_texts: list[str],
) -> list[dict]:
    """Map reviewed group text back to original segment granularity.

    Uses character-length ratio to split reviewed text proportionally.
    """
    result: list[dict] = []
    cursor = 0

    for group, reviewed_text in zip(groups, reviewed_texts, strict=True):
        segment_count = int(group.get("segment_count", 0))
        if segment_count <= 0:
            continue

        batch = original_segments[cursor : cursor + segment_count]
        cursor += segment_count
        if not batch:
            continue

        if len(batch) == 1:
            result.append({**batch[0], "text": reviewed_text})
            continue

        # Split proportionally by original text length
        orig_lengths = [len(s.get("text", "")) for s in batch]
        total_orig = sum(orig_lengths)
        if total_orig == 0:
            for seg in batch:
                result.append({**seg, "text": ""})
            continue

        # Split reviewed text by paragraph boundaries (\n\n) matching original proportions
        pos = 0
        for j, seg in enumerate(batch):
            ratio = orig_lengths[j] / total_orig
            if j == len(batch) - 1:
                chunk = reviewed_text[pos:]
            else:
                target_end = pos + int(len(reviewed_text) * ratio)
                # Find nearest paragraph break
                break_pos = reviewed_text.find("\n\n", target_end - 50, target_end + 200)
                if break_pos == -1:
                    break_pos = target_end
                else:
                    break_pos += 2  # Include the \n\n
                chunk = reviewed_text[pos:break_pos]
                pos = break_pos
            result.append({**seg, "text": chunk.strip()})

    # Defensive fallback for unexpected group mismatch; preserve untouched tail.
    if cursor < len(original_segments):
        result.extend({**seg} for seg in original_segments[cursor:])

    return result
