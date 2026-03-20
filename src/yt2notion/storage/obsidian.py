"""Obsidian storage backend. Writes markdown files to vault."""

from __future__ import annotations

from yt2notion.models.base import ChineseContent, VideoMeta


class ObsidianStorage:
    """Obsidian vault storage. Not yet implemented — PRs welcome!"""

    def __init__(self, vault_path: str, folder: str = "YouTube Notes") -> None:
        self.vault_path = vault_path
        self.folder = folder

    def save(self, content: ChineseContent, metadata: VideoMeta) -> str:
        raise NotImplementedError(
            "Obsidian storage is not yet implemented. "
            "See src/yt2notion/storage/base.py for the Protocol. PRs welcome!"
        )
