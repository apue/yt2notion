"""CLI entry point for yt2notion."""

from __future__ import annotations

import json
from dataclasses import asdict

import typer

from yt2notion.config import ConfigError, load_config
from yt2notion.extract import ExtractionError
from yt2notion.process import seconds_to_display

app = typer.Typer(help="YouTube videos → structured Chinese notes → Notion")


@app.command()
def process(
    url: str = typer.Argument(help="YouTube or podcast URL"),
    config_path: str = typer.Option("config.yaml", "--config", "-c", help="Config file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Output result without publishing"),
    no_confirm: bool = typer.Option(False, "--no-confirm", help="Skip confirmation prompt"),
    resume: str = typer.Option(None, "--resume", help="Resume from workspace directory"),
    from_step: str = typer.Option(
        None, "--from", help="Step to resume from (download/segment/transcribe/review/summarize)"
    ),
    workspace_dir: str = typer.Option(None, "--workspace-dir", help="Workspace base directory"),
    mode: str = typer.Option(None, "--mode", help="Output mode: summary or full"),
) -> None:
    """Process a video or podcast into a Chinese Notion page."""
    try:
        config = load_config(config_path)
    except ConfigError as e:
        typer.echo(f"Configuration error: {e}", err=True)
        raise typer.Exit(1) from None

    from yt2notion.pipeline import run_pipeline

    try:
        result = run_pipeline(
            url,
            config,
            verbose=verbose,
            dry_run=dry_run,
            no_confirm=no_confirm,
            resume_from=from_step,
            workspace_dir=resume or workspace_dir,
            mode=mode,
        )
        if result and not dry_run:
            typer.echo(f"Done! {result}")
    except ExtractionError as e:
        typer.echo(f"Extraction error: {e}", err=True)
        raise typer.Exit(1) from None
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None


@app.command()
def prepare(
    url: str = typer.Argument(help="YouTube or podcast URL"),
    config_path: str = typer.Option("config.yaml", "--config", "-c", help="Config file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    resume: str = typer.Option(None, "--resume", help="Resume from workspace directory"),
    from_step: str = typer.Option(
        None, "--from", help="Step to resume from (download/segment/transcribe/review/summarize)"
    ),
    workspace_dir: str = typer.Option(None, "--workspace-dir", help="Workspace base directory"),
    mode: str = typer.Option(None, "--mode", help="Output mode: summary or full"),
) -> None:
    """Run processing without publishing and emit structured JSON for agent wrappers."""
    try:
        config = load_config(config_path)
    except ConfigError as e:
        typer.echo(f"Configuration error: {e}", err=True)
        raise typer.Exit(1) from None

    from yt2notion.pipeline import prepare_content

    try:
        prepared = prepare_content(
            url,
            config,
            verbose=verbose,
            resume_from=from_step,
            workspace_dir=resume or workspace_dir,
            mode=mode,
        )
    except ExtractionError as e:
        typer.echo(f"Extraction error: {e}", err=True)
        raise typer.Exit(1) from None
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None

    transcript_markdown = None
    if prepared.transcript_segments:
        lines = [f"## 逐字稿：{prepared.metadata.title}", ""]
        for seg in prepared.transcript_segments:
            lines.append(
                (
                    f"### [{seconds_to_display(int(seg.get('start_seconds', 0)))}] "
                    f"{str(seg.get('title', '')).strip()}"
                ).strip()
            )
            lines.append("")
            lines.append(str(seg.get("text", "")).strip())
            lines.append("")
        transcript_markdown = "\n".join(lines).strip()

    payload = {
        "mode": prepared.output_mode,
        "is_long": prepared.is_long,
        "metadata": asdict(prepared.metadata),
        "summary": {
            "overview": prepared.chinese_content.overview,
            "key_points": prepared.chinese_content.key_points,
            "tags": prepared.chinese_content.tags,
            "fun_facts": prepared.chinese_content.fun_facts,
            "mindmap": prepared.chinese_content.mindmap,
            "raw_markdown": prepared.chinese_content.raw_markdown,
        },
        "transcript_segments": prepared.transcript_segments,
        "transcript_markdown": transcript_markdown,
        "entities": asdict(prepared.entities) if prepared.entities else None,
        "workspace_dir": str(prepared.workspace.dir),
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command()
def extract(
    content_dir: str = typer.Argument(help="Workspace directory containing reviewed.json"),
    config_path: str = typer.Option("config.yaml", "--config", "-c", help="Config file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Extract entities from reviewed transcript in a workspace directory."""
    from pathlib import Path

    try:
        config = load_config(config_path)
    except ConfigError as e:
        typer.echo(f"Configuration error: {e}", err=True)
        raise typer.Exit(1) from None

    from yt2notion.entity_extract import extract_entities
    from yt2notion.models.llm import create_llm_caller

    ws_dir = Path(content_dir)
    reviewed_path = ws_dir / "reviewed.json"
    transcripts_path = ws_dir / "transcripts.json"
    if reviewed_path.exists():
        reviewed = json.loads(reviewed_path.read_text(encoding="utf-8"))
    elif transcripts_path.exists():
        reviewed = json.loads(transcripts_path.read_text(encoding="utf-8"))
    else:
        typer.echo(f"No reviewed.json or transcripts.json found in {content_dir}", err=True)
        raise typer.Exit(1) from None

    raw_config = {
        "model": config.model,
    }
    caller = create_llm_caller(raw_config, model_key="review_model")

    if verbose:
        typer.echo(f"Extracting entities from {len(reviewed)} segments...")

    result = extract_entities(reviewed, caller)

    # Save to workspace
    from dataclasses import asdict

    output_path = ws_dir / "entities.json"
    output_path.write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if verbose:
        typer.echo(f"  Domain: {result.domain}")
        typer.echo(f"  Entity-centric: {result.is_entity_centric}")
        typer.echo(f"  Entities: {len(result.entities)}")
        typer.echo(f"  Relations: {len(result.relations)}")
    typer.echo(f"Saved to {output_path}")


if __name__ == "__main__":
    app()
