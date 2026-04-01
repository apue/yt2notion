"""Tests for prompt template loading."""

from __future__ import annotations

import pytest

from yt2notion.prompts import load_prompt


def test_load_summarize_prompt():
    prompt = load_prompt("summarize")
    assert "timestamp" in prompt.lower()
    assert "JSON" in prompt


def test_load_chinese_prompt():
    prompt = load_prompt("chinese")
    assert "中文" in prompt


def test_load_nonexistent_prompt():
    with pytest.raises(FileNotFoundError):
        load_prompt("nonexistent_prompt")


def test_render_prompt_no_vars():
    # Summarize and chinese prompts don't use {vars}, should load fine
    prompt = load_prompt("summarize")
    assert len(prompt) > 0


def test_load_extract_entities():
    from yt2notion.prompts import load_prompt

    text = load_prompt("extract_entities")
    assert "entities" in text
    assert "linkable" in text


def test_load_reduce_entities():
    from yt2notion.prompts import load_prompt

    text = load_prompt("reduce_entities")
    assert "deduplicate" in text.lower() or "merge" in text.lower() or "consolidat" in text.lower()
