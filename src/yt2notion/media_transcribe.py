"""Standalone transcription helpers."""

from __future__ import annotations

import json
from pathlib import Path

from yt2notion.config import AppConfig, ConfigError
from yt2notion.transcript_artifacts import (
    MediaTranscribeResult as MediaTranscribeResult,  # noqa: TC001
)
from yt2notion.transcript_artifacts import (
    render_media_transcript_markdown as render_media_transcript_markdown,
)

DEFAULT_USER_CONFIG_PATH = Path.home() / ".yt2notion" / "config.yaml"
DEFAULT_REPO_CONFIG_PATH = Path("config.yaml")


def resolve_media_transcribe_config_path(config_path: str | None) -> Path:
    """Resolve explicit, user-level, or repository configuration."""
    if config_path:
        explicit = Path(config_path).expanduser()
        if explicit.exists():
            return explicit
        raise ConfigError(f"Config file not found: {config_path}")

    candidates = [DEFAULT_USER_CONFIG_PATH, DEFAULT_REPO_CONFIG_PATH]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    tried = ", ".join(str(path) for path in candidates)
    raise ConfigError(f"Config file not found. Tried: {tried}")


def transcribe_media(
    url: str,
    config: AppConfig,
    *,
    workspace_dir: str | None = None,
    keep_video: bool = True,
    verbose: bool = False,
) -> MediaTranscribeResult:
    """Prefer captions, otherwise transcribe media, and save local artifacts."""
    from yt2notion.application import create_yt2notion

    return create_yt2notion(config, verbose=verbose).transcribe(
        url,
        workspace_dir=workspace_dir,
        keep_video=keep_video,
        verbose=verbose,
    )


def write_result_json(result: MediaTranscribeResult) -> str:
    """Serialize CLI result summary as formatted JSON."""
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
