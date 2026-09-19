"""Offline integration contracts for complete typed product pipelines."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yt2notion.config import AppConfig
from yt2notion.content_preparation import ContentPreparation
from yt2notion.domain import TranscriptSegment
from yt2notion.media_source import (
    OperationResult,
    SourceOperationError,
    SourceProbe,
)
from yt2notion.models.base import NoteDocument, NoteMetadata, VideoMeta
from yt2notion.pipelines import (
    run_note_pipeline,
    run_process_pipeline,
    run_subtitle_pack_pipeline,
    run_transcribe_pipeline,
    run_translation_experiment_pipeline,
)
from yt2notion.retry import retry, retry_for_exceptions
from yt2notion.workspace import Workspace


class FakeSourceProvider:
    def __init__(self, *, video_path: Path | None = None) -> None:
        self.video_path = video_path
        self.operations: list[str] = []

    def probe(self, locator: str) -> SourceProbe:
        metadata = VideoMeta(
            video_id="video-1",
            title="Title",
            channel="Channel",
            url=locator,
            duration_seconds=60,
        )
        return SourceProbe(locator=locator, metadata=metadata)

    def execute(self, operation: str, probe: SourceProbe, workspace: Workspace) -> OperationResult:
        self.operations.append(operation)
        if operation == "webpage_transcript":
            raise SourceOperationError(operation, "unavailable", "no transcript")
        audio_path = workspace.dir / "audio.mp3"
        audio_path.write_bytes(b"audio")
        return OperationResult(audio_path=audio_path, video_path=self.video_path)


class FakeEngine:
    def __init__(self) -> None:
        self.workspace_calls = 0
        self.audio_calls = 0

    def transcribe_workspace(self, *args, **kwargs) -> tuple[TranscriptSegment, ...]:
        self.workspace_calls += 1
        return _transcript("manual_subtitle")

    def transcribe_audio(self, *args, **kwargs) -> tuple[TranscriptSegment, ...]:
        self.audio_calls += 1
        return _transcript("asr")

    def backend_outcome(self, workspace: Workspace) -> str:
        return "mixed: groq, remote"


class FakeSummarizer:
    def compose_guide_note(self, *args, **kwargs) -> NoteDocument:
        return NoteDocument(title="Guide", markdown="# Guide", tags=["guide"], variant="a_guide")

    def compose_longform_note(self, *args, **kwargs) -> NoteDocument:
        return NoteDocument(title="Long", markdown="# Long", tags=["long"], variant="b_longform")

    def compose_note_metadata(self, *args, **kwargs) -> NoteMetadata:
        return NoteMetadata(
            source_title="Source",
            stable_tags=["stable"],
            guide_tags=["guide"],
            longform_tags=["long"],
            source_summary="Summary",
            source_topics=["topic"],
        )


class FakeStorage:
    def __init__(self) -> None:
        self.saved: list[tuple[object, VideoMeta]] = []

    def save_note_bundle(self, bundle, metadata: VideoMeta) -> str:
        self.saved.append((bundle, metadata))
        return "obsidian://source-note"


def test_note_pipeline_uses_source_provider_and_transcription_engine(tmp_path: Path) -> None:
    config = _config(tmp_path)
    Workspace(tmp_path, "video-1").save_failure(
        "https://example.com/video",
        "summarize",
        "old failure",
        retries_exhausted=True,
    )
    source_provider = FakeSourceProvider()
    engine = FakeEngine()

    prepared = run_note_pipeline(
        "https://example.com/video",
        config=config,
        source_provider=source_provider,
        transcription_engine=engine,
        preparation=_preparation(),
    )

    assert source_provider.operations == ["webpage_transcript", "audio"]
    assert engine.workspace_calls == 1
    assert prepared.note_bundle.source.variant == "source"
    assert prepared.workspace.load_transcripts() == _transcript("manual_subtitle")
    assert prepared.workspace.load_failure() is None


def test_transcribe_pipeline_stops_after_transcript_artifacts(tmp_path: Path) -> None:
    source_provider = FakeSourceProvider()
    engine = FakeEngine()

    result = run_transcribe_pipeline(
        "https://example.com/video",
        config=_config(tmp_path),
        source_provider=source_provider,
        transcription_engine=engine,
        preparation=ContentPreparation(),
        keep_video=False,
    )

    assert source_provider.operations == ["webpage_transcript", "audio"]
    assert engine.workspace_calls == 1
    assert engine.audio_calls == 0
    assert result.transcripts_path.exists()
    markdown = result.transcript_markdown_path.read_text(encoding="utf-8")
    assert "- Transcript source: manual_subtitle" in markdown
    assert not (result.workspace.dir / "note_bundle.json").exists()


def test_transcribe_pipeline_uses_shared_workspace_transcription(tmp_path: Path) -> None:
    class SubtitleSourceProvider:
        def probe(self, locator: str) -> SourceProbe:
            metadata = VideoMeta(
                video_id="captioned-video",
                title="Captioned",
                channel="Channel",
                url=locator,
                duration_seconds=60,
                manual_subtitle_languages=["en"],
            )
            return SourceProbe(locator=locator, metadata=metadata)

        def execute(
            self, operation: str, probe: SourceProbe, workspace: Workspace
        ) -> OperationResult:
            subtitle_path = workspace.dir / "subtitles.srt"
            subtitle_path.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello\n",
                encoding="utf-8",
            )
            workspace.save_subtitle_source("manual_subtitle")
            return OperationResult(
                subtitle_path=subtitle_path,
                subtitle_source="manual_subtitle",
            )

    engine = FakeEngine()
    result = run_transcribe_pipeline(
        "https://example.com/captioned",
        config=_config(tmp_path),
        source_provider=SubtitleSourceProvider(),
        transcription_engine=engine,
        preparation=ContentPreparation(),
        keep_video=False,
    )

    assert engine.workspace_calls == 1
    assert engine.audio_calls == 0
    assert result.audio_path is None
    assert result.workspace.load_transcripts() == _transcript("manual_subtitle")
    assert set(result.to_dict()["timings_seconds"]) == {
        "acquire",
        "segment",
        "transcribe",
        "total",
    }


def test_transcribe_pipeline_returns_media_source_video_path(tmp_path: Path) -> None:
    provider_video = tmp_path / "provider-video.webm"
    provider_video.write_bytes(b"video")

    result = run_transcribe_pipeline(
        "https://example.com/video",
        config=_config(tmp_path),
        source_provider=FakeSourceProvider(video_path=provider_video),
        transcription_engine=FakeEngine(),
        preparation=ContentPreparation(),
    )

    assert result.video_path == provider_video


def test_note_pipeline_records_source_acquisition_failure(tmp_path: Path) -> None:
    class FailingSourceProvider:
        def probe(self, locator: str) -> SourceProbe:
            return SourceProbe(
                locator=locator,
                metadata=VideoMeta("failed-video", "Title", "Channel", url=locator),
            )

        def execute(
            self, operation: str, probe: SourceProbe, workspace: Workspace
        ) -> OperationResult:
            raise SourceOperationError(operation, "provider", "download failed")

    with pytest.raises(RuntimeError, match="download failed"):
        run_note_pipeline(
            "https://example.com/video",
            config=_config(tmp_path),
            source_provider=FailingSourceProvider(),
            transcription_engine=FakeEngine(),
            preparation=_preparation(),
        )

    assert Workspace(tmp_path, "failed-video").load_failure()["step"] == "download"


def test_transcribe_pipeline_records_failure_and_profile(tmp_path: Path) -> None:
    class FailingEngine(FakeEngine):
        def transcribe_workspace(self, *args, **kwargs) -> tuple[TranscriptSegment, ...]:
            raise RuntimeError("ASR unavailable")

    with pytest.raises(RuntimeError, match="ASR unavailable"):
        run_transcribe_pipeline(
            "https://example.com/video",
            config=_config(tmp_path),
            source_provider=FakeSourceProvider(),
            transcription_engine=FailingEngine(),
            preparation=ContentPreparation(),
        )

    workspace = Workspace(tmp_path, "video-1")
    assert workspace.load_failure()["step"] == "transcribe"
    profile = _load_only_profile(workspace)
    assert profile["run_name"] == "transcribe"
    assert profile["status"] == "failed"
    transcribe = next(item for item in profile["observations"] if item["name"] == "transcribe")
    assert transcribe["status"] == "failed"
    assert transcribe["parent_id"] == profile["run_id"]


def test_transcribe_pipeline_clears_stale_failure_on_success(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path, "video-1")
    workspace.save_failure(
        "https://example.com/video",
        "download",
        "old failure",
        retries_exhausted=False,
    )

    result = run_transcribe_pipeline(
        "https://example.com/video",
        config=_config(tmp_path),
        source_provider=FakeSourceProvider(),
        transcription_engine=FakeEngine(),
        preparation=ContentPreparation(),
    )

    assert result.workspace.load_failure() is None


def test_process_pipeline_uses_storage_and_profiles_publish(tmp_path: Path) -> None:
    storage = FakeStorage()

    result = run_process_pipeline(
        "https://example.com/video",
        config=_config(tmp_path),
        source_provider=FakeSourceProvider(),
        transcription_engine=FakeEngine(),
        preparation=_preparation(),
        storage_factory=lambda config: storage,
    )

    assert result == "obsidian://source-note"
    assert len(storage.saved) == 1
    profile = _load_only_profile(Workspace(tmp_path, "video-1"))
    assert profile["run_name"] == "process"
    publish = next(item for item in profile["observations"] if item["name"] == "publish")
    storage_call = next(
        item for item in profile["observations"] if item["name"] == "storage.save_note_bundle"
    )
    assert storage_call["parent_id"] == publish["id"]


def test_note_pipeline_profile_nests_provider_retry_attempts(tmp_path: Path) -> None:
    class RetryingSourceProvider(FakeSourceProvider):
        def __init__(self) -> None:
            super().__init__()
            self.audio_attempts = 0

        def execute(
            self, operation: str, probe: SourceProbe, workspace: Workspace
        ) -> OperationResult:
            if operation != "audio":
                return super().execute(operation, probe, workspace)

            def download() -> OperationResult:
                self.audio_attempts += 1
                if self.audio_attempts == 1:
                    raise TimeoutError("sensitive provider detail")
                return super(RetryingSourceProvider, self).execute(operation, probe, workspace)

            return retry(
                download,
                classify=retry_for_exceptions(TimeoutError),
                max_retries=2,
                base_delay=0,
            )

    run_note_pipeline(
        "https://example.com/video",
        config=_config(tmp_path),
        source_provider=RetryingSourceProvider(),
        transcription_engine=FakeEngine(),
        preparation=_preparation(),
    )

    profile = _load_only_profile(Workspace(tmp_path, "video-1"))
    assert profile["run_name"] == "note_prepare"
    by_name = {item["name"]: item for item in profile["observations"]}
    attempts = [item for item in profile["observations"] if item["kind"] == "attempt"]
    assert [item["status"] for item in attempts] == ["failed", "completed"]
    assert all(item["parent_id"] == by_name["source.audio"]["id"] for item in attempts)
    assert by_name["source.audio"]["parent_id"] == by_name["acquire"]["id"]
    assert "sensitive provider detail" not in json.dumps(profile)


def test_translation_pipeline_composes_transcription_and_profiles_interruption(
    tmp_path: Path,
) -> None:
    engine = FakeEngine()

    class InterruptingRunner:
        def run(self, metadata, transcripts, workspace):
            raise KeyboardInterrupt("sensitive translation content")

    with pytest.raises(KeyboardInterrupt):
        run_translation_experiment_pipeline(
            "https://example.com/video",
            config=_config(tmp_path),
            source_provider=FakeSourceProvider(),
            transcription_engine=engine,
            preparation=ContentPreparation(),
            runner=InterruptingRunner(),
            keep_video=False,
        )

    assert engine.workspace_calls == 1
    profile = _load_only_profile(Workspace(tmp_path, "video-1"))
    assert profile["run_name"] == "translation_experiment"
    assert profile["status"] == "interrupted"
    translation = next(
        item for item in profile["observations"] if item["name"] == "translation_experiment"
    )
    assert translation["status"] == "interrupted"
    assert translation["parent_id"] == profile["run_id"]
    assert "sensitive translation content" not in json.dumps(profile)


def test_non_publish_pipelines_compose_transcription_without_storage(tmp_path: Path) -> None:
    engine = FakeEngine()

    class FakeExperimentRunner:
        def run(self, metadata, transcripts, workspace):
            assert transcripts == _transcript("manual_subtitle")
            return "experiment"

    class FakeSubtitleService:
        def run(self, result, *, observer=None):
            assert result.workspace.load_transcripts() == _transcript("manual_subtitle")
            assert observer is not None
            return "subtitle"

    common = {
        "config": _config(tmp_path),
        "source_provider": FakeSourceProvider(),
        "transcription_engine": engine,
        "preparation": ContentPreparation(),
    }
    experiment = run_translation_experiment_pipeline(
        "https://example.com/video",
        runner=FakeExperimentRunner(),
        keep_video=False,
        **common,
    )
    subtitle = run_subtitle_pack_pipeline(
        "https://example.com/video",
        service=FakeSubtitleService(),
        keep_video=False,
        **common,
    )
    assert experiment == "experiment"
    assert subtitle == "subtitle"
    assert engine.workspace_calls == 2
    profiles = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (tmp_path / "video-1" / "profiles").glob("*.json")
    ]
    assert {profile["run_name"] for profile in profiles} == {
        "translation_experiment",
        "subtitle_pack",
    }


def _config(tmp_path: Path) -> AppConfig:
    config = AppConfig()
    config.workspace = {"base_dir": str(tmp_path)}
    config.storage = {"backend": "obsidian"}
    return config


def _preparation() -> ContentPreparation:
    return ContentPreparation(summarizer_factory=lambda config: FakeSummarizer())


def _load_only_profile(workspace: Workspace) -> dict:
    profile_path = next((workspace.dir / "profiles").glob("*.json"))
    return json.loads(profile_path.read_text(encoding="utf-8"))


def _transcript(source: str) -> tuple[TranscriptSegment, ...]:
    return (
        TranscriptSegment(
            title="Part 1",
            start_seconds=0,
            end_seconds=10,
            text="hello",
            source=source,
        ),
    )
