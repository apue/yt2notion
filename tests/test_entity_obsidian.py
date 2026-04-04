"""Tests for entity rendering in Obsidian output."""

from __future__ import annotations

from pathlib import Path

import pytest

from yt2notion.models.base import ChineseContent, Entity, EntityResult, VideoMeta
from yt2notion.storage.obsidian import ObsidianStorage


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def meta() -> VideoMeta:
    return VideoMeta(
        video_id="abc123",
        title="Bangkok Food Tour",
        channel="Mark Wiens",
        upload_date="20240315",
        url="https://www.youtube.com/watch?v=abc123",
        duration_seconds=1574,
        subtitles_available=True,
    )


@pytest.fixture
def content() -> ChineseContent:
    return ChineseContent(
        overview="曼谷美食之旅。",
        key_points=[
            {"timestamp": "5:30", "title": "Gaggan 餐厅", "summary": "创新印度菜"},
        ],
        tags=["美食", "曼谷"],
        raw_markdown="raw md",
    )


@pytest.fixture
def entities() -> EntityResult:
    return EntityResult(
        domain="food/dining",
        is_entity_centric=True,
        entity_types=["restaurant", "dish", "person", "city"],
        entities=[
            Entity(
                name="Gaggan",
                type="restaurant",
                attributes={"city": "Bangkok", "cuisine": "Progressive Indian"},
                linkable=True,
            ),
            Entity(name="Gaggan Anand", type="person", attributes={"role": "chef"}, linkable=True),
            Entity(name="Curry Crab", type="dish", attributes={}, linkable=False),
            Entity(name="Bangkok", type="city", attributes={}, linkable=True),
        ],
        relations=[
            {"from": "Gaggan Anand", "relation": "runs", "to": "Gaggan"},
            {"from": "Gaggan", "relation": "serves", "to": "Curry Crab"},
            {"from": "Gaggan", "relation": "located_in", "to": "Bangkok"},
        ],
    )


class TestEntityRendering:
    def test_entities_section_in_output(
        self, vault: Path, meta: VideoMeta, content: ChineseContent, entities: EntityResult
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, entities=entities)
        text = Path(result).read_text(encoding="utf-8")
        assert "## Entities" in text

    def test_entities_grouped_by_type(
        self, vault: Path, meta: VideoMeta, content: ChineseContent, entities: EntityResult
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, entities=entities)
        text = Path(result).read_text(encoding="utf-8")
        assert "**Restaurant**" in text
        assert "**Person**" in text
        assert "**City**" in text

    def test_linkable_entities_get_wikilinks(
        self, vault: Path, meta: VideoMeta, content: ChineseContent, entities: EntityResult
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, entities=entities)
        text = Path(result).read_text(encoding="utf-8")
        assert "[[Gaggan]]" in text
        assert "[[Gaggan Anand]]" in text
        assert "[[Bangkok]]" in text
        # Non-linkable should NOT have wiki-links
        assert "[[Curry Crab]]" not in text
        assert "Curry Crab" in text  # but still mentioned

    def test_entity_attributes_shown(
        self, vault: Path, meta: VideoMeta, content: ChineseContent, entities: EntityResult
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, entities=entities)
        text = Path(result).read_text(encoding="utf-8")
        assert "Bangkok" in text  # Gaggan's city attribute

    def test_no_entities_section_when_none(
        self, vault: Path, meta: VideoMeta, content: ChineseContent
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, entities=None)
        text = Path(result).read_text(encoding="utf-8")
        assert "## Entities" not in text

    def test_non_entity_centric_shows_minimal(
        self, vault: Path, meta: VideoMeta, content: ChineseContent
    ):
        entities = EntityResult(
            domain="tech",
            is_entity_centric=False,
            entity_types=["tool"],
            entities=[
                Entity(name="Python", type="tool", linkable=True),
                Entity(name="Rust", type="tool", linkable=True),
            ],
            relations=[],
        )
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, entities=entities)
        text = Path(result).read_text(encoding="utf-8")
        # Non-entity-centric: one-liner "Mentioned: ..." instead of full section
        assert "Mentioned:" in text
        assert "[[Python]]" in text
        assert "[[Rust]]" in text

    def test_entities_before_tags(
        self, vault: Path, meta: VideoMeta, content: ChineseContent, entities: EntityResult
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, entities=entities)
        text = Path(result).read_text(encoding="utf-8")
        entities_pos = text.index("## Entities")
        tags_pos = text.index("## 标签")
        assert entities_pos < tags_pos

    def test_empty_entities_no_section(self, vault: Path, meta: VideoMeta, content: ChineseContent):
        entities = EntityResult(
            domain="",
            is_entity_centric=False,
            entity_types=[],
            entities=[],
            relations=[],
        )
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, entities=entities)
        text = Path(result).read_text(encoding="utf-8")
        assert "## Entities" not in text
