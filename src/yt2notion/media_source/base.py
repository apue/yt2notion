"""Media acquisition Protocol and typed request/result objects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from yt2notion.models.base import VideoMeta
    from yt2notion.workspace import Workspace


@dataclass(frozen=True)
class MediaAcquireRequest:
    """Request for acquiring source metadata and local media artifacts."""

    url: str
    workspace_base_dir: Path
    keep_video: bool = False


@dataclass(frozen=True)
class MediaAcquireResult:
    """Metadata and local artifacts produced by subtitle-first acquisition."""

    metadata: VideoMeta
    workspace: Workspace
    audio_path: Path | None = None
    subtitle_path: Path | None = None
    subtitle_source: str | None = None
    video_path: Path | None = None


class MediaAcquisitionError(RuntimeError):
    """Expose a created workspace when acquisition fails before returning artifacts."""

    def __init__(self, workspace: Workspace, cause: Exception) -> None:
        super().__init__(str(cause))
        self.workspace = workspace
        self.cause = cause


class MediaSource(Protocol):
    """High-level source acquisition provider."""

    def acquire(self, request: MediaAcquireRequest) -> MediaAcquireResult:
        """Acquire metadata plus local subtitle/audio/video artifacts."""
        ...
