"""Storage backend protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from yt2notion.models.base import NoteBundle, VideoMeta


class Storage(Protocol):
    """Persist a source/A/B note bundle."""

    def save_note_bundle(self, bundle: NoteBundle, metadata: VideoMeta) -> str:
        """Save a note bundle and return the source note path."""
        ...
