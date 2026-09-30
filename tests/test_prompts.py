"""Tests for active prompt template loading."""

from __future__ import annotations

import pytest

from yt2notion.prompts import load_prompt, render_prompt


def test_load_nonexistent_prompt():
    with pytest.raises(FileNotFoundError):
        load_prompt("nonexistent_prompt")


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
