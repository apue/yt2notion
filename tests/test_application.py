"""Contract tests for explicit application and provider interfaces."""

from __future__ import annotations

from pathlib import Path

import pytest

from yt2notion.application import Yt2Notion
from yt2notion.config import AppConfig, ConfigError, load_config
from yt2notion.content_preparation import ContentPreparation
from yt2notion.media_source import (
    MediaAcquireRequest,
    MediaAcquireResult,
    MediaAcquisitionError,
    create_media_source,
)
from yt2notion.models.base import NoteDocument, NoteMetadata, VideoMeta
from yt2notion.transcribe import create_transcription_engine
from yt2notion.workspace import Workspace


class FakeMediaSource:
    def __init__(self, tmp_path: Path, *, video_path: Path | None = None) -> None:
        self.tmp_path = tmp_path
        self.video_path = video_path
        self.requests: list[MediaAcquireRequest] = []

    def acquire(self, request: MediaAcquireRequest) -> MediaAcquireResult:
        self.requests.append(request)
        metadata = VideoMeta(
            video_id="video-1",
            title="Title",
            channel="Channel",
            url=request.url,
            duration_seconds=60,
        )
        ws = Workspace(request.workspace_base_dir, metadata.video_id)
        ws.save_metadata(metadata)
        audio_path = ws.dir / "audio.mp3"
        audio_path.write_bytes(b"audio")
        return MediaAcquireResult(
            metadata=metadata,
            workspace=ws,
            audio_path=audio_path,
            video_path=self.video_path,
        )


class FakeEngine:
    def __init__(self) -> None:
        self.workspace_calls = 0
        self.audio_calls = 0

    def transcribe_workspace(self, *args, **kwargs) -> list[dict]:
        self.workspace_calls += 1
        return _transcript("manual_subtitle")

    def transcribe_audio(self, *args, **kwargs) -> list[dict]:
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


def test_application_prepare_uses_media_source_and_transcription_engine(
    tmp_path: Path,
) -> None:
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path)}
    media_source = FakeMediaSource(tmp_path)
    engine = FakeEngine()
    prepared = Yt2Notion(
        cfg,
        media_source=media_source,
        transcription_engine=engine,
        content_preparation=ContentPreparation(summarizer_factory=lambda config: FakeSummarizer()),
    ).prepare("https://example.com/video")

    assert media_source.requests[0].keep_video is False
    assert engine.workspace_calls == 1
    assert prepared.note_bundle.source.variant == "source"
    assert prepared.workspace.load_transcripts() == _transcript("manual_subtitle")


def test_application_transcribe_stops_after_transcript_artifacts(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path)}
    media_source = FakeMediaSource(tmp_path)
    engine = FakeEngine()

    result = Yt2Notion(cfg, media_source=media_source, transcription_engine=engine).transcribe(
        "https://example.com/video",
        keep_video=False,
    )

    assert media_source.requests[0].keep_video is False
    assert engine.workspace_calls == 1
    assert engine.audio_calls == 0
    assert result.transcripts_path.exists()
    markdown = result.transcript_markdown_path.read_text(encoding="utf-8")
    assert "- Transcript source: manual_subtitle" in markdown
    assert not (result.workspace.dir / "note_bundle.json").exists()


def test_application_transcribe_uses_shared_workspace_transcription(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path)}

    class SubtitleMediaSource:
        def acquire(self, request: MediaAcquireRequest) -> MediaAcquireResult:
            metadata = VideoMeta(
                video_id="captioned-video",
                title="Captioned",
                channel="Channel",
                url=request.url,
                duration_seconds=60,
                manual_subtitle_languages=["en"],
            )
            ws = Workspace(request.workspace_base_dir, metadata.video_id)
            ws.save_metadata(metadata)
            subtitle_path = ws.dir / "subtitles.srt"
            subtitle_path.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello\n",
                encoding="utf-8",
            )
            ws.save_subtitle_source("manual_subtitle")
            return MediaAcquireResult(
                metadata=metadata,
                workspace=ws,
                subtitle_path=subtitle_path,
                subtitle_source="manual_subtitle",
            )

    engine = FakeEngine()
    result = Yt2Notion(
        cfg,
        media_source=SubtitleMediaSource(),
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
        media_source=FakeMediaSource(tmp_path, video_path=provider_video),
        transcription_engine=FakeEngine(),
    ).transcribe("https://example.com/video")

    assert result.video_path == provider_video


def test_application_records_media_acquisition_failure(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path)}
    ws = Workspace(tmp_path, "failed-video")

    class FailingMediaSource:
        def acquire(self, request: MediaAcquireRequest) -> MediaAcquireResult:
            raise MediaAcquisitionError(ws, RuntimeError("download failed"))

    with pytest.raises(RuntimeError, match="download failed"):
        Yt2Notion(
            cfg,
            media_source=FailingMediaSource(),
            transcription_engine=FakeEngine(),
        ).prepare("https://example.com/video")

    assert ws.load_failure()["step"] == "download"


def test_application_records_transcription_failure(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path)}

    class FailingEngine(FakeEngine):
        def transcribe_workspace(self, *args, **kwargs) -> list[dict]:
            raise RuntimeError("ASR unavailable")

    with pytest.raises(RuntimeError, match="ASR unavailable"):
        Yt2Notion(
            cfg,
            media_source=FakeMediaSource(tmp_path),
            transcription_engine=FailingEngine(),
        ).transcribe("https://example.com/video")

    ws = Workspace(tmp_path, "video-1")
    assert ws.load_failure()["step"] == "transcribe"


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
        media_source=FakeMediaSource(tmp_path),
        transcription_engine=FakeEngine(),
    ).transcribe("https://example.com/video")

    assert result.workspace.load_failure() is None


def test_application_process_uses_injected_storage_adapter(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path)}
    cfg.storage = {"backend": "obsidian"}
    media_source = FakeMediaSource(tmp_path)
    engine = FakeEngine()
    storage = FakeStorage()

    result = Yt2Notion(
        cfg,
        media_source=media_source,
        transcription_engine=engine,
        content_preparation=ContentPreparation(summarizer_factory=lambda config: FakeSummarizer()),
        storage_factory=lambda config: storage,
    ).process("https://example.com/video")

    assert result == "obsidian://source-note"
    assert len(storage.saved) == 1


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


def test_unknown_media_source_factory_backend_raises() -> None:
    with pytest.raises(ValueError, match="Unknown media-source backend"):
        create_media_source({"extract": {"media_source": {"backend": "nope"}}})


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


def _transcript(source: str) -> list[dict]:
    return [
        {
            "title": "Part 1",
            "start_seconds": 0,
            "end_seconds": 10,
            "text": "hello",
            "source": source,
        }
    ]
