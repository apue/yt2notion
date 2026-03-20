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
