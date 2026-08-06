"""CLI entry point for yt2notion."""

from __future__ import annotations

import json
from dataclasses import asdict

import typer

from yt2notion.application import create_yt2notion
from yt2notion.config import ConfigError, load_config
from yt2notion.extract import ExtractionError

app = typer.Typer(help="YouTube videos → structured Chinese notes → storage")
RESUME_STEP_HELP = "Step to resume from (download/segment/transcribe/review/summarize)"


@app.command()
def process(
    url: str = typer.Argument(help="YouTube or podcast URL"),
    config_path: str = typer.Option("config.yaml", "--config", "-c", help="Config file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Output result without publishing"),
    resume: str = typer.Option(None, "--resume", help="Resume from workspace directory"),
    from_step: str = typer.Option(None, "--from", help=RESUME_STEP_HELP),
    workspace_dir: str = typer.Option(None, "--workspace-dir", help="Workspace base directory"),
    mode: str = typer.Option(None, "--mode", help="Output mode: summary only"),
) -> None:
    """Process media into an Obsidian source/A/B note bundle."""
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(1) from None

    try:
        result = create_yt2notion(config, verbose=verbose).process(
            url,
            verbose=verbose,
            dry_run=dry_run,
            resume_from=from_step,
            workspace_dir=resume or workspace_dir,
            mode=mode,
        )
        if result and not dry_run:
            typer.echo(f"Done! {result}")
    except ExtractionError as exc:
        typer.echo(f"Extraction error: {exc}", err=True)
        raise typer.Exit(1) from None
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None


@app.command()
def prepare(
    url: str = typer.Argument(help="YouTube or podcast URL"),
    config_path: str = typer.Option("config.yaml", "--config", "-c", help="Config file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    resume: str = typer.Option(None, "--resume", help="Resume from workspace directory"),
    from_step: str = typer.Option(None, "--from", help=RESUME_STEP_HELP),
    workspace_dir: str = typer.Option(None, "--workspace-dir", help="Workspace base directory"),
    mode: str = typer.Option(None, "--mode", help="Output mode: summary only"),
) -> None:
    """Run processing without publishing and emit structured JSON."""
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(1) from None

    try:
        prepared = create_yt2notion(config, verbose=verbose).prepare(
            url,
            verbose=verbose,
            resume_from=from_step,
            workspace_dir=resume or workspace_dir,
            mode=mode,
        )
    except ExtractionError as exc:
        typer.echo(f"Extraction error: {exc}", err=True)
        raise typer.Exit(1) from None
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None

    payload = {
        "mode": "bundle",
        "is_long": prepared.is_long,
        "metadata": asdict(prepared.metadata),
        "workspace_dir": str(prepared.workspace.dir),
        "note_bundle": asdict(prepared.note_bundle),
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("transcribe")
def transcribe(
    url: str = typer.Argument(help="Media URL"),
    config_path: str | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Config file path; defaults to ~/.yt2notion/config.yaml, then ./config.yaml",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    workspace_dir: str | None = typer.Option(None, "--workspace-dir", help="Workspace base dir"),
    keep_video: bool = typer.Option(
        True,
        "--keep-video/--no-video",
        help="Keep the downloaded video artifact in the workspace",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON result summary"),
) -> None:
    """Prefer captions, otherwise download media and transcribe, then write artifacts."""
    from yt2notion.audio import AudioError
    from yt2notion.media_transcribe import (
        resolve_media_transcribe_config_path,
        transcribe_media,
        write_result_json,
    )

    try:
        resolved_config_path = resolve_media_transcribe_config_path(config_path)
        config = load_config(str(resolved_config_path))
        result = transcribe_media(
            url,
            config,
            workspace_dir=workspace_dir,
            keep_video=keep_video,
            verbose=verbose,
        )
    except ConfigError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(1) from None
    except ExtractionError as exc:
        typer.echo(f"Extraction error: {exc}", err=True)
        raise typer.Exit(1) from None
    except AudioError as exc:
        typer.echo(f"Audio error: {exc}", err=True)
        raise typer.Exit(1) from None
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None

    if json_output:
        typer.echo(write_result_json(result))
        return

    typer.echo(f"Workspace: {result.workspace.dir}")
    if result.video_path:
        typer.echo(f"Video: {result.video_path}")
    typer.echo(f"Audio: {result.audio_path}")
    typer.echo(f"Transcript JSON: {result.transcripts_path}")
    typer.echo(f"Transcript Markdown: {result.transcript_markdown_path}")


@app.command("translation-experiment")
def translation_experiment(
    url: str = typer.Argument(help="Media URL"),
    config_path: str | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Config file path; defaults to ~/.yt2notion/config.yaml, then ./config.yaml",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    workspace_dir: str | None = typer.Option(None, "--workspace-dir", help="Workspace base dir"),
    keep_video: bool = typer.Option(
        False,
        "--keep-video/--no-video",
        help="Keep downloaded video when no subtitle track is available",
    ),
) -> None:
    """Create whole-chapter vs semantic-block blind translation candidates."""
    from yt2notion.media_transcribe import resolve_media_transcribe_config_path

    try:
        resolved_config_path = resolve_media_transcribe_config_path(config_path)
        config = load_config(str(resolved_config_path))
        result = create_yt2notion(config, verbose=verbose).run_translation_experiment(
            url,
            workspace_dir=workspace_dir,
            keep_video=keep_video,
            verbose=verbose,
        )
    except ConfigError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(1) from None
    except ExtractionError as exc:
        typer.echo(f"Extraction error: {exc}", err=True)
        raise typer.Exit(1) from None
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None

    typer.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
