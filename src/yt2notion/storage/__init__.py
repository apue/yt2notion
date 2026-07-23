"""Storage backend composition."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yt2notion.storage.base import Storage


def create_storage(config: dict) -> Storage:
    """Create the configured Obsidian bundle storage adapter."""
    storage_config = config.get("storage", {})
    backend = storage_config.get("backend", "obsidian")
    if backend != "obsidian":
        raise ValueError(f"Unknown storage backend: {backend!r}")

    from yt2notion.storage.obsidian import ObsidianStorage

    obsidian_config = storage_config.get("obsidian", {})
    return ObsidianStorage(
        vault_path=obsidian_config.get("vault_path", ""),
        summaries_dir=obsidian_config.get("summaries_dir", "yt2notion/summaries"),
    )
