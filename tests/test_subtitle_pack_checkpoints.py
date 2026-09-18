"""Offline checkpoint identity contracts for subtitle generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from tests.subtitle_pack_support import (
    ScriptedSubtitleCaller,
    context_response,
    generation_response,
    make_transcription,
    successful_caller,
)
from yt2notion.subtitle_pack import workflow as workflow_module
from yt2notion.subtitle_pack.service import SubtitlePackService

if TYPE_CHECKING:
    import pytest


def test_context_checkpoint_is_invalidated_when_metadata_changes(tmp_path: Path) -> None:
    transcription = make_transcription(tmp_path, source_kind="manual_subtitle")
    SubtitlePackService(
        successful_caller(),
        model_label="fake:model",
        target_language="zh-CN",
    ).run(transcription)

    transcription.metadata.description = "A different course and lecturer."
    second_caller = ScriptedSubtitleCaller(context_response(), generation_response(), "[]")
    SubtitlePackService(
        second_caller,
        model_label="fake:model",
        target_language="zh-CN",
    ).run(transcription)

    assert len(second_caller.calls) == 3
    context = json.loads(
        (transcription.workspace.dir / "subtitle_context.json").read_text(encoding="utf-8")
    )
    assert context["source_evidence"]["description"] == "A different course and lecturer."


def test_generation_strategy_change_invalidates_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcription = make_transcription(tmp_path, source_kind="manual_subtitle")
    SubtitlePackService(
        successful_caller(),
        model_label="fake:model",
        target_language="zh-CN",
    ).run(transcription)
    checkpoint_path = transcription.workspace.dir / "subtitle_checkpoints" / "batch-0001.json"
    first_identity = json.loads(checkpoint_path.read_text(encoding="utf-8"))["identity"]

    monkeypatch.setattr(
        workflow_module,
        "_GENERATION_BATCH_CHAR_BUDGET",
        workflow_module._GENERATION_BATCH_CHAR_BUDGET - 1,
    )
    second_caller = ScriptedSubtitleCaller(generation_response(), "[]")
    SubtitlePackService(
        second_caller,
        model_label="fake:model",
        target_language="zh-CN",
    ).run(transcription)

    second_identity = json.loads(checkpoint_path.read_text(encoding="utf-8"))["identity"]
    assert len(second_caller.calls) == 2
    assert second_identity != first_identity
