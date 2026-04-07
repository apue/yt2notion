"""Pipeline orchestrator: 5-step metadata-driven flow with workspace persistence."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
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
        Summarizer,
        VideoMeta,
    )


FULL_AUDIO_ASR_CHUNK_SECONDS = 300
ASR_CHUNK_PADDING_SECONDS = 0.5
SUMMARY_GROUP_CHAR_LIMIT = 24_000
SUMMARY_GROUP_SEGMENT_LIMIT = 6
ENTITY_EXTRACT_SUBTITLE_SKIP_THRESHOLD = 300
ProgressEvent: TypeAlias = Literal["started", "completed"]
ProgressCallback: TypeAlias = Callable[[str, ProgressEvent, str | None], None]


@dataclass
class PreparedContent:
    """Structured pipeline output before storage publish."""

    metadata: VideoMeta
    chinese_content: ChineseContent
    transcript_segments: list[dict] | None
    entities: EntityResult | None
    workspace: Workspace
    is_long: bool
    output_mode: str


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

    if verbose:
        typer.echo(f"Publishing to {config.storage['backend']}...")

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

    if prepared.is_long and prepared.output_mode == "full" and prepared.transcript_segments:
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
            _emit_progress(progress_callback, "transcribe", "started")
            transcripts = _step_transcribe(ws, metadata, segments, raw_config, verbose)
            ws.save_transcripts(transcripts)  # Final save (incremental saves happen inside)
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
            if is_long:
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
) -> list[dict]:
    """Step 3: Transcribe content (subtitles or ASR)."""
    if verbose:
        typer.echo("Transcribing...")

    sub_path = ws.subtitle_path
    audio_path = ws.audio_path

    if sub_path:
        return _transcribe_from_subtitles(sub_path, segments, metadata, config, verbose)
    elif audio_path:
        return _transcribe_from_audio(audio_path, segments, metadata, config, ws, verbose)
    else:
        raise ExtractionError("No subtitles or audio found in workspace")


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


def _transcribe_from_audio(
    audio_path: Path,
    segments: list[dict],
    metadata: VideoMeta,
    config: dict,
    ws: Workspace,
    verbose: bool,
) -> list[dict]:
    """Transcribe audio via ASR, optionally per-segment."""
    from yt2notion.transcribe import create_transcriber

    transcriber = create_transcriber(config)
    language = metadata.language or None

    if segments:
        # Per-segment ASR: split audio, transcribe each piece
        from yt2notion.audio import split_audio

        seg_dir = audio_path.parent / "segments"
        seg_files = split_audio(audio_path, segments, seg_dir)

        # Load partial progress if available
        partial = ws.load_transcripts()
        result: list[dict] = list(partial) if partial else []
        start_from = len(result)

        if start_from > 0 and verbose:
            typer.echo(f"  Resuming ASR from segment {start_from + 1}/{len(segments)}")

        for i, (seg, seg_file) in enumerate(zip(segments, seg_files, strict=True)):
            if i < start_from:
                continue
            if verbose:
                typer.echo(f"  ASR [{i + 1}/{len(segments)}] {seg.get('title', '')}")
            entries = transcriber.transcribe(seg_file, language=language)
            text = " ".join(e.text for e in entries).strip()
            result.append(
                {
                    "title": seg.get("title", f"Part {i + 1}"),
                    "start_seconds": seg["start_seconds"],
                    "end_seconds": seg["end_seconds"],
                    "text": text,
                    "source": "asr",
                }
            )
            # Save progress incrementally after each segment
            ws.save_transcripts(result)
        return result
    else:
        # No segments — chunk long audio to avoid oversized remote ASR requests.
        if verbose:
            typer.echo("  ASR on full audio (no pre-segmentation)...")
        entries = _transcribe_full_audio_entries(
            audio_path,
            metadata,
            config,
            transcriber,
            language=language,
            verbose=verbose,
        )
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

    duration_seconds = float(metadata.duration_seconds or get_duration(audio_path))
    chunk_seconds = _resolve_full_audio_asr_chunk_seconds(config)

    if duration_seconds <= chunk_seconds:
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

        chunk_entries = transcriber.transcribe(chunk_file, language=language)
        all_entries.extend(_rebase_chunk_entries(chunk_entries, chunk_spec))

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


def render_prepared_output(prepared: PreparedContent, config: AppConfig) -> str:
    """Render human-readable dry-run output from prepared content."""
    credit_format = config.credit.get("format", "来源：{channel} 「{title}」\n链接：{url}")
    credit = credit_format.format(
        channel=prepared.metadata.channel,
        title=prepared.metadata.title,
        url=prepared.metadata.url,
    )
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
