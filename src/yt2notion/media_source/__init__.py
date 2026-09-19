"""Typed source acquisition contracts, planner, and provider factory."""

from __future__ import annotations

from yt2notion.media_source.acquisition import acquire_media, plan_acquisition, route_source
from yt2notion.media_source.base import (
    AcquiredMedia,
    AcquisitionError,
    AcquisitionIntent,
    AcquisitionPlan,
    AcquisitionRequest,
    OperationResult,
    SourceFailureCategory,
    SourceOperation,
    SourceOperationError,
    SourceProbe,
    SourceProvider,
    SourceRef,
)
from yt2notion.media_source.ytdlp import YtDlpSourceProvider


def create_source_provider(config: dict, *, verbose: bool = False) -> SourceProvider:
    """Create the configured source provider."""
    source_cfg = config.get("extract", {}).get("media_source", {})
    if not isinstance(source_cfg, dict):
        raise ValueError("extract.media_source must be a mapping")
    backend = source_cfg.get("backend", "yt_dlp")
    if backend == "yt_dlp":
        return YtDlpSourceProvider(config, verbose=verbose)
    raise ValueError(f"Unknown media-source backend: {backend!r}. Supported: yt_dlp")


__all__ = [
    "AcquiredMedia",
    "AcquisitionError",
    "AcquisitionIntent",
    "AcquisitionPlan",
    "AcquisitionRequest",
    "OperationResult",
    "SourceFailureCategory",
    "SourceOperation",
    "SourceOperationError",
    "SourceProbe",
    "SourceProvider",
    "SourceRef",
    "acquire_media",
    "create_source_provider",
    "plan_acquisition",
    "route_source",
]
