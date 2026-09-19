"""Contract tests for explicit application and provider interfaces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yt2notion.application import Yt2Notion
from yt2notion.config import AppConfig, ConfigError, load_config
from yt2notion.content_preparation import ContentPreparation
from yt2notion.domain import TranscriptSegment
from yt2notion.media_source import (
    OperationResult,
    SourceOperationError,
    SourceProbe,
    SourceRef,
    create_source_provider,
)
from yt2notion.models.base import NoteDocument, NoteMetadata, VideoMeta
from yt2notion.retry import retry, retry_for_exceptions
from yt2notion.transcribe import create_transcription_engine
from yt2notion.workspace import Workspace


class FakeSourceProvider:
    def __init__(self, tmp_path: Path, *, video_path: Path | None = None) -> None:
        self.video_path = video_path
        self.operations: list[str] = []

    def probe(self, source: SourceRef) -> SourceProbe:
        metadata = VideoMeta(
            video_id="video-1",
            title="Title",
            channel="Channel",
            url=source.locator,
            duration_seconds=60,
        )
        return SourceProbe(source=source, metadata=metadata)

    def execute(self, operation: str, probe: SourceProbe, workspace: Workspace) -> OperationResult:
        self.operations.append(operation)
        if operation == "webpage_transcript":
            raise SourceOperationError(operation, "unavailable", "no transcript")
        audio_path = workspace.dir / "audio.mp3"
        audio_path.write_bytes(b"audio")
        return OperationResult(
            audio_path=audio_path,
            video_path=self.video_path,
        )


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

    def backend_outcome(self, ws: Workspace) -> str:
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


def test_application_prepare_uses_source_provider_and_transcription_engine(
    tmp_path: Path,
) -> None:
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path)}
    Workspace(tmp_path, "video-1").save_failure(
        "https://example.com/video",
        "summarize",
        "old failure",
        retries_exhausted=True,
    )
    source_provider = FakeSourceProvider(tmp_path)
    engine = FakeEngine()
    prepared = Yt2Notion(
        cfg,
        source_provider=source_provider,
        transcription_engine=engine,
        content_preparation=ContentPreparation(summarizer_factory=lambda config: FakeSummarizer()),
    ).prepare("https://example.com/video")

    assert source_provider.operations == ["webpage_transcript", "audio"]
    assert engine.workspace_calls == 1
    assert prepared.note_bundle.source.variant == "source"
    assert prepared.workspace.load_transcripts() == _transcript("manual_subtitle")
    assert prepared.workspace.load_failure() is None


def test_application_transcribe_stops_after_transcript_artifacts(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path)}
    source_provider = FakeSourceProvider(tmp_path)
    engine = FakeEngine()

    result = Yt2Notion(
        cfg, source_provider=source_provider, transcription_engine=engine
    ).transcribe(
        "https://example.com/video",
        keep_video=False,
    )

    assert source_provider.operations == ["webpage_transcript", "audio"]
    assert engine.workspace_calls == 1
    assert engine.audio_calls == 0
    assert result.transcripts_path.exists()
    markdown = result.transcript_markdown_path.read_text(encoding="utf-8")
    assert "- Transcript source: manual_subtitle" in markdown
    assert not (result.workspace.dir / "note_bundle.json").exists()


def test_application_transcribe_uses_shared_workspace_transcription(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path)}

    class SubtitleSourceProvider:
        def probe(self, source: SourceRef) -> SourceProbe:
            metadata = VideoMeta(
                video_id="captioned-video",
                title="Captioned",
                channel="Channel",
                url=source.locator,
                duration_seconds=60,
                manual_subtitle_languages=["en"],
            )
            return SourceProbe(source=source, metadata=metadata)

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
    result = Yt2Notion(
        cfg,
        source_provider=SubtitleSourceProvider(),
        transcription_engine=engine,
    ).transcribe("https://example.com/captioned", keep_video=False)

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


def test_application_transcribe_returns_media_source_video_path(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path)}
    provider_video = tmp_path / "provider-video.webm"
    provider_video.write_bytes(b"video")

    result = Yt2Notion(
        cfg,
        source_provider=FakeSourceProvider(tmp_path, video_path=provider_video),
        transcription_engine=FakeEngine(),
    ).transcribe("https://example.com/video")

    assert result.video_path == provider_video


def test_application_records_source_acquisition_failure(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path)}

    class FailingSourceProvider:
        def probe(self, source: SourceRef) -> SourceProbe:
            return SourceProbe(
                source=source,
                metadata=VideoMeta("failed-video", "Title", "Channel", url=source.locator),
            )

        def execute(
            self, operation: str, probe: SourceProbe, workspace: Workspace
        ) -> OperationResult:
            raise SourceOperationError(operation, "provider", "download failed")

    with pytest.raises(RuntimeError, match="download failed"):
        Yt2Notion(
            cfg,
            source_provider=FailingSourceProvider(),
            transcription_engine=FakeEngine(),
        ).prepare("https://example.com/video")

    assert Workspace(tmp_path, "failed-video").load_failure()["step"] == "download"


def test_application_records_transcription_failure(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path)}

    class FailingEngine(FakeEngine):
        def transcribe_workspace(self, *args, **kwargs) -> tuple[TranscriptSegment, ...]:
            raise RuntimeError("ASR unavailable")

    with pytest.raises(RuntimeError, match="ASR unavailable"):
        Yt2Notion(
            cfg,
            source_provider=FakeSourceProvider(tmp_path),
            transcription_engine=FailingEngine(),
        ).transcribe("https://example.com/video")

    ws = Workspace(tmp_path, "video-1")
    assert ws.load_failure()["step"] == "transcribe"
    profile_path = next((ws.dir / "profiles").glob("*.json"))
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile["run_name"] == "transcribe"
    assert profile["status"] == "failed"
    transcribe = next(item for item in profile["observations"] if item["name"] == "transcribe")
    assert transcribe["status"] == "failed"
    assert transcribe["parent_id"] == profile["run_id"]


def test_application_transcribe_clears_stale_failure_on_success(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path)}
    ws = Workspace(tmp_path, "video-1")
    ws.save_failure(
        "https://example.com/video",
        "download",
        "old failure",
        retries_exhausted=False,
    )

    result = Yt2Notion(
        cfg,
        source_provider=FakeSourceProvider(tmp_path),
        transcription_engine=FakeEngine(),
    ).transcribe("https://example.com/video")

    assert result.workspace.load_failure() is None


def test_application_process_uses_injected_storage_adapter(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path)}
    cfg.storage = {"backend": "obsidian"}
    source_provider = FakeSourceProvider(tmp_path)
    engine = FakeEngine()
    storage = FakeStorage()

    result = Yt2Notion(
        cfg,
        source_provider=source_provider,
        transcription_engine=engine,
        content_preparation=ContentPreparation(summarizer_factory=lambda config: FakeSummarizer()),
        storage_factory=lambda config: storage,
    ).process("https://example.com/video")

    assert result == "obsidian://source-note"
    assert len(storage.saved) == 1
    profiles = list((tmp_path / "video-1" / "profiles").glob("*.json"))
    assert len(profiles) == 1
    profile = json.loads(profiles[0].read_text(encoding="utf-8"))
    assert profile["run_name"] == "process"
    publish = next(item for item in profile["observations"] if item["name"] == "publish")
    storage_call = next(
        item for item in profile["observations"] if item["name"] == "storage.save_note_bundle"
    )
    assert storage_call["parent_id"] == publish["id"]


def test_note_profile_nests_provider_retry_attempts(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path)}

    class RetryingSourceProvider(FakeSourceProvider):
        def __init__(self) -> None:
            super().__init__(tmp_path)
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

    Yt2Notion(
        cfg,
        source_provider=RetryingSourceProvider(),
        transcription_engine=FakeEngine(),
        content_preparation=ContentPreparation(summarizer_factory=lambda config: FakeSummarizer()),
    ).prepare("https://example.com/video")

    profile_path = next((tmp_path / "video-1" / "profiles").glob("*.json"))
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
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
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path)}
    engine = FakeEngine()

    class InterruptingRunner:
        def run(self, metadata, transcripts, workspace):
            raise KeyboardInterrupt("sensitive translation content")

    app = Yt2Notion(
        cfg,
        source_provider=FakeSourceProvider(tmp_path),
        transcription_engine=engine,
        translation_experiment_runner=InterruptingRunner(),
    )

    with pytest.raises(KeyboardInterrupt):
        app.run_translation_experiment("https://example.com/video")

    assert engine.workspace_calls == 1
    profiles = list((tmp_path / "video-1" / "profiles").glob("*.json"))
    assert len(profiles) == 1
    profile = json.loads(profiles[0].read_text(encoding="utf-8"))
    assert profile["run_name"] == "translation_experiment"
    assert profile["status"] == "interrupted"
    translation = next(
        item for item in profile["observations"] if item["name"] == "translation_experiment"
    )
    assert translation["status"] == "interrupted"
    assert translation["parent_id"] == profile["run_id"]
    assert "sensitive translation content" not in json.dumps(profile)


def test_non_publish_pipelines_do_not_construct_storage(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path)}
    storage_calls = 0

    def forbidden_storage(config: dict):
        nonlocal storage_calls
        storage_calls += 1
        raise AssertionError("local pipelines must not construct storage")

    app = Yt2Notion(
        cfg,
        source_provider=FakeSourceProvider(tmp_path),
        transcription_engine=FakeEngine(),
        content_preparation=ContentPreparation(summarizer_factory=lambda config: FakeSummarizer()),
        storage_factory=forbidden_storage,
    )
    app.prepare("https://example.com/video")

    class FakeExperimentRunner:
        def run(self, metadata, transcripts, workspace):
            assert transcripts == _transcript("manual_subtitle")
            return "experiment"

    class FakeSubtitleService:
        def run(self, result, *, observer=None):
            assert result.workspace.load_transcripts() == _transcript("manual_subtitle")
            assert observer is not None
            return "subtitle"

    app.translation_experiment_runner = FakeExperimentRunner()
    app.subtitle_pack_service = FakeSubtitleService()
    assert app.run_translation_experiment("https://example.com/video") == "experiment"
    assert app.create_subtitle_pack("https://example.com/video") == "subtitle"
    assert app.transcription_engine.workspace_calls == 3
    assert storage_calls == 0
    profiles = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (tmp_path / "video-1" / "profiles").glob("*.json")
    ]
    assert {profile["run_name"] for profile in profiles} == {
        "note_prepare",
        "translation_experiment",
        "subtitle_pack",
    }


def test_unknown_media_source_backend_raises_config_error(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("extract:\n  media_source:\n    backend: nope\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="Invalid media-source backend"):
        load_config(str(cfg_file))


def test_invalid_media_source_config_shape_raises_config_error(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("extract:\n  media_source: yt_dlp\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="extract.media_source must be a mapping"):
        load_config(str(cfg_file))


def test_unknown_source_provider_factory_backend_raises() -> None:
    with pytest.raises(ValueError, match="Unknown media-source backend"):
        create_source_provider({"extract": {"media_source": {"backend": "nope"}}})


def test_transcription_engine_factory_memoizes_fallback_adapter(monkeypatch) -> None:
    fallback = object()
    calls = 0

    def create_fallback(config: dict) -> object:
        nonlocal calls
        calls += 1
        return fallback

    monkeypatch.setattr("yt2notion.transcribe.create_fallback_transcriber", create_fallback)
    engine = create_transcription_engine(
        {
            "extract": {
                "asr": {
                    "backend": "groq",
                    "fallback_backend": "remote",
                }
            }
        }
    )

    factory = engine._fallback_transcriber_factory
    assert factory is not None
    assert factory() is fallback
    assert factory() is fallback
    assert calls == 1


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
