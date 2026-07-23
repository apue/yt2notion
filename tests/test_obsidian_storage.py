"""Tests for Obsidian bundle storage."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from yt2notion.models.base import NoteBundle, NoteDocument, VideoMeta
from yt2notion.storage.obsidian import (
    ObsidianStorage,
    ObsidianStorageError,
    _sanitize_title,
)


@pytest.fixture
def metadata() -> VideoMeta:
    return VideoMeta(
        video_id="abc123",
        title="But what is a GPT?",
        channel="3Blue1Brown",
        url="https://www.youtube.com/watch?v=abc123",
        duration_seconds=1574,
    )


@pytest.fixture
def bundle() -> NoteBundle:
    return NoteBundle(
        source=NoteDocument(
            title="Edited Source Title",
            markdown="# Source\n\n轻索引内容。",
            tags=["AI", "math"],
            variant="source",
        ),
        guide=NoteDocument(
            title="Guide",
            markdown="# Guide\n\nA 版内容。",
            tags=["AI", "guide"],
            variant="a_guide",
        ),
        longform=NoteDocument(
            title="Longform",
            markdown="# Longform\n\nB 版内容。",
            tags=["AI", "longform"],
            variant="b_longform",
        ),
        stable_tags=["AI", "math"],
        source_topics=["attention", "embedding"],
    )


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ('foo/bar\\baz:qux*"<>|', "foobarbazqux"),
        ("foo[bar]#baz", "foobarbaz"),
        ("如何理解 GPT 模型", "如何理解 GPT 模型"),
        (":::", "Untitled"),
    ],
)
def test_sanitize_title(title: str, expected: str) -> None:
    assert _sanitize_title(title) == expected


def test_sanitize_title_truncates() -> None:
    assert len(_sanitize_title("A" * 200)) == 100


def test_invalid_vault_path(tmp_path: Path) -> None:
    with pytest.raises(ObsidianStorageError, match="does not exist"):
        ObsidianStorage(str(tmp_path / "missing"))


def test_save_bundle_writes_three_linked_notes(
    tmp_path: Path,
    metadata: VideoMeta,
    bundle: NoteBundle,
) -> None:
    source_path = Path(ObsidianStorage(str(tmp_path)).save_note_bundle(bundle, metadata))
    today = date.today().isoformat()
    safe_title = _sanitize_title(metadata.title)
    guide_path = source_path.with_name(f"{today} {safe_title} - 导读.md")
    longform_path = source_path.with_name(f"{today} {safe_title} - 扩展.md")

    assert source_path.name == f"{today} {safe_title}.md"
    assert guide_path.exists()
    assert longform_path.exists()

    source_text = source_path.read_text(encoding="utf-8")
    guide_text = guide_path.read_text(encoding="utf-8")
    longform_text = longform_path.read_text(encoding="utf-8")
    source_frontmatter = yaml.safe_load(source_text.split("---", 2)[1])

    assert source_frontmatter["source_url"] == metadata.url
    assert source_frontmatter["title"] == "Edited Source Title"
    assert source_frontmatter["media_type"] == "youtube"
    assert source_frontmatter["duration"] == "26:14"
    assert source_frontmatter["variant"] == "source"
    assert f"[[{guide_path.stem}]]" in source_text
    assert f"[[{longform_path.stem}]]" in source_text
    assert f"[[{source_path.stem}]]" in guide_text
    assert f"[[{source_path.stem}]]" in longform_text
    assert "轻索引内容。" in source_text
    assert "A 版内容。" in guide_text
    assert "B 版内容。" in longform_text


def test_save_bundle_uses_metadata_title_for_filename(
    tmp_path: Path,
    metadata: VideoMeta,
    bundle: NoteBundle,
) -> None:
    result = Path(ObsidianStorage(str(tmp_path)).save_note_bundle(bundle, metadata))

    assert _sanitize_title(metadata.title) in result.name
    assert _sanitize_title(bundle.source.title) not in result.name


def test_save_bundle_resolves_three_file_conflicts_together(
    tmp_path: Path,
    metadata: VideoMeta,
    bundle: NoteBundle,
) -> None:
    storage = ObsidianStorage(str(tmp_path))

    first = Path(storage.save_note_bundle(bundle, metadata))
    second = Path(storage.save_note_bundle(bundle, metadata))

    assert first != second
    assert second.stem.endswith("-2")
    assert second.with_name(f"{second.stem} - 导读.md").exists()
    assert second.with_name(f"{second.stem} - 扩展.md").exists()


def test_custom_summary_directory(
    tmp_path: Path,
    metadata: VideoMeta,
    bundle: NoteBundle,
) -> None:
    result = ObsidianStorage(str(tmp_path), summaries_dir="custom/notes").save_note_bundle(
        bundle,
        metadata,
    )

    assert "custom/notes" in result


def test_podcast_frontmatter(
    tmp_path: Path,
    bundle: NoteBundle,
) -> None:
    metadata = VideoMeta(
        video_id="pod1",
        title="Podcast",
        channel="Acquired",
        url="https://podcasts.apple.com/episode",
        duration_seconds=3600,
    )

    result = Path(ObsidianStorage(str(tmp_path)).save_note_bundle(bundle, metadata))
    frontmatter = yaml.safe_load(result.read_text(encoding="utf-8").split("---", 2)[1])

    assert frontmatter["media_type"] == "podcast"
