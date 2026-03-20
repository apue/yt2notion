"""CLI entry point for yt2notion."""

from __future__ import annotations

import typer

app = typer.Typer(help="YouTube videos → structured Chinese notes → Notion")


@app.command()
def process(
    url: str = typer.Argument(help="YouTube video URL"),
    config_path: str = typer.Option("config.yaml", "--config", "-c", help="Config file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Process a YouTube video into a Chinese Notion page."""
    # TODO: Implement pipeline
    # 1. Load config
    # 2. Extract subtitles + metadata
    # 3. Process/clean subtitles
    # 4. Summarize (Sonnet)
    # 5. Chinese transform (Opus)
    # 6. Save to storage
    typer.echo(f"Processing: {url}")


if __name__ == "__main__":
    app()
