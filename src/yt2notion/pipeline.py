"""Pipeline orchestrator: 5-step metadata-driven flow with workspace persistence."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from yt2notion.extract import ExtractionError, extract_audio, extract_metadata, extract_subtitles
from yt2notion.models import create_summarizer
from yt2notion.process import (
    SubtitleEntry,
    format_chapters_transcript,
    format_timestamped_transcript,
    parse_subtitle_file,
    seconds_to_display,
)
from yt2notion.storage import create_storage
from yt2notion.workspace import STEPS, Workspace

if TYPE_CHECKING:
    from yt2notion.config import AppConfig
    from yt2notion.models.base import ChineseContent, VideoMeta


def run_pipeline(
    url: str,
    config: AppConfig,
    *,
    verbose: bool = False,
    dry_run: bool = False,
    no_confirm: bool = False,
    resume_from: str | None = None,
    workspace_dir: str | None = None,
) -> str:
    """Run the 5-step pipeline: download → segment → transcribe → review → summarize."""
    raw_config = {
        "extract": config.extract,
        "model": config.model,
        "storage": config.storage,
        "credit": config.credit,
        "output": config.output,
    }

    # Determine which steps to run
    start_idx = 0
    if resume_from:
        if resume_from not in STEPS:
            raise ValueError(f"Unknown step: {resume_from!r}. Valid: {', '.join(STEPS)}")
        start_idx = STEPS.index(resume_from)

    # --- Step 1: DOWNLOAD ---
    ws: Workspace | None = None

    if start_idx <= 0:
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
                _download_audio(url, metadata, raw_config, ws, verbose)
        else:
            _download_audio(url, metadata, raw_config, ws, verbose)
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

    # --- Step 2: SEGMENT ---
    if start_idx <= 1:
        segments = _step_segment(metadata, raw_config, verbose)
        ws.save_segments(segments)
    else:
        segments = ws.load_segments()
        if segments is None:
            raise ValueError("Cannot resume: no segments.json in workspace")

    # --- Step 3: TRANSCRIBE ---
    if start_idx <= 2:
        transcripts = _step_transcribe(ws, metadata, segments, raw_config, verbose)
        ws.save_transcripts(transcripts)  # Final save (incremental saves happen inside)
    else:
        transcripts = ws.load_transcripts()
        if transcripts is None:
            raise ValueError("Cannot resume: no transcripts.json in workspace")

    # --- Step 4: REVIEW ---
    if start_idx <= 3:
        reviewed = _step_review(transcripts, metadata, raw_config, ws, verbose)
        ws.save_reviewed(reviewed)  # Final save
    else:
        reviewed = ws.load_reviewed()
        if reviewed is None:
            raise ValueError("Cannot resume: no reviewed.json in workspace")

    # --- Step 5: SUMMARIZE ---
    chinese_content = _step_summarize(reviewed, metadata, raw_config, verbose)
    ws.save_summary(chinese_content)

    # --- Output / Publish ---
    if dry_run:
        credit_format = config.credit.get("format", "来源：{channel} 「{title}」\n链接：{url}")
        credit = credit_format.format(
            channel=metadata.channel, title=metadata.title, url=metadata.url
        )
        output = f"{credit}\n\n{chinese_content.raw_markdown}"
        typer.echo(output)
        return output

    if not no_confirm:
        typer.echo("\n--- Preview ---")
        typer.echo(chinese_content.raw_markdown[:500])
        if len(chinese_content.raw_markdown) > 500:
            typer.echo("...(truncated)")
        typer.echo("--- End Preview ---\n")
        if not typer.confirm("Publish to storage?"):
            typer.echo("Aborted.")
            return ""

    if verbose:
        typer.echo(f"Publishing to {config.storage['backend']}...")
    storage = create_storage(raw_config)
    result_url = storage.save(chinese_content, metadata, transcript_segments=reviewed)
    if verbose:
        typer.echo(f"  Published: {result_url}")
    return result_url


# === Step implementations ===


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
        # No segments — transcribe full audio, then split by sentences
        if verbose:
            typer.echo("  ASR on full audio (no pre-segmentation)...")
        entries = transcriber.transcribe(audio_path, language=language)
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


def _step_summarize(
    reviewed: list[dict],
    metadata: VideoMeta,
    config: dict,
    verbose: bool,
) -> ChineseContent:
    """Step 5: Summarize reviewed transcripts."""
    if verbose:
        typer.echo("Summarizing...")

    summarizer = create_summarizer(config)
    threshold = config.get("output", {}).get("long_content_threshold_seconds", 1800)

    # Short content with few segments: use single-pass pipeline
    if metadata.duration_seconds < threshold and len(reviewed) <= 3:
        return _summarize_short(reviewed, metadata, summarizer, config, verbose)

    # Long content: map-reduce
    return _summarize_long(reviewed, metadata, summarizer, verbose)


def _summarize_short(
    reviewed: list[dict],
    metadata: VideoMeta,
    summarizer: object,
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


def _summarize_long(
    reviewed: list[dict],
    metadata: VideoMeta,
    summarizer: object,
    verbose: bool,
) -> ChineseContent:
    """Map-reduce summarization for long content."""
    if verbose:
        typer.echo(f"  Long content — map-reduce ({len(reviewed)} segments)")

    # Map phase
    chunk_summaries = []
    for i, seg in enumerate(reviewed):
        segment_info = {
            "segment_title": seg.get("title", f"Part {i + 1}"),
            "start_time": seconds_to_display(seg["start_seconds"]),
            "end_time": seconds_to_display(seg["end_seconds"]),
            "segment_index": str(i + 1),
            "total_segments": str(len(reviewed)),
        }
        cs = summarizer.summarize_chunk(seg["text"], metadata, segment_info)
        chunk_summaries.append(cs)
        if verbose:
            typer.echo(f"  Map [{i + 1}/{len(reviewed)}] {cs.segment_title}")

    # Reduce phase
    if verbose:
        typer.echo("  Reduce: synthesizing global summary...")
    return summarizer.synthesize(chunk_summaries, metadata)
