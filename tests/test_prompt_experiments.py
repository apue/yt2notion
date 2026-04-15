"""Tests for experimental prompt generation."""

from __future__ import annotations

import json
from pathlib import Path

from yt2notion.config import AppConfig
from yt2notion.models.base import ChineseContent, ChunkSummary, VideoMeta
from yt2notion.prompt_experiments import (
    PromptVariant,
    generate_workspace_ab_article_pair,
    generate_workspace_summary_variants,
    parse_ab_article_pair_json,
    prepare_workspace_transcript_only,
)


class _FakeSummarizer:
    def __init__(self) -> None:
        self.chunk_calls: list[dict] = []
        self.synthesize_calls: list[str] = []
        self.direct_calls: list[str] = []

    def summarize_chunk(
        self, chunk_transcript: str, metadata: VideoMeta, segment_info: dict
    ) -> ChunkSummary:
        del chunk_transcript, metadata
        self.chunk_calls.append(segment_info)
        return ChunkSummary(
            segment_title=segment_info["segment_title"],
            timestamp=segment_info["start_time"],
            timestamp_seconds=0,
            summary=f"summary for {segment_info['segment_title']}",
            key_points=[
                {
                    "timestamp": segment_info["start_time"],
                    "timestamp_seconds": 0,
                    "point": f"point for {segment_info['segment_title']}",
                }
            ],
            key_terms=["term"],
        )

    def synthesize(
        self,
        chunk_summaries: list[ChunkSummary],
        metadata: VideoMeta,
        *,
        prompt_name: str = "synthesize",
    ) -> ChineseContent:
        del chunk_summaries, metadata
        self.synthesize_calls.append(prompt_name)
        raw_markdown = (
            "## 概要\n\n"
            f"{prompt_name} overview\n\n"
            "## 关键节点\n\n"
            "- [0:00] **节点**：一段测试摘要\n\n"
            "## 标签\n\n"
            "测试标签"
        )
        return ChineseContent(
            overview=f"{prompt_name} overview",
            key_points=[{"timestamp": "0:00", "title": "节点", "summary": "一段测试摘要"}],
            tags=["测试标签"],
            raw_markdown=raw_markdown,
        )

    def summarize_transcript_to_markdown(
        self,
        transcript: str,
        metadata: VideoMeta,
        *,
        prompt_name: str,
    ) -> ChineseContent:
        del transcript, metadata
        self.direct_calls.append(prompt_name)
        raw_markdown = (
            "## 概要\n\n"
            f"{prompt_name} overview\n\n"
            "## 证据锚点\n\n"
            "- [0:00] **证据**：测试证据锚点\n\n"
            "## 关键节点\n\n"
            "- [0:00] **节点**：一段测试摘要\n\n"
            "## 标签\n\n"
            "测试标签"
        )
        return ChineseContent(
            overview=f"{prompt_name} overview",
            key_points=[{"timestamp": "0:00", "title": "节点", "summary": "一段测试摘要"}],
            tags=["测试标签"],
            raw_markdown=raw_markdown,
        )


class _FakeLLMCaller:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def call(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 4000) -> str:
        del max_tokens
        self.calls.append((system_prompt, user_prompt))
        return json.dumps(
            {
                "version_a": {
                    "title": "A版标题",
                    "markdown": "第一段。\n\n第二段。",
                },
                "version_b": {
                    "title": "B版标题",
                    "markdown": "导读第一段。\n\n导读第二段。",
                },
            },
            ensure_ascii=False,
        )

def _write_workspace_fixture(workspace_dir: Path) -> None:
    workspace_dir.mkdir(parents=True)
    metadata = {
        "video_id": workspace_dir.name,
        "title": "Long Episode",
        "channel": "Test Channel",
        "url": "https://example.com/video",
        "duration_seconds": 4000,
        "chapters": [],
    }
    transcripts = [
        {
            "title": "Part 1",
            "start_seconds": 0,
            "end_seconds": 1200,
            "text": "segment one",
            "source": "subtitle",
        },
        {
            "title": "Part 2",
            "start_seconds": 1200,
            "end_seconds": 2400,
            "text": "segment two",
            "source": "subtitle",
        },
    ]
    (workspace_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (workspace_dir / "transcripts.json").write_text(json.dumps(transcripts), encoding="utf-8")


def test_generate_workspace_summary_variants_writes_one_file_per_variant(
    tmp_path: Path, monkeypatch
) -> None:
    workspace_dir = tmp_path / "workspace" / "video123"
    _write_workspace_fixture(workspace_dir)

    fake = _FakeSummarizer()
    monkeypatch.setattr("yt2notion.prompt_experiments.create_summarizer", lambda config: fake)
    monkeypatch.setattr(
        "yt2notion.prompt_experiments._merge_segments_into_groups",
        lambda reviewed: [
            {"title": "Group 1", "start_seconds": 0, "end_seconds": 1000, "text": "first group"},
            {
                "title": "Group 2",
                "start_seconds": 1000,
                "end_seconds": 2000,
                "text": "second group",
            },
        ],
    )

    outputs = generate_workspace_summary_variants(
        workspace_dir=workspace_dir,
        config={"output": {"long_content_threshold_seconds": 1800}},
        variants=[
            PromptVariant(
                slug="reading_guide",
                label="导读短文",
                prompt_name="synthesize_reading_guide",
            ),
            PromptVariant(
                slug="guided_notes",
                label="结构化笔记",
                prompt_name="synthesize_guided_notes",
            ),
        ],
    )

    assert [item.slug for item in outputs] == ["reading_guide", "guided_notes"]
    assert fake.synthesize_calls == ["synthesize_reading_guide", "synthesize_guided_notes"]
    assert len(fake.chunk_calls) == 2

    for output in outputs:
        assert output.markdown_path.exists()
        assert output.json_path.exists()
        assert output.label in output.markdown_path.read_text(encoding="utf-8")
        payload = json.loads(output.json_path.read_text(encoding="utf-8"))
        assert payload["raw_markdown"].startswith("## 概要")


def test_generate_workspace_summary_variants_supports_direct_transcript_mode(
    tmp_path: Path, monkeypatch
) -> None:
    workspace_dir = tmp_path / "workspace" / "video123"
    _write_workspace_fixture(workspace_dir)

    fake = _FakeSummarizer()
    monkeypatch.setattr("yt2notion.prompt_experiments.create_summarizer", lambda config: fake)

    outputs = generate_workspace_summary_variants(
        workspace_dir=workspace_dir,
        config={"output": {"long_content_threshold_seconds": 1800}},
        variants=[
            PromptVariant(
                slug="raw_evidence_guide",
                label="原文直读",
                prompt_name="summarize_long_direct_evidence",
                mode="direct",
            )
        ],
    )

    assert [item.slug for item in outputs] == ["raw_evidence_guide"]
    assert fake.direct_calls == ["summarize_long_direct_evidence"]
    assert fake.chunk_calls == []
    assert fake.synthesize_calls == []

    payload = json.loads(outputs[0].json_path.read_text(encoding="utf-8"))
    assert "## 证据锚点" in payload["raw_markdown"]


def test_parse_ab_article_pair_json_handles_fenced_json() -> None:
    raw = """```json
    {
      "version_a": {"title": "A", "markdown": "正文A"},
      "version_b": {"title": "B", "markdown": "正文B"}
    }
    ```"""
    parsed = parse_ab_article_pair_json(raw)

    assert parsed["version_a"]["title"] == "A"
    assert parsed["version_b"]["markdown"] == "正文B"


def test_generate_workspace_ab_article_pair_writes_outputs(
    tmp_path: Path, monkeypatch
) -> None:
    workspace_dir = tmp_path / "workspace" / "video123"
    _write_workspace_fixture(workspace_dir)

    caller = _FakeLLMCaller()
    monkeypatch.setattr(
        "yt2notion.prompt_experiments.create_llm_caller",
        lambda *args, **kwargs: caller,
    )

    outputs = generate_workspace_ab_article_pair(
        workspace_dir=workspace_dir,
        config={"model": {"backend": "codex_cli", "translate_model": "gpt-5.2"}},
    )

    assert sorted(outputs) == ["version_a", "version_b"]
    assert len(caller.calls) == 1
    assert outputs["version_a"]["markdown_path"].exists()
    assert outputs["version_b"]["markdown_path"].exists()
    assert "A版标题" in outputs["version_a"]["markdown_path"].read_text(encoding="utf-8")
    assert "导读第一段" in outputs["version_b"]["markdown_path"].read_text(encoding="utf-8")


def test_prepare_workspace_transcript_only_writes_transcript_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    metadata = VideoMeta(
        video_id="video123",
        title="Episode",
        channel="Channel",
        url="https://example.com/video",
        duration_seconds=4000,
        subtitles_available=False,
    )

    monkeypatch.setattr(
        "yt2notion.prompt_experiments._step_download",
        lambda *args, **kwargs: metadata,
    )
    monkeypatch.setattr(
        "yt2notion.prompt_experiments._download_webpage_transcript",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "yt2notion.prompt_experiments._download_audio",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "yt2notion.prompt_experiments._step_segment",
        lambda *args, **kwargs: [{"title": "Part 1", "start_seconds": 0, "end_seconds": 100}],
    )
    monkeypatch.setattr(
        "yt2notion.prompt_experiments._step_transcribe",
        lambda *args, **kwargs: [
            {
                "title": "Part 1",
                "start_seconds": 0,
                "end_seconds": 100,
                "text": "hello world",
                "source": "subtitle",
            }
        ],
    )

    ws = prepare_workspace_transcript_only(
        url="https://example.com/video",
        config=AppConfig(workspace={"base_dir": str(tmp_path / "workspace")}),
        workspace_dir=str(tmp_path / "workspace"),
        verbose=False,
    )

    assert (ws.dir / "metadata.json").exists()
    assert (ws.dir / "segments.json").exists()
    assert (ws.dir / "transcripts.json").exists()
    assert not (ws.dir / "summary.json").exists()
