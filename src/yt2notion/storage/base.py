"""Storage backend protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from yt2notion.models.base import ChineseContent, EntityResult, VideoMeta


class Storage(Protocol):
    """Protocol for storage backends that persist processed content."""

    def save(
        self,
        content: ChineseContent,
        metadata: VideoMeta,
        *,
        transcript_segments: list[dict] | None = None,
        entities: EntityResult | None = None,
    ) -> str:
        """Save content and return a URL or path to the created resource."""
        ...

    def add_transcript_subpage(
        self,
        summary_ref: str,
        transcript_segments: list[dict],
        metadata: VideoMeta,
    ) -> None:
        """Add transcript as child of summary. summary_ref is the value returned by save()."""
        ...
