"""Tests for active prompt template loading."""

from __future__ import annotations

import pytest

from yt2notion.prompts import load_prompt, render_prompt


def test_load_nonexistent_prompt():
    with pytest.raises(FileNotFoundError):
        load_prompt("nonexistent_prompt")


def test_load_review_prompt():
    text = load_prompt("review")
    assert "transcript" in text.lower() or "转录" in text


def test_load_topic_segment_prompt():
    text = render_prompt(
        "topic_segment",
        channel="Channel",
        title="Title",
        duration_seconds="120",
        char_count="1000",
    )
    assert "Channel" in text
    assert "Title" in text


def test_load_compose_guide_prompt():
    text = load_prompt("compose_guide")
    assert "导读版" in text
    assert "a_guide" in text
    assert "<note_json>" in text
    assert "<note_markdown>" in text


def test_load_compose_longform_prompt():
    text = load_prompt("compose_longform")
    assert "扩展成稿" in text
    assert "b_longform" in text
    assert "<note_json>" in text
    assert "<note_markdown>" in text


def test_load_compose_note_metadata_prompt():
    text = load_prompt("compose_note_metadata")
    assert "stable_tags" in text
    assert "source_summary" in text
    assert "source_title" in text
