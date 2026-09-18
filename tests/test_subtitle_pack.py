"""Contract tests for cue-timed bilingual subtitle packages."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yt2notion.models.base import VideoMeta
from yt2notion.subtitle_pack.service import SubtitlePackError, SubtitlePackService
from yt2notion.transcript_artifacts import MediaTranscribeResult
from yt2notion.workspace import Workspace


class FakeSubtitleCaller:
    """Return prompt-shaped data while preserving strict cue contracts."""

    def __init__(
        self,
        *,
        correct_source: bool = False,
        drop_last_id: bool = False,
        quality_issue_once: bool = False,
        malformed_quality: bool = False,
    ) -> None:
        self.correct_source = correct_source
        self.drop_last_id = drop_last_id
        self.quality_issue_once = quality_issue_once
        self.malformed_quality = malformed_quality
        self.quality_calls = 0
        self.calls: list[str] = []

    def call(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 4000) -> str:
        del system_prompt, max_tokens
        self.calls.append(user_prompt)
        if "Audit the bilingual cues" in user_prompt:
            self.quality_calls += 1
            if self.malformed_quality:
                return "quality looks good"
            if self.quality_issue_once and self.quality_calls == 1:
                payload = _prompt_payload(user_prompt)
                return json.dumps(
                    [{"id": payload["cues"][0]["id"], "issue": "translation is inaccurate"}]
                )
            return "[]"
        payload = _prompt_payload(user_prompt)
        if "Process only the IDs" in user_prompt:
            owned_ids = payload["owned_ids"]
            visible = {cue["id"]: cue for cue in payload["visible_cues"]}
            records = []
            for cue_id in owned_ids:
                source = visible[cue_id]["original_text"]
                if self.correct_source:
                    source = source.replace("Graeme", "Graham")
                records.append(
                    {
                        "id": cue_id,
                        "source_text": source,
                        "translated_text": f"译：{source}",
                    }
                )
            if self.drop_last_id:
                records.pop()
            return json.dumps(records, ensure_ascii=False)
        return json.dumps(
            {
                "domain": "AI agents",
                "course_or_series": "CMU CS 11-768",
                "people": ["Graham Neubig"],
                "topics": ["agents"],
                "terminology": [
                    {
                        "term": "Transformer",
                        "preferred_rendering": "Transformer",
                        "reason": "standard term",
                    }
                ],
                "notes": [],
            }
        )


def _prompt_payload(prompt: str) -> dict:
    marker = "Input:\n" if "Input:\n" in prompt else "Source:\n"
    return json.loads(prompt.split(marker, 1)[1])


def _transcription(tmp_path: Path, *, source_kind: str) -> MediaTranscribeResult:
    metadata = VideoMeta(
        video_id="UwfjzyLnvMg",
        title="AI Agents Course",
        channel="CMU",
        url="https://www.youtube.com/watch?v=UwfjzyLnvMg",
        duration_seconds=12,
        language="en",
        description="This lecture by Daniel Fried and Graham Neubig for CMU CS 11-768.",
    )
    workspace = Workspace(tmp_path, metadata.video_id)
    workspace.save_metadata(metadata)
    subtitle_path = workspace.dir / "subtitles.srt"
    subtitle_path.write_text(
        "1\n00:00:01,000 --> 00:00:04,000\nWelcome to Transformer agents.\n\n"
        "2\n00:00:05,000 --> 00:00:09,000\nThank you Graeme.\n",
        encoding="utf-8",
    )
    workspace.save_subtitle_source(source_kind)
    workspace.save_transcripts(
        [
            {
                "title": "Segment",
                "start_seconds": 1,
                "end_seconds": 9,
                "text": "Welcome to Transformer agents. Thank you Graeme.",
                "source": source_kind,
            }
        ]
    )
    transcript_path = workspace.dir / "transcript.md"
    transcript_path.write_text("transcript", encoding="utf-8")
    return MediaTranscribeResult(
        metadata=metadata,
        workspace=workspace,
        video_path=None,
        audio_path=None,
        transcripts_path=workspace.dir / "transcripts.json",
        transcript_markdown_path=transcript_path,
        timings_seconds={"acquire": 0.1, "transcribe": 0.2, "total": 0.3},
    )


def test_manual_subtitles_are_translated_without_source_rewrite(tmp_path: Path) -> None:
    caller = FakeSubtitleCaller()
    result = SubtitlePackService(
        caller,
        model_label="fake:model",
        target_language="zh-CN",
    ).run(_transcription(tmp_path, source_kind="manual_subtitle"))

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
    assert {call["operation"] for call in profile["llm_calls"]} == {
        "context_section",
        "generate",
        "semantic_quality",
    }
    assert "Transformer" not in result.profile_path.read_text(encoding="utf-8")


def test_automatic_captions_can_be_contextually_corrected(tmp_path: Path) -> None:
    result = SubtitlePackService(
        FakeSubtitleCaller(correct_source=True),
        model_label="fake:model",
        target_language="zh-CN",
    ).run(_transcription(tmp_path, source_kind="automatic_caption"))

    package = json.loads(result.package_path.read_text(encoding="utf-8"))
    assert package["cues"][1]["original_text"] == "Thank you Graeme."
    assert package["cues"][1]["source_text"] == "Thank you Graham."
    reviewed = json.loads((result.workspace_dir / "reviewed_cues.json").read_text(encoding="utf-8"))
    assert reviewed[1] == {"id": "cue-000002", "source_text": "Thank you Graham."}


def test_asr_uses_preserved_chunk_cue_timing(tmp_path: Path) -> None:
    transcription = _transcription(tmp_path, source_kind="automatic_caption")
    transcription.workspace.subtitle_path.unlink()
    (transcription.workspace.dir / "subtitle_source.json").unlink()
    transcription.workspace.save_transcribe_plan(
        [
            {
                "chunk_id": "segment-001",
                "segment_index": 0,
                "title": "Lecture",
                "start_seconds": 60,
                "end_seconds": 90,
                "audio_relpath": "segments/001.mp3",
            }
        ]
    )
    transcription.workspace.save_transcribe_chunk_result(
        "segment-001",
        [
            {
                "start_seconds": 1.0,
                "end_seconds": 4.5,
                "text": "Thank you Graeme.",
                "source": "asr",
            }
        ],
    )

    result = SubtitlePackService(
        FakeSubtitleCaller(correct_source=True),
        model_label="fake:model",
        target_language="zh-CN",
    ).run(transcription)

    package = json.loads(result.package_path.read_text(encoding="utf-8"))
    assert package["source_kind"] == "asr"
    assert package["cues"][0]["start_ms"] == 61_000
    assert package["cues"][0]["end_ms"] == 64_500
    assert package["cues"][0]["source_text"] == "Thank you Graham."


def test_semantic_issue_is_repaired_and_rechecked(tmp_path: Path) -> None:
    caller = FakeSubtitleCaller(quality_issue_once=True)
    result = SubtitlePackService(
        caller,
        model_label="fake:model",
        target_language="zh-CN",
    ).run(_transcription(tmp_path, source_kind="manual_subtitle"))

    assert result.quality_passed is True
    profile = json.loads(result.profile_path.read_text(encoding="utf-8"))
    operations = [call["operation"] for call in profile["llm_calls"]]
    assert "repair" in operations
    assert "semantic_quality_after_repair" in operations
    package = json.loads(result.package_path.read_text(encoding="utf-8"))
    assert package["quality"] == {"passed": True, "semantic_issue_count": 0}


def test_missing_model_id_fails_and_still_writes_profile(tmp_path: Path) -> None:
    transcription = _transcription(tmp_path, source_kind="automatic_caption")
    service = SubtitlePackService(
        FakeSubtitleCaller(drop_last_id=True),
        model_label="fake:model",
        target_language="zh-CN",
    )

    with pytest.raises(SubtitlePackError, match="exactly match"):
        service.run(transcription)

    profiles = list((transcription.workspace.dir / "profiles").glob("*.json"))
    assert len(profiles) == 1
    assert json.loads(profiles[0].read_text(encoding="utf-8"))["status"] == "failed"


def test_malformed_quality_response_cannot_pass_validation(tmp_path: Path) -> None:
    transcription = _transcription(tmp_path, source_kind="manual_subtitle")

    with pytest.raises(SubtitlePackError, match="semantic quality response is not valid JSON"):
        SubtitlePackService(
            FakeSubtitleCaller(malformed_quality=True),
            model_label="fake:model",
            target_language="zh-CN",
        ).run(transcription)

    assert not (transcription.workspace.dir / "bilingual_subtitles.json").exists()


def test_context_checkpoint_is_invalidated_when_metadata_changes(tmp_path: Path) -> None:
    transcription = _transcription(tmp_path, source_kind="manual_subtitle")
    first_caller = FakeSubtitleCaller()
    SubtitlePackService(
        first_caller,
        model_label="fake:model",
        target_language="zh-CN",
    ).run(transcription)

    transcription.metadata.description = "A different course and lecturer."
    second_caller = FakeSubtitleCaller()
    SubtitlePackService(
        second_caller,
        model_label="fake:model",
        target_language="zh-CN",
    ).run(transcription)

    assert any("Analyze the supplied video metadata" in prompt for prompt in second_caller.calls)
    context = json.loads(
        (transcription.workspace.dir / "subtitle_context.json").read_text(encoding="utf-8")
    )
    assert context["source_evidence"]["description"] == "A different course and lecturer."
