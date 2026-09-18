"""Offline use-case contract tests for bilingual subtitle packages."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.subtitle_pack_support import (
    ScriptedSubtitleCaller,
    context_response,
    generation_response,
    make_transcription,
    successful_caller,
)
from yt2notion.subtitle_pack.service import SubtitlePackService
from yt2notion.subtitle_pack.validation import SubtitlePackError


def test_manual_subtitles_are_translated_without_source_rewrite(tmp_path: Path) -> None:
    result = SubtitlePackService(
        successful_caller(),
        model_label="fake:model",
        target_language="zh-CN",
    ).run(make_transcription(tmp_path, source_kind="manual_subtitle"))

    package = json.loads(result.package_path.read_text(encoding="utf-8"))
    assert result.cue_count == 2
    assert package["source_kind"] == "manual_subtitle"
    assert package["cues"][1]["original_text"] == "Thank you Graeme."
    assert package["cues"][1]["source_text"] == "Thank you Graeme."
    assert package["cues"][1]["translated_text"] == "译：Thank you Graeme."
    assert "00:00:05,000 --> 00:00:09,000" in result.srt_path.read_text(encoding="utf-8")
    report = json.loads(result.quality_report_path.read_text(encoding="utf-8"))
    assert report["passed"] is True
    profile = json.loads(result.profile_path.read_text(encoding="utf-8"))
    assert profile["status"] == "completed"
    assert "Transformer" not in result.profile_path.read_text(encoding="utf-8")


def test_automatic_captions_can_be_contextually_corrected(tmp_path: Path) -> None:
    result = SubtitlePackService(
        successful_caller(corrected=True),
        model_label="fake:model",
        target_language="zh-CN",
    ).run(make_transcription(tmp_path, source_kind="automatic_caption"))

    package = json.loads(result.package_path.read_text(encoding="utf-8"))
    assert package["cues"][1]["original_text"] == "Thank you Graeme."
    assert package["cues"][1]["source_text"] == "Thank you Graham."
    reviewed = json.loads((result.workspace_dir / "reviewed_cues.json").read_text(encoding="utf-8"))
    assert reviewed[1] == {"id": "cue-000002", "source_text": "Thank you Graham."}


def test_semantic_issue_is_repaired_and_rechecked(tmp_path: Path) -> None:
    issue = json.dumps([{"id": "cue-000001", "issue": "translation is inaccurate"}])
    caller = ScriptedSubtitleCaller(
        context_response(),
        generation_response(),
        issue,
        generation_response(include_second=False),
        "[]",
    )
    result = SubtitlePackService(
        caller,
        model_label="fake:model",
        target_language="zh-CN",
    ).run(make_transcription(tmp_path, source_kind="manual_subtitle"))

    assert result.quality_passed is True
    profile = json.loads(result.profile_path.read_text(encoding="utf-8"))
    operations = [call["operation"] for call in profile["llm_calls"]]
    assert "repair" in operations
    assert "semantic_quality_after_repair" in operations


def test_malformed_quality_response_cannot_publish_package(tmp_path: Path) -> None:
    transcription = make_transcription(tmp_path, source_kind="manual_subtitle")
    caller = ScriptedSubtitleCaller(context_response(), generation_response(), "quality looks good")

    with pytest.raises(SubtitlePackError, match="semantic quality response is not valid JSON"):
        SubtitlePackService(
            caller,
            model_label="fake:model",
            target_language="zh-CN",
        ).run(transcription)

    assert not (transcription.workspace.dir / "bilingual_subtitles.json").exists()
