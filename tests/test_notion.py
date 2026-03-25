"""Tests for Notion storage backend."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from yt2notion.models.base import ChineseContent, VideoMeta
from yt2notion.storage.notion import NotionStorage, _split_text, _timestamp_to_seconds


@pytest.fixture
def meta():
    return VideoMeta(
        video_id="abc123",
        title="5 Hip Flexor Exercises",
        channel="FitnessPro",
        url="https://www.youtube.com/watch?v=abc123",
        upload_date="20260319",
    )


@pytest.fixture
def content():
    return ChineseContent(
        overview="这是一个关于髋关节训练的视频",
        key_points=[
            {"timestamp": "0:00", "title": "髋关节结构", "summary": "讲解髋关节基本结构"},
            {"timestamp": "2:04", "title": "强化训练", "summary": "五个针对髂腰肌的训练动作"},
        ],
        tags=["髋关节灵活性", "力量训练"],
        raw_markdown="...",
    )


@pytest.fixture
def rules():
    return [
        {"match": ["muscle", "stretch", "训练", "健身"], "parent": "健身/训练笔记"},
        {"match": ["AI", "LLM"], "parent": "技术/AI"},
        {"default": "收件箱"},
    ]


@patch("yt2notion.storage.notion._NotionClient")
def test_build_properties(mock_client, content, meta):
    storage = NotionStorage(token="test", database_id="db123")
    props = storage._build_page_properties(content, meta)
    assert props["title"]["title"][0]["text"]["content"] == "这是一个关于髋关节训练的视频"
    assert props["URL"]["url"] == meta.url
    assert len(props["Tags"]["multi_select"]) == 2


@patch("yt2notion.storage.notion._NotionClient")
def test_build_blocks(mock_client, content, meta):
    storage = NotionStorage(token="test", database_id="db123")
    blocks = storage._build_blocks(content, meta)
    # credit callout + headings + overview + 2 key points + tags
    assert blocks[0].get("callout") is not None  # credit block
    assert any(b.get("heading_2") for b in blocks)
    bullet_items = [b for b in blocks if b.get("bulleted_list_item")]
    assert len(bullet_items) == 2


@patch("yt2notion.storage.notion._NotionClient")
def test_credit_block_content(mock_client, meta):
    storage = NotionStorage(token="test", database_id="db123")
    block = storage._make_credit_block(meta)
    text = block["callout"]["rich_text"][0]["text"]["content"]
    assert "FitnessPro" in text
    assert "5 Hip Flexor Exercises" in text
    assert meta.url in text


@patch("yt2notion.storage.notion._NotionClient")
def test_directory_routing(mock_client, rules):
    storage = NotionStorage(token="test", database_id="db123", directory_rules=rules)
    assert storage.route_directory(["力量训练"], "训练视频") == "健身/训练笔记"


@patch("yt2notion.storage.notion._NotionClient")
def test_directory_routing_default(mock_client, rules):
    storage = NotionStorage(token="test", database_id="db123", directory_rules=rules)
    assert storage.route_directory(["cooking"], "recipe") == "收件箱"


def test_long_block_split():
    text = "A" * 5000
    chunks = _split_text(text, 2000)
    assert len(chunks) >= 3
    assert all(len(c) <= 2000 for c in chunks)
    assert "".join(chunks) == text


def test_timestamp_to_seconds():
    assert _timestamp_to_seconds("0:00") == 0
    assert _timestamp_to_seconds("2:04") == 124
    assert _timestamp_to_seconds("10:30") == 630


@patch("yt2notion.storage.notion._NotionClient")
def test_save_calls_api(mock_client_cls, content, meta):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.pages.create.return_value = {"id": "page123", "url": "https://notion.so/page123"}

    storage = NotionStorage(token="test", database_id="db123")
    url = storage.save(content, meta)

    assert url == "https://notion.so/page123"
    mock_client.pages.create.assert_called_once()
    call_kwargs = mock_client.pages.create.call_args[1]
    assert call_kwargs["parent"]["database_id"] == "db123"
