"""Storage backend protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from yt2notion.models.base import ChineseContent, VideoMeta


class Storage(Protocol):
    """Protocol for storage backends that persist processed content."""

    def save(
        self,
        content: ChineseContent,
        metadata: VideoMeta,
        *,
        transcript_segments: list[dict] | None = None,
    ) -> str:
        """Save content and return a URL or path to the created resource."""
        ...
