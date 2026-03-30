"""Tests for Obsidian storage backend."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from yt2notion.models.base import ChineseContent, VideoMeta
from yt2notion.storage.obsidian import (
    ObsidianStorage,
    ObsidianStorageError,
    _format_duration,
    _make_timestamp_link,
    _sanitize_title,
)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Create a temporary vault directory."""
    return tmp_path


@pytest.fixture
def meta() -> VideoMeta:
    return VideoMeta(
        video_id="abc123",
        title="But what is a GPT?",
        channel="3Blue1Brown",
        upload_date="20240315",
        url="https://www.youtube.com/watch?v=abc123",
        duration_seconds=1574,
        subtitles_available=True,
    )


@pytest.fixture
def content() -> ChineseContent:
    return ChineseContent(
        overview="这是一期关于 GPT 的视频。",
        key_points=[
            {"timestamp": "5:30", "title": "Embedding 的几何含义", "summary": "把词映射到高维空间"},
            {"timestamp": "12:45", "title": "Attention 的本质", "summary": "信息路由机制"},
        ],
        tags=["AI", "数学"],
        raw_markdown="raw md content",
    )


@pytest.fixture
def segments() -> list[dict]:
    return [
        {
            "title": "Embedding 的几何含义",
            "start_seconds": 330,
            "end_seconds": 765,
            "text": "逐段校对后的原文关于 embedding...",
            "source": "subtitle",
        },
        {
            "title": "Attention 的本质",
            "start_seconds": 765,
            "end_seconds": 1200,
            "text": "逐段校对后的原文关于 attention...",
            "source": "subtitle",
        },
    ]


# --- sanitize_title ---


class TestSanitizeTitle:
    def test_removes_unsafe_chars(self):
        assert _sanitize_title('foo/bar\\baz:qux*"<>|') == "foobarbazqux"

    def test_truncates_long_title(self):
        long = "A" * 200
        assert len(_sanitize_title(long)) == 100

    def test_preserves_chinese(self):
        assert _sanitize_title("如何理解 GPT 模型") == "如何理解 GPT 模型"

    def test_empty_title(self):
        assert _sanitize_title("") == "Untitled"
        assert _sanitize_title(":::") == "Untitled"

    def test_strips_whitespace(self):
        assert _sanitize_title("  hello  ") == "hello"


# --- format_duration ---


class TestFormatDuration:
    def test_short(self):
        assert _format_duration(300) == "5:00"

    def test_with_hours(self):
        assert _format_duration(3661) == "1:01:01"

    def test_zero(self):
        assert _format_duration(0) == "0:00"


# --- timestamp_link ---


class TestTimestampLink:
    def test_youtube_watch_url(self):
        link = _make_timestamp_link("5:30", "https://www.youtube.com/watch?v=abc123")
        assert link == "[5:30](https://youtube.com/watch?v=abc123&t=330)"

    def test_youtube_short_url(self):
        link = _make_timestamp_link("5:30", "https://youtu.be/abc123")
        assert link == "[5:30](https://youtube.com/watch?v=abc123&t=330)"

    def test_podcast_no_link(self):
        link = _make_timestamp_link("5:30", "https://podcasts.apple.com/some/podcast")
        assert link == "[5:30]"


# --- ObsidianStorage init ---


class TestObsidianStorageInit:
    def test_invalid_vault_path(self, tmp_path: Path):
        with pytest.raises(ObsidianStorageError, match="does not exist"):
            ObsidianStorage(vault_path=str(tmp_path / "nonexistent"))

    def test_valid_vault_path(self, vault: Path):
        storage = ObsidianStorage(vault_path=str(vault))
        assert storage.vault_path == vault


# --- save ---


class TestSave:
    def test_creates_summary_and_transcript(
        self, vault: Path, meta: VideoMeta, content: ChineseContent, segments: list[dict]
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, transcript_segments=segments)

        summary_path = Path(result)
        assert summary_path.exists()
        assert summary_path.parent.name == "summaries"

        # Transcript should also exist
        transcript_dir = vault / "yt2notion" / "transcripts"
        transcript_files = list(transcript_dir.glob("T-*.md"))
        assert len(transcript_files) == 1

    def test_summary_without_transcript(
        self, vault: Path, meta: VideoMeta, content: ChineseContent
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, transcript_segments=None)

        assert Path(result).exists()
        transcript_dir = vault / "yt2notion" / "transcripts"
        # Directory created but no files
        assert not list(transcript_dir.glob("*.md"))

    def test_summary_frontmatter_valid_yaml(
        self, vault: Path, meta: VideoMeta, content: ChineseContent, segments: list[dict]
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, transcript_segments=segments)

        text = Path(result).read_text(encoding="utf-8")
        # Extract frontmatter between ---
        parts = text.split("---", 2)
        fm = yaml.safe_load(parts[1])

        assert fm["source_url"] == meta.url
        assert fm["channel"] == "3Blue1Brown"
        assert fm["media_type"] == "youtube"
        assert fm["tags"] == ["AI", "数学"]
        assert "[[T-" in fm["transcript"]

    def test_summary_body_has_source_credit(
        self, vault: Path, meta: VideoMeta, content: ChineseContent
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta)

        text = Path(result).read_text(encoding="utf-8")
        assert "**3Blue1Brown**" in text
        assert "原始视频" in text
        assert meta.url in text

    def test_summary_key_points_with_timestamp_links(
        self, vault: Path, meta: VideoMeta, content: ChineseContent
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta)

        text = Path(result).read_text(encoding="utf-8")
        assert "[5:30](https://youtube.com/watch?v=abc123&t=330)" in text
        assert "**Embedding 的几何含义**" in text

    def test_transcript_frontmatter_and_wikilinks(
        self, vault: Path, meta: VideoMeta, content: ChineseContent, segments: list[dict]
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, transcript_segments=segments)

        transcript_dir = vault / "yt2notion" / "transcripts"
        transcript_file = list(transcript_dir.glob("T-*.md"))[0]
        text = transcript_file.read_text(encoding="utf-8")

        # Check frontmatter
        parts = text.split("---", 2)
        fm = yaml.safe_load(parts[1])
        assert fm["type"] == "transcript"
        assert "[[" in fm["parent"]  # wikilink to summary

        # Check segment content
        assert "## Embedding 的几何含义 (5:30-12:45)" in text
        assert "## Attention 的本质 (12:45-20:00)" in text

    def test_wikilinks_are_bidirectional(
        self, vault: Path, meta: VideoMeta, content: ChineseContent, segments: list[dict]
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, transcript_segments=segments)

        summary_text = Path(result).read_text(encoding="utf-8")
        transcript_file = list((vault / "yt2notion" / "transcripts").glob("T-*.md"))[0]
        transcript_text = transcript_file.read_text(encoding="utf-8")

        # Summary links to transcript
        assert f"[[{transcript_file.stem}]]" in summary_text
        # Transcript links to summary
        assert f"[[{Path(result).stem}]]" in transcript_text

    def test_filename_conflict_appends_suffix(
        self, vault: Path, meta: VideoMeta, content: ChineseContent
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result1 = storage.save(content, meta)
        result2 = storage.save(content, meta)

        assert result1 != result2
        assert Path(result1).exists()
        assert Path(result2).exists()
        assert "-2" in Path(result2).stem

    def test_utf8_encoding(self, vault: Path, content: ChineseContent):
        meta = VideoMeta(
            video_id="cn123",
            title="如何理解 Transformer",
            channel="中文频道",
            url="https://youtube.com/watch?v=cn123",
            duration_seconds=600,
        )
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta)

        text = Path(result).read_text(encoding="utf-8")
        assert "如何理解 Transformer" in text
        assert "中文频道" in text

    def test_custom_dirs(self, vault: Path, meta: VideoMeta, content: ChineseContent):
        storage = ObsidianStorage(
            vault_path=str(vault),
            summaries_dir="custom/sums",
            transcripts_dir="custom/trans",
        )
        result = storage.save(content, meta)
        assert "custom/sums" in result

    def test_podcast_url_no_timestamp_links(self, vault: Path, content: ChineseContent):
        meta = VideoMeta(
            video_id="pod1",
            title="Some Podcast Episode",
            channel="Acquired",
            url="https://podcasts.apple.com/some/episode",
            duration_seconds=3600,
        )
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta)

        text = Path(result).read_text(encoding="utf-8")
        # Podcast timestamps should be plain, not hyperlinked
        assert "[5:30]" in text
        assert "youtube.com" not in text.split("---", 2)[2]  # body only


# --- add_transcript_subpage ---


class TestAddTranscriptSubpage:
    def test_adds_transcript_after_save(
        self, vault: Path, meta: VideoMeta, content: ChineseContent, segments: list[dict]
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        # Save without transcript (long content scenario)
        result = storage.save(content, meta, transcript_segments=None)

        # Simulate deferred transcript addition
        storage.add_transcript_subpage(result, segments, meta)

        transcript_dir = vault / "yt2notion" / "transcripts"
        transcript_files = list(transcript_dir.glob("T-*.md"))
        assert len(transcript_files) == 1

        # Check transcript content
        text = transcript_files[0].read_text(encoding="utf-8")
        assert "## Embedding 的几何含义" in text


# --- config validation ---


class TestConfigValidation:
    def test_obsidian_config_in_create_storage(self, vault: Path):
        from yt2notion.storage import create_storage

        config = {
            "storage": {
                "backend": "obsidian",
                "obsidian": {
                    "vault_path": str(vault),
                },
            },
        }
        storage = create_storage(config)
        assert isinstance(storage, ObsidianStorage)
        assert storage.summaries_dir == "yt2notion/summaries"

    def test_missing_vault_path_in_load_config(self, tmp_path: Path):
        from yt2notion.config import ConfigError, load_config

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "model:\n  backend: claude_code\nstorage:\n  backend: obsidian\n  obsidian:\n    vault_path: ''\n"
        )
        with pytest.raises(ConfigError, match="vault_path is required"):
            load_config(str(config_file))
