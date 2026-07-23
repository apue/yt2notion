"""Tests for storage composition."""

import pytest

from yt2notion.storage import create_storage
from yt2notion.storage.obsidian import ObsidianStorage


def test_create_obsidian(tmp_path) -> None:
    storage = create_storage(
        {"storage": {"backend": "obsidian", "obsidian": {"vault_path": str(tmp_path)}}}
    )

    assert isinstance(storage, ObsidianStorage)


def test_unknown_backend_raises() -> None:
    with pytest.raises(ValueError, match="Unknown storage backend"):
        create_storage({"storage": {"backend": "dropbox"}})
