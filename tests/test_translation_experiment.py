"""Contract tests for the controlled translation A/B experiment."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from yt2notion.models.base import VideoMeta
from yt2notion.translation_experiment.artifacts import (
    load_candidate_checkpoint,
    save_candidate_checkpoint,
)
from yt2notion.translation_experiment.generator import (
    TranslationGenerator,
    TranslationResponseError,
)
from yt2notion.translation_experiment.models import CandidateIdentity, TranslationItem
from yt2notion.translation_experiment.service import (
    TranslationExperimentRunner,
    create_translation_experiment_runner,
)
from yt2notion.translation_experiment.source import (
    SourceContractError,
    build_source_chapters,
)
from yt2notion.workspace import Workspace


class FakeCaller:
    """Return queued responses while retaining prompts for fairness checks."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, int]] = []

    def call(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 4000) -> str:
        self.calls.append((system_prompt, user_prompt, max_tokens))
        return self.responses.pop(0)


def _transcripts() -> list[dict]:
    return [
        {
            "title": "Sets",
            "start_seconds": 0,
            "end_seconds": 60,
            "text": "A sample space contains outcomes. An event is a subset of that space.",
            "source": "manual_subtitle",
        },
        {
            "title": "Examples",
            "start_seconds": 60,
            "end_seconds": 120,
            "text": "Roll a die. The even outcomes form one event.",
            "source": "manual_subtitle",
        },
    ]


def test_build_source_chapters_creates_stable_semantic_block_ids():
    chapters = build_source_chapters(_transcripts(), block_target_chars=40)

    assert [chapter.chapter_id for chapter in chapters] == ["c001", "c002"]
    assert [block.block_id for block in chapters[0].blocks] == ["c001-b001", "c001-b002"]
    assert " ".join(block.source_text for block in chapters[0].blocks) == chapters[0].source_text


def test_build_source_chapters_rejects_empty_transcript():
    with pytest.raises(SourceContractError, match="at least one"):
        build_source_chapters([])


def test_generator_rejects_missing_or_reordered_ids():
    chapters = build_source_chapters(_transcripts())
    caller = FakeCaller(
        [json.dumps([{"chapter_id": "c002", "translation": "错误顺序"}], ensure_ascii=False)]
    )

    with pytest.raises(TranslationResponseError, match="exactly match source order"):
        TranslationGenerator(caller).translate_whole_chapters(chapters)


def test_checkpoint_identity_includes_model_and_prompt(tmp_path):
    path = tmp_path / "candidate.json"
    identity = CandidateIdentity(
        source_sha256="source-hash",
        strategy="whole_chapter",
        model_label="codex_cli:model-a",
        prompt_sha256="prompt-hash-a",
    )
    items = (TranslationItem(source_id="c001", translation="译文"),)
    save_candidate_checkpoint(
        path,
        identity=identity,
        items=items,
        generation_seconds=1.0,
    )

    assert load_candidate_checkpoint(path, identity=identity, expected_ids=["c001"]) is not None
    assert (
        load_candidate_checkpoint(
            path,
            identity=replace(identity, model_label="codex_cli:model-b"),
            expected_ids=["c001"],
        )
        is None
    )
    assert (
        load_candidate_checkpoint(
            path,
            identity=replace(identity, prompt_sha256="prompt-hash-b"),
            expected_ids=["c001"],
        )
        is None
    )


def test_runner_model_identity_includes_reasoning_effort():
    from yt2notion.config import AppConfig

    config = AppConfig(
        model={
            "backend": "codex_cli",
            "translate_model": "gpt-test",
            "review_model": "gpt-test",
            "reasoning_effort": "high",
            "timeout_seconds": 10,
            "max_attempts": 1,
        }
    )

    runner = create_translation_experiment_runner(config)

    assert runner.model_label == "codex_cli:gpt-test:reasoning=high"


def test_runner_writes_balanced_blind_artifacts_with_two_calls(tmp_path):
    whole = [
        {"chapter_id": "c001", "translation": "样本空间包含结果。事件是它的子集。"},
        {"chapter_id": "c002", "translation": "掷骰子。偶数结果构成一个事件。"},
    ]
    blocks = [
        {"block_id": "c001-b001", "translation": "样本空间包含结果。事件是该空间的子集。"},
        {"block_id": "c002-b001", "translation": "掷一个骰子。偶数结果形成一个事件。"},
    ]
    caller = FakeCaller(
        [json.dumps(whole, ensure_ascii=False), json.dumps(blocks, ensure_ascii=False)]
    )
    runner = TranslationExperimentRunner(caller, model_label="fake:test")
    workspace = Workspace(tmp_path, "video-1")
    metadata = VideoMeta(
        video_id="video-1",
        title="Probability",
        channel="Course",
        url="https://example.com/video-1",
    )

    result = runner.run(metadata, _transcripts(), workspace)

    assert len(caller.calls) == 2
    assert caller.calls[0][0] == caller.calls[1][0]
    assert result.blind_review_path.exists()
    review = result.blind_review_path.read_text(encoding="utf-8")
    assert "whole_chapter" not in review
    assert "semantic_blocks" not in review
    assert "样本空间" in review

    answer_key = json.loads(result.answer_key_path.read_text(encoding="utf-8"))
    a_strategies = [item["A"] for item in answer_key["assignments"].values()]
    assert sorted(a_strategies) == ["semantic_blocks", "whole_chapter"]

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["controlled_variables"]["calls_per_strategy"] == 1
    assert manifest["controlled_variables"]["formula_enrichment"] == "disabled"
    assert "translation_source_ratio" in manifest["diagnostics"]["whole_chapter"][0]
    assert manifest["generation_timings_seconds"]["whole_chapter"] >= 0

    resumed_caller = FakeCaller([])
    resumed = TranslationExperimentRunner(resumed_caller, model_label="fake:test").run(
        metadata, _transcripts(), workspace
    )
    assert resumed_caller.calls == []
    resumed_manifest = json.loads(resumed.manifest_path.read_text(encoding="utf-8"))
    assert resumed_manifest["reused_checkpoints"] == {
        "whole_chapter": True,
        "semantic_blocks": True,
    }
