"""Facade tests for application dependency and request composition."""

from __future__ import annotations

from unittest.mock import Mock

from yt2notion.application import Yt2Notion
from yt2notion.config import AppConfig


def test_prepare_composes_note_pipeline_dependencies(monkeypatch) -> None:
    app, dependencies = _application()
    pipeline = Mock(return_value="prepared")
    monkeypatch.setattr("yt2notion.application.run_note_pipeline", pipeline)

    result = app.prepare("https://example.com/video", verbose=True, resume_from="review")

    assert result == "prepared"
    assert pipeline.call_args.args == ("https://example.com/video",)
    assert pipeline.call_args.kwargs["resume_from"] == "review"
    assert pipeline.call_args.kwargs["verbose"] is True
    _assert_common_dependencies(pipeline, dependencies)
    assert "storage_factory" not in pipeline.call_args.kwargs


def test_process_is_only_facade_method_that_passes_storage(monkeypatch) -> None:
    app, dependencies = _application()
    pipeline = Mock(return_value="obsidian://note")
    monkeypatch.setattr("yt2notion.application.run_process_pipeline", pipeline)

    result = app.process("https://example.com/video", dry_run=True)

    assert result == "obsidian://note"
    assert pipeline.call_args.args == ("https://example.com/video",)
    assert pipeline.call_args.kwargs["dry_run"] is True
    _assert_common_dependencies(pipeline, dependencies)
    assert pipeline.call_args.kwargs["storage_factory"] is dependencies[3]


def test_transcribe_composes_complete_pipeline_dependencies(monkeypatch) -> None:
    app, dependencies = _application()
    pipeline = Mock(return_value="transcription")
    monkeypatch.setattr("yt2notion.application.run_transcribe_pipeline", pipeline)

    result = app.transcribe("https://example.com/video", keep_video=False)

    assert result == "transcription"
    assert pipeline.call_args.args == ("https://example.com/video",)
    assert pipeline.call_args.kwargs["keep_video"] is False
    _assert_common_dependencies(pipeline, dependencies)
    assert "storage_factory" not in pipeline.call_args.kwargs


def test_translation_experiment_composes_complete_pipeline_dependencies(monkeypatch) -> None:
    runner = object()
    app, dependencies = _application(translation_experiment_runner=runner)
    pipeline = Mock(return_value="experiment")
    monkeypatch.setattr("yt2notion.application.run_translation_experiment_pipeline", pipeline)

    result = app.run_translation_experiment("https://example.com/video")

    assert result == "experiment"
    assert pipeline.call_args.args == ("https://example.com/video",)
    assert pipeline.call_args.kwargs["keep_video"] is False
    _assert_common_dependencies(pipeline, dependencies)
    assert pipeline.call_args.kwargs["runner"] is runner
    assert "storage_factory" not in pipeline.call_args.kwargs


def test_subtitle_pack_composes_complete_pipeline_dependencies(monkeypatch) -> None:
    service = object()
    app, dependencies = _application(subtitle_pack_service=service)
    pipeline = Mock(return_value="subtitle")
    monkeypatch.setattr("yt2notion.application.run_subtitle_pack_pipeline", pipeline)

    result = app.create_subtitle_pack("https://example.com/video")

    assert result == "subtitle"
    assert pipeline.call_args.args == ("https://example.com/video",)
    assert pipeline.call_args.kwargs["keep_video"] is False
    _assert_common_dependencies(pipeline, dependencies)
    assert pipeline.call_args.kwargs["service"] is service
    assert "storage_factory" not in pipeline.call_args.kwargs


def _application(**kwargs) -> tuple[Yt2Notion, tuple[object, object, object, object]]:
    source_provider = object()
    transcription_engine = object()
    preparation = object()
    storage_factory = Mock()
    app = Yt2Notion(
        AppConfig(),
        source_provider=source_provider,
        transcription_engine=transcription_engine,
        content_preparation=preparation,
        storage_factory=storage_factory,
        **kwargs,
    )
    return app, (source_provider, transcription_engine, preparation, storage_factory)


def _assert_common_dependencies(pipeline: Mock, dependencies: tuple[object, ...]) -> None:
    source_provider, transcription_engine, preparation, _ = dependencies
    assert pipeline.call_args.kwargs["source_provider"] is source_provider
    assert pipeline.call_args.kwargs["transcription_engine"] is transcription_engine
    assert pipeline.call_args.kwargs["preparation"] is preparation
