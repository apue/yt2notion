"""Typed contracts for source probe and provider operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from yt2notion.models.base import VideoMeta
    from yt2notion.workspace import Workspace

SourceOperation = Literal["subtitle", "webpage_transcript", "audio", "video"]
SourceFailureCategory = Literal[
    "unavailable",
    "authentication",
    "local_resource",
    "transient",
    "provider",
]


@dataclass(frozen=True)
class SourceProbe:
    """Lightweight metadata and capability observation."""

    locator: str
    metadata: VideoMeta

    @property
    def subtitles_available(self) -> bool:
        """Return whether the probe observed a subtitle capability."""
        return self.metadata.subtitles_available


@dataclass(frozen=True)
class OperationResult:
    """Local artifacts produced by one source-provider operation."""

    audio_path: Path | None = None
    subtitle_path: Path | None = None
    subtitle_source: str | None = None
    video_path: Path | None = None


@dataclass(frozen=True)
class AcquiredMedia:
    """Metadata and local artifacts produced by an acquisition plan."""

    metadata: VideoMeta
    workspace: Workspace
    audio_path: Path | None = None
    subtitle_path: Path | None = None
    subtitle_source: str | None = None
    video_path: Path | None = None


class SourceOperationError(RuntimeError):
    """Normalized provider failure used by acquisition policy."""

    def __init__(
        self,
        operation: str,
        category: SourceFailureCategory,
        cause: Exception | str,
    ) -> None:
        self.operation = operation
        self.category = category
        self.cause = cause
        super().__init__(str(cause))


class AcquisitionError(RuntimeError):
    """Expose the created workspace when acquisition cannot complete."""

    def __init__(self, workspace: Workspace, cause: Exception) -> None:
        super().__init__(str(cause))
        self.workspace = workspace
        self.cause = cause


class SourceProvider(Protocol):
    """Observe a locator and materialize one requested operation into a workspace."""

    def probe(self, locator: str) -> SourceProbe:
        """Observe metadata and capabilities without downloading large media."""
        ...

    def execute(
        self,
        operation: SourceOperation,
        probe: SourceProbe,
        workspace: Workspace,
    ) -> OperationResult:
        """Execute one planned provider operation."""
        ...
