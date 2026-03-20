"""Storage backend protocol."""

from __future__ import annotations

from typing import Protocol

from yt2notion.models.base import ChineseContent, VideoMeta


class Storage(Protocol):
    """Protocol for storage backends that persist processed content."""

    def save(self, content: ChineseContent, metadata: VideoMeta) -> str:
        """Save content and return a URL or path to the created resource."""
        ...
