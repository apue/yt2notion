"""Deterministic fixtures for offline subtitle-pack contract tests."""

from __future__ import annotations

import json
from pathlib import Path

from yt2notion.models.base import VideoMeta
from yt2notion.transcript_artifacts import MediaTranscribeResult
from yt2notion.workspace import Workspace


class ScriptedSubtitleCaller:
    """Return an explicit response sequence without interpreting prompt prose."""

    def __init__(self, *responses: str | BaseException) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    def call(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 4000) -> str:
        del system_prompt, max_tokens
        self.calls.append(user_prompt)
        if not self.responses:
            raise AssertionError("unexpected subtitle LLM call")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def context_response() -> str:
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


def generation_response(*, corrected: bool = False, include_second: bool = True) -> str:
    second = "Thank you Graham." if corrected else "Thank you Graeme."
    records = [
        {
            "id": "cue-000001",
            "source_text": "Welcome to Transformer agents.",
            "translated_text": "译：Welcome to Transformer agents.",
        }
    ]
    if include_second:
        records.append(
            {
                "id": "cue-000002",
                "source_text": second,
                "translated_text": f"译：{second}",
            }
        )
    return json.dumps(records, ensure_ascii=False)


def successful_caller(*, corrected: bool = False) -> ScriptedSubtitleCaller:
    return ScriptedSubtitleCaller(
        context_response(),
        generation_response(corrected=corrected),
        "[]",
    )


def make_transcription(tmp_path: Path, *, source_kind: str) -> MediaTranscribeResult:
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
