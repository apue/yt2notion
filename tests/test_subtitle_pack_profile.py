"""Offline observability contracts for subtitle-pack runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.subtitle_pack_support import (
    ScriptedSubtitleCaller,
    make_transcription,
    successful_caller,
)
from yt2notion.subtitle_pack.service import SubtitlePackService


def test_keyboard_interrupt_marks_run_stage_and_call_failed(tmp_path: Path) -> None:
    transcription = make_transcription(tmp_path, source_kind="automatic_caption")

    with pytest.raises(KeyboardInterrupt):
        SubtitlePackService(
            ScriptedSubtitleCaller(KeyboardInterrupt()),
            model_label="fake:model",
            target_language="zh-CN",
        ).run(transcription)

    profiles = list((transcription.workspace.dir / "profiles").glob("*.json"))
    assert len(profiles) == 1
    profile = json.loads(profiles[0].read_text(encoding="utf-8"))
    assert profile["status"] == "failed"
    assert profile["error_type"] == "KeyboardInterrupt"
    assert profile["stages"][-1]["status"] == "failed"
    assert profile["llm_calls"][-1]["status"] == "failed"


def test_progress_reports_stage_and_timed_llm_events(tmp_path: Path) -> None:
    messages: list[str] = []

    SubtitlePackService(
        successful_caller(),
        model_label="fake:model",
        target_language="zh-CN",
        progress_callback=messages.append,
    ).run(make_transcription(tmp_path, source_kind="manual_subtitle"))

    assert "Subtitle pack: 2 source cues (manual_subtitle)" in messages
    assert any(
        message.startswith("LLM context_section context-001: started") for message in messages
    )
    assert any("semantic_quality" in message and "completed in" in message for message in messages)
    assert any(message.startswith("Subtitle pack: complete (") for message in messages)
