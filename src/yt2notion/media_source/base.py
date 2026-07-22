"""Media acquisition Protocol and typed request/result objects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, TypeAlias

if TYPE_CHECKING:
    from yt2notion.models.base import VideoMeta
    from yt2notion.workspace import Workspace

AcquisitionProfile = Literal["content", "transcript"]


@dataclass(frozen=True)
class MediaAcquireRequest:
    """Request for acquiring source metadata and local media artifacts."""

    url: str
    workspace_base_dir: Path
    profile: AcquisitionProfile
    keep_video: bool = True


@dataclass(frozen=True)
class ContentMediaAcquireResult:
    """Artifacts produced for the content-preparation use case."""

    metadata: VideoMeta
    workspace: Workspace
    audio_path: Path | None = None
    subtitle_path: Path | None = None
    subtitle_source: str | None = None


@dataclass(frozen=True)
class TranscriptMediaAcquireResult:
    """Artifacts produced for the transcript-only use case."""

    metadata: VideoMeta
    workspace: Workspace
    audio_path: Path
    video_path: Path | None = None


MediaAcquireResult: TypeAlias = ContentMediaAcquireResult | TranscriptMediaAcquireResult


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
