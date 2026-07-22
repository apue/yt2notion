"""MediaSource adapter factory."""

from __future__ import annotations

from yt2notion.media_source.base import (
    ContentMediaAcquireResult,
    MediaAcquireRequest,
    MediaAcquireResult,
    MediaAcquisitionError,
    MediaSource,
    TranscriptMediaAcquireResult,
)
from yt2notion.media_source.ytdlp import YtDlpMediaSource


def create_media_source(config: dict, *, verbose: bool = False) -> MediaSource:
    """Create the configured media acquisition adapter."""
    source_cfg = config.get("extract", {}).get("media_source", {})
    if not isinstance(source_cfg, dict):
        raise ValueError("extract.media_source must be a mapping")
    backend = source_cfg.get("backend", "yt_dlp")
    if backend == "yt_dlp":
        return YtDlpMediaSource(config, verbose=verbose)
    raise ValueError(f"Unknown media-source backend: {backend!r}. Supported: yt_dlp")


__all__ = [
    "MediaAcquireRequest",
    "MediaAcquireResult",
    "MediaAcquisitionError",
    "MediaSource",
    "ContentMediaAcquireResult",
    "TranscriptMediaAcquireResult",
    "create_media_source",
]
