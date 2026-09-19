"""Offline contracts for source routing, planning, and acquisition execution."""

from __future__ import annotations

from pathlib import Path

import pytest

from yt2notion.media_source import (
    AcquisitionError,
    AcquisitionIntent,
    AcquisitionRequest,
    OperationResult,
    SourceFailureCategory,
    SourceOperationError,
    SourceProbe,
    SourceRef,
    acquire_media,
    plan_acquisition,
    route_source,
)
from yt2notion.models.base import VideoMeta


def _probe(*, subtitles: bool) -> SourceProbe:
    metadata = VideoMeta(
        video_id="video-1",
        title="Title",
        channel="Channel",
        url="https://example.com/video-1",
        manual_subtitle_languages=["en"] if subtitles else [],
    )
    return SourceProbe(source=SourceRef(metadata.url), metadata=metadata)


def test_planner_prefers_subtitle_then_webpage_then_direct_audio() -> None:
    plan = plan_acquisition(_probe(subtitles=True), AcquisitionIntent(keep_video=False))

    assert plan.operations == ("subtitle", "webpage_transcript", "audio")


def test_planner_skips_subtitle_and_keeps_video_when_requested() -> None:
    plan = plan_acquisition(_probe(subtitles=False), AcquisitionIntent(keep_video=True))

    assert plan.operations == ("webpage_transcript", "video")


def test_router_is_explicit_and_does_not_guess_from_url_patterns() -> None:
    assert route_source("https://podcasts.example/episode").provider == "yt_dlp"


class FakeProvider:
    def __init__(
        self,
        tmp_path: Path,
        *,
        subtitle_failure: SourceOperationError | None = None,
    ) -> None:
        self.tmp_path = tmp_path
        self.subtitle_failure = subtitle_failure
        self.operations: list[str] = []

    def probe(self, source: SourceRef) -> SourceProbe:
        return _probe(subtitles=True)

    def execute(self, operation: str, probe: SourceProbe, workspace) -> OperationResult:
        self.operations.append(operation)
        if operation == "subtitle" and self.subtitle_failure is not None:
            raise self.subtitle_failure
        if operation == "webpage_transcript":
            raise SourceOperationError(operation, "unavailable", "no webpage transcript")
        if operation == "audio":
            path = workspace.dir / "audio.mp3"
            path.write_bytes(b"audio")
            return OperationResult(audio_path=path)
        path = workspace.dir / "subtitles.srt"
        path.write_text("subtitle", encoding="utf-8")
        return OperationResult(subtitle_path=path, subtitle_source="manual_subtitle")


def test_unavailable_subtitle_uses_declared_fallback(tmp_path: Path) -> None:
    provider = FakeProvider(
        tmp_path,
        subtitle_failure=SourceOperationError("subtitle", "unavailable", "track disappeared"),
    )

    result = acquire_media(
        provider,
        AcquisitionRequest("https://example.com/video-1", tmp_path, keep_video=False),
    )

    assert provider.operations == ["subtitle", "webpage_transcript", "audio"]
    assert result.audio_path == result.workspace.dir / "audio.mp3"


@pytest.mark.parametrize("category", ["authentication", "local_resource"])
def test_auth_and_local_failures_are_not_treated_as_missing_subtitles(
    tmp_path: Path, category: SourceFailureCategory
) -> None:
    failure = SourceOperationError("subtitle", category, "hard failure")
    provider = FakeProvider(tmp_path, subtitle_failure=failure)

    with pytest.raises(AcquisitionError) as raised:
        acquire_media(
            provider,
            AcquisitionRequest("https://example.com/video-1", tmp_path, keep_video=False),
        )

    assert raised.value.cause is failure
    assert provider.operations == ["subtitle"]
