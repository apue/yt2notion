"""Tests for LLM-based chapter extraction."""

from __future__ import annotations

import json
from unittest.mock import patch

from yt2notion.chapter_extract import _parse_chapters_json, extract_chapters_llm


def test_parse_chapters_json_valid():
    raw = json.dumps(
        [
            {"title": "Intro", "start_seconds": 0, "end_seconds": 300},
            {"title": "Main", "start_seconds": 300, "end_seconds": 600},
        ]
    )
    chapters = _parse_chapters_json(raw, 600)
    assert len(chapters) == 2
    assert chapters[0].title == "Intro"
    assert chapters[1].end_seconds == 600


def test_parse_chapters_json_fixes_last_end():
    raw = json.dumps(
        [
            {"title": "A", "start_seconds": 0, "end_seconds": 100},
            {"title": "B", "start_seconds": 100, "end_seconds": 200},
        ]
    )
    chapters = _parse_chapters_json(raw, 500)
    assert chapters[-1].end_seconds == 500


def test_parse_chapters_json_invalid_order():
    raw = json.dumps(
        [
            {"title": "B", "start_seconds": 300, "end_seconds": 600},
            {"title": "A", "start_seconds": 0, "end_seconds": 300},
        ]
    )
    chapters = _parse_chapters_json(raw, 600)
    assert chapters == []  # Invalid ordering discarded


def test_parse_chapters_json_empty():
    assert _parse_chapters_json("[]", 100) == []


def test_parse_chapters_json_with_markdown_fences():
    raw = '```json\n[{"title": "X", "start_seconds": 0, "end_seconds": 60}]\n```'
    chapters = _parse_chapters_json(raw, 60)
    assert len(chapters) == 1


def test_extract_chapters_llm_fallback_to_regex():
    """When LLM fails, falls back to regex parsing."""
    desc = "00:00:00 Intro\n00:05:30 Main Topic\n00:10:00 Outro"

    with patch("yt2notion.chapter_extract._call_llm", side_effect=Exception("LLM failed")):
        chapters = extract_chapters_llm(desc, 600, {"model": {"backend": "claude_code"}})

    assert len(chapters) == 3
    assert chapters[0].title == "Intro"


def test_extract_chapters_llm_empty_description():
    chapters = extract_chapters_llm("", 600, {"model": {"backend": "claude_code"}})
    assert chapters == []
