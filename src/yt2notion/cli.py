"""CLI entry point for yt2notion."""

from __future__ import annotations

import typer

from yt2notion.config import ConfigError, load_config
from yt2notion.extract import ExtractionError

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
    if not reviewed_path.exists():
        typer.echo(f"No reviewed.json found in {content_dir}", err=True)
        raise typer.Exit(1) from None

    import json

    reviewed = json.loads(reviewed_path.read_text(encoding="utf-8"))

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
