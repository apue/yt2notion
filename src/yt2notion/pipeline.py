"""Pipeline orchestrator: connects extraction, processing, LLM, and storage."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from yt2notion.extract import extract_metadata, extract_subtitles
from yt2notion.models import create_summarizer
from yt2notion.process import (
    format_chapters_transcript,
    format_timestamped_transcript,
    parse_subtitle_file,
)
from yt2notion.storage import create_storage

if TYPE_CHECKING:
    from yt2notion.config import AppConfig


def run_pipeline(
    url: str,
    config: AppConfig,
    *,
    verbose: bool = False,
    dry_run: bool = False,
    no_confirm: bool = False,
) -> str:
    """Run the full yt2notion pipeline.

    Returns the URL/path of the created resource, or the raw markdown in dry-run mode.
    """
    # 1. Extract metadata
    if verbose:
        typer.echo("Extracting video metadata...")
    metadata = extract_metadata(url)
    if verbose:
        typer.echo(f"  Title: {metadata.title}")
        typer.echo(f"  Channel: {metadata.channel}")
        typer.echo(f"  Chapters: {len(metadata.chapters)} found")

    # 2. Extract subtitles
    if verbose:
        typer.echo("Downloading subtitles...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        raw_config = {
            "extract": config.extract,
            "model": config.model,
            "storage": config.storage,
            "credit": config.credit,
            "output": config.output,
        }
        subtitle_path = extract_subtitles(
            url, raw_config, Path(tmp_dir), video_id=metadata.video_id
        )
        if verbose:
            typer.echo(f"  Subtitle file: {subtitle_path.name}")

        # 3. Parse subtitles
        if verbose:
            typer.echo("Processing subtitles...")
        entries = parse_subtitle_file(subtitle_path)

        # 4. Build transcript based on chapters availability
        if metadata.chapters:
            transcript = format_chapters_transcript(entries, metadata.chapters)
            prompt_name = "summarize"
            if verbose:
                typer.echo(f"  Using {len(metadata.chapters)} author chapters")
        else:
            transcript = format_timestamped_transcript(entries)
            prompt_name = "summarize_freeform"
            if verbose:
                typer.echo(f"  No chapters — using {len(entries)} timestamped lines")

    if verbose:
        typer.echo(f"  {len(entries)} subtitle entries")

    # 5. Summarize with LLM
    if verbose:
        typer.echo(f"Summarizing with {config.model['backend']}...")
    summarizer = create_summarizer(raw_config)
    summary = summarizer.summarize(transcript, metadata, prompt_name=prompt_name)
    if verbose:
        typer.echo(f"  {len(summary.sections)} sections identified")

    # 6. Chinese transform
    if verbose:
        typer.echo("Generating Chinese content...")
    chinese_content = summarizer.to_chinese(summary, metadata)
    if verbose:
        typer.echo("  Chinese content ready")

    # 7. Dry run: output and return
    if dry_run:
        credit_format = config.credit.get("format", "来源：{channel} 「{title}」\n链接：{url}")
        credit = credit_format.format(
            channel=metadata.channel,
            title=metadata.title,
            url=metadata.url,
        )
        output = f"{credit}\n\n{chinese_content.raw_markdown}"
        typer.echo(output)
        return output

    # 8. Confirm before publishing
    if not no_confirm:
        typer.echo("\n--- Preview ---")
        typer.echo(chinese_content.raw_markdown[:500])
        if len(chinese_content.raw_markdown) > 500:
            typer.echo("...(truncated)")
        typer.echo("--- End Preview ---\n")
        if not typer.confirm("Publish to storage?"):
            typer.echo("Aborted.")
            return ""

    # 9. Save to storage
    if verbose:
        typer.echo(f"Publishing to {config.storage['backend']}...")
    storage = create_storage(raw_config)
    result_url = storage.save(chinese_content, metadata)
    if verbose:
        typer.echo(f"  Published: {result_url}")

    return result_url
