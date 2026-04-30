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


def test_load_summarize_reviewed_prompt():
    text = load_prompt("summarize_reviewed")
    assert "ASR" in text
    assert "reviewed_transcript" in text


def test_load_summarize_reviewed_freeform_prompt():
    text = load_prompt("summarize_reviewed_freeform")
    assert "ASR" in text
    assert "reviewed_transcript" in text


def test_load_reduce_entities():
    from yt2notion.prompts import load_prompt

    text = load_prompt("reduce_entities")
    assert "deduplicate" in text.lower() or "merge" in text.lower() or "consolidat" in text.lower()


def test_load_compose_guide_prompt():
    text = load_prompt("compose_guide")
    assert "导读版" in text
    assert "a_guide" in text
    assert "target_chars" in text
    assert "JSON" in text
    assert "连续正文" in text
    assert "非列表" in text
    assert "<note_json>" in text
    assert "<note_markdown>" in text


def test_load_compose_longform_prompt():
    text = load_prompt("compose_longform")
    assert "扩展成稿" in text
    assert "b_longform" in text
    assert "target_chars" in text
    assert "guide_note" in text
    assert "JSON" in text
    assert "避免" in text or "重复" in text
    assert "<note_json>" in text
    assert "<note_markdown>" in text


def test_load_compose_note_metadata_prompt():
    text = load_prompt("compose_note_metadata")
    assert "stable_tags" in text
    assert "source_summary" in text
    assert "source_title" in text
    assert "source" in text
    assert "轻索引" in text
    assert "JSON" in text
