"""Public contracts shared by typed product pipelines."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypeAlias

if TYPE_CHECKING:
    from yt2notion.models.base import NoteBundle, VideoMeta
    from yt2notion.storage.base import Storage
    from yt2notion.workspace import Workspace

ProgressEvent: TypeAlias = Literal[
    "started",
    "completed",
    "skipped",
    "failed",
    "chunk_started",
    "chunk_completed",
    "hourly_wait",
    "daily_fallback_switch",
]
ProgressCallback: TypeAlias = Callable[[str, ProgressEvent, str | None], None]
StorageFactory: TypeAlias = Callable[[dict], "Storage"]


@dataclass
class PreparedContent:
    """Bundle-only pipeline output before explicit storage publish."""

    metadata: VideoMeta
    note_bundle: NoteBundle
    workspace: Workspace
    is_long: bool


def emit_progress(
    progress_callback: ProgressCallback | None,
    step: str,
    event: ProgressEvent,
    message: str | None = None,
) -> None:
    """Emit a typed progress event when a callback is configured."""
    if progress_callback is not None:
        progress_callback(step, event, message)
