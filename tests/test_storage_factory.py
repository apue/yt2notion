"""Tests for storage backend factory."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from yt2notion.storage import create_storage


@patch("yt2notion.storage.notion._NotionClient")
def test_create_notion(mock_client):
    config = {"storage": {"backend": "notion", "notion": {"token": "t", "database_id": "d"}}}
    storage = create_storage(config)
    from yt2notion.storage.notion import NotionStorage

    assert isinstance(storage, NotionStorage)


def test_create_obsidian():
    config = {"storage": {"backend": "obsidian", "obsidian": {"vault_path": "/tmp/vault"}}}
    storage = create_storage(config)
    from yt2notion.storage.obsidian import ObsidianStorage

    assert isinstance(storage, ObsidianStorage)


def test_unknown_backend_raises():
    config = {"storage": {"backend": "dropbox"}}
    with pytest.raises(ValueError, match="Unknown storage backend"):
        create_storage(config)
