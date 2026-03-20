"""CLI entry point for yt2notion."""

from __future__ import annotations

import typer

from yt2notion.config import ConfigError, load_config
from yt2notion.extract import ExtractionError

app = typer.Typer(help="YouTube videos → structured Chinese notes → Notion")


@app.command()
def process(
    url: str = typer.Argument(help="YouTube video URL"),
    config_path: str = typer.Option("config.yaml", "--config", "-c", help="Config file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Output result without publishing"),
    no_confirm: bool = typer.Option(False, "--no-confirm", help="Skip confirmation prompt"),
) -> None:
    """Process a YouTube video into a Chinese Notion page."""
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
        )
        if result and not dry_run:
            typer.echo(f"Done! {result}")
    except ExtractionError as e:
        typer.echo(f"Extraction error: {e}", err=True)
        raise typer.Exit(1) from None
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
