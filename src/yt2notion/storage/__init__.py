"""Storage backend factory."""

from __future__ import annotations

from typing import Any


def create_storage(config: dict) -> Any:
    """Create a Storage instance based on config.

    Returns an object conforming to the Storage Protocol.
    """
    storage_config = config.get("storage", {})
    backend = storage_config.get("backend", "notion")
    credit_config = config.get("credit", {})

    if backend == "notion":
        from yt2notion.storage.notion import NotionStorage

        notion_cfg = storage_config.get("notion", {})
        token = notion_cfg.get("token", "")
        database_id = notion_cfg.get("database_id", "")
        directory_rules = notion_cfg.get("directory_rules", [])
        credit_format = credit_config.get("format", "来源：{channel} 「{title}」\n链接：{url}")
        return NotionStorage(
            token=token,
            database_id=database_id,
            directory_rules=directory_rules,
            credit_format=credit_format,
        )
    elif backend == "obsidian":
        from yt2notion.storage.obsidian import ObsidianStorage

        obsidian_cfg = storage_config.get("obsidian", {})
        return ObsidianStorage(
            vault_path=obsidian_cfg.get("vault_path", ""),
            folder=obsidian_cfg.get("folder", "YouTube Notes"),
        )
    else:
        raise ValueError(f"Unknown storage backend: {backend!r}")
