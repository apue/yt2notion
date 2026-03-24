"""Tests for new parsers: chunk summary and synthesized markdown."""

from __future__ import annotations

import pytest

from yt2notion.models._parsers import (
    ParseError,
    parse_chunk_summary_json,
    parse_synthesized_markdown,
)


class TestParseChunkSummaryJson:
    def test_basic_parsing(self):
        text = """{
  "segment_title": "Introduction",
  "timestamp": "0:00",
  "timestamp_seconds": 0,
  "summary": "The host introduces the guest.",
  "key_points": [
    {"timestamp": "0:30", "timestamp_seconds": 30, "point": "Guest background"}
  ],
  "key_terms": ["AI", "research"]
}"""
        result = parse_chunk_summary_json(text)
        assert result.segment_title == "Introduction"
        assert result.timestamp == "0:00"
        assert result.summary == "The host introduces the guest."
        assert len(result.key_points) == 1
        assert result.key_terms == ["AI", "research"]

    def test_with_code_fence(self):
        text = """Here is the summary:

```json
{
  "segment_title": "Test",
  "timestamp": "5:00",
  "timestamp_seconds": 300,
  "summary": "A test segment."
}
```"""
        result = parse_chunk_summary_json(text)
        assert result.segment_title == "Test"
        assert result.timestamp_seconds == 300

    def test_invalid_json_raises(self):
        with pytest.raises(ParseError, match="Failed to parse chunk summary"):
            parse_chunk_summary_json("not valid json {{{")


class TestParseSynthesizedMarkdown:
    def test_with_mindmap(self):
        text = """## 概要

这是一个关于AI的访谈，涵盖了多个重要话题。

## 关键节点

- [0:00] **开场介绍**：主持人介绍了嘉宾背景
- [5:30] **AI研究**：讨论了最新的AI研究进展

## 思维导图

```markmap
- AI访谈
  - 学术背景
    - 计算机视觉
    - 深度学习
  - 创业经历
    - AMI Labs
```

## 标签

人工智能, 深度学习, 创业
"""
        result = parse_synthesized_markdown(text)
        assert "AI" in result.overview
        assert len(result.key_points) == 2
        assert result.key_points[0]["title"] == "开场介绍"
        assert len(result.tags) == 3
        assert "AI访谈" in result.mindmap
        assert "计算机视觉" in result.mindmap

    def test_without_mindmap(self):
        text = """## 概要

简短概要。

## 关键节点

- [0:00] **标题**：内容

## 标签

标签一
"""
        result = parse_synthesized_markdown(text)
        assert result.mindmap == ""
        assert result.overview == "简短概要。"
