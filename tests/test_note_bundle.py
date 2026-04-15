"""Tests for note bundle parsing and composition."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yt2notion.models._parsers import (
    ParseError,
    parse_note_document_json,
    parse_note_metadata_json,
)
from yt2notion.models.anthropic_api import AnthropicAPIModel
from yt2notion.models.base import (
    NoteDocument,
    NoteMetadata,
    VideoMeta,
)
from yt2notion.models.claude_code import ClaudeCodeModel
from yt2notion.models.codex_cli import CodexCLIModel
from yt2notion.note_bundle import (
    build_note_bundle,
    build_source_note,
    format_note_bundle_transcript,
    resolve_note_targets,
)


def _sample_metadata() -> VideoMeta:
    return VideoMeta(
        video_id="video123",
        title="Ferrari",
        channel="Channel",
        url="https://youtu.be/video123",
        duration_seconds=3600,
    )


def _sample_guide_note() -> NoteDocument:
    return NoteDocument(
        title="Ferrari 导读",
        markdown="# Ferrari 导读",
        tags=["法拉利", "导读版"],
        variant="a_guide",
    )


def _sample_longform_note() -> NoteDocument:
    return NoteDocument(
        title="Ferrari 扩展",
        markdown="# Ferrari 扩展",
        tags=["法拉利", "扩展版"],
        variant="b_longform",
    )


def test_resolve_note_targets_scales_with_duration() -> None:
    guide_1h, long_1h = resolve_note_targets(3600)
    guide_4h, long_4h = resolve_note_targets(4 * 3600)

    assert guide_1h >= 2000
    assert 2500 <= guide_4h <= 4000
    assert 7000 <= long_1h <= 9000
    assert 7000 <= long_4h <= 9000


def test_format_note_bundle_transcript_preserves_time_and_title() -> None:
    transcript = format_note_bundle_transcript(
        [
            {
                "title": "Part 1",
                "start_seconds": 0,
                "end_seconds": 10,
                "text": "alpha",
            },
            {
                "title": "Part 2",
                "start_seconds": 10,
                "end_seconds": 20,
                "text": "beta",
            },
        ]
    )

    assert "[0:00] Part 1" in transcript
    assert "[0:10] Part 2" in transcript
    assert "alpha" in transcript
    assert "beta" in transcript


def test_build_source_note_is_light_index() -> None:
    metadata = _sample_metadata()
    note_metadata = NoteMetadata(
        source_title="Ferrari",
        stable_tags=["法拉利", "赛车"],
        guide_tags=["导读版"],
        longform_tags=["扩展版"],
        source_summary="一段关于 Ferrari 的源材料摘要",
        source_topics=["赛车文化", "品牌叙事"],
    )
    source_note = build_source_note(
        metadata,
        note_metadata,
        _sample_guide_note(),
        _sample_longform_note(),
    )

    assert source_note.variant == "source"
    assert source_note.tags == ["法拉利", "赛车"]
    assert "来源定位" in source_note.markdown
    assert "核心主题" in source_note.markdown
    assert "阅读入口" in source_note.markdown
    assert "原始链接" in source_note.markdown
    assert metadata.url in source_note.markdown


def test_build_note_bundle_calls_guide_then_longform_then_metadata() -> None:
    reviewed = [
        {
            "title": "Part 1",
            "start_seconds": 0,
            "end_seconds": 10,
            "text": "alpha",
            "source": "asr",
        }
    ]
    metadata = _sample_metadata()
    calls: list[str] = []

    class FakeSummarizer:
        def compose_guide_note(
            self,
            transcript,
            metadata,
            *,
            target_chars,
            prompt_name="compose_guide",
        ):
            calls.append("guide")
            assert "Part 1" in transcript
            assert target_chars >= 2000
            del metadata, prompt_name
            return _sample_guide_note()

        def compose_longform_note(
            self,
            transcript,
            guide_note,
            metadata,
            *,
            target_chars,
            prompt_name="compose_longform",
        ):
            calls.append("longform")
            assert guide_note.variant == "a_guide"
            assert "Part 1" in transcript
            assert target_chars >= 7000
            del metadata, prompt_name
            return _sample_longform_note()

        def compose_note_metadata(
            self,
            guide_note,
            longform_note,
            metadata,
            *,
            prompt_name="compose_note_metadata",
        ):
            calls.append("metadata")
            assert guide_note.variant == "a_guide"
            assert longform_note.variant == "b_longform"
            del metadata, prompt_name
            return NoteMetadata(
                source_title="Ferrari",
                stable_tags=["法拉利", "赛车"],
                guide_tags=["导读版"],
                longform_tags=["扩展版"],
                source_summary="一段关于 Ferrari 的源材料摘要",
                source_topics=["赛车文化", "品牌叙事"],
            )

    bundle = build_note_bundle(reviewed, metadata, FakeSummarizer())

    assert calls == ["guide", "longform", "metadata"]
    assert bundle.guide.variant == "a_guide"
    assert bundle.longform.variant == "b_longform"
    assert bundle.source.variant == "source"
    assert bundle.stable_tags == ["法拉利", "赛车"]


def test_parse_note_document_json_success() -> None:
    text = """
    {
      "title": "Ferrari 导读",
      "markdown": "# Ferrari 导读",
      "tags": ["法拉利", "导读版"],
      "variant": "a_guide"
    }
    """
    note = parse_note_document_json(text, expected_variant="a_guide")
    assert note == _sample_guide_note()


def test_parse_note_document_json_supports_fenced_json() -> None:
    text = """```json
    {
      "title": "Ferrari 扩展",
      "markdown": "# Ferrari 扩展",
      "tags": ["法拉利", "扩展版"],
      "variant": "b_longform"
    }
    ```"""
    note = parse_note_document_json(text, expected_variant="b_longform")
    assert note == _sample_longform_note()


def test_parse_note_document_json_supports_markdown_paragraphs() -> None:
    text = """
    {
      "title": "Ferrari 扩展",
      "markdown_paragraphs": [
        "第一段。",
        "第二段。"
      ],
      "tags": ["法拉利", "扩展版"],
      "variant": "b_longform"
    }
    """
    note = parse_note_document_json(text, expected_variant="b_longform")
    assert note == NoteDocument(
        title="Ferrari 扩展",
        markdown="第一段。\n\n第二段。",
        tags=["法拉利", "扩展版"],
        variant="b_longform",
    )


def test_parse_note_document_json_supports_tagged_markdown_output() -> None:
    text = """
    <note_json>
    {
      "title": "Ferrari 导读",
      "tags": ["法拉利", "导读版"],
      "variant": "a_guide"
    }
    </note_json>
    <note_markdown>
    第一段。

    第二段。
    </note_markdown>
    """
    note = parse_note_document_json(text, expected_variant="a_guide")
    assert note == NoteDocument(
        title="Ferrari 导读",
        markdown="第一段。\n\n第二段。",
        tags=["法拉利", "导读版"],
        variant="a_guide",
    )


def test_parse_note_document_json_variant_mismatch_raises() -> None:
    text = """
    {
      "title": "Ferrari 导读",
      "markdown": "# Ferrari 导读",
      "tags": ["法拉利", "导读版"],
      "variant": "b_longform"
    }
    """
    with pytest.raises(ParseError, match="variant"):
        parse_note_document_json(text, expected_variant="a_guide")


def test_parse_note_document_json_missing_required_field_raises() -> None:
    text = """
    {
      "title": "Ferrari 导读",
      "markdown": "# Ferrari 导读",
      "variant": "a_guide"
    }
    """
    with pytest.raises(ParseError, match="tags"):
        parse_note_document_json(text, expected_variant="a_guide")


def test_parse_note_document_json_rejects_empty_strings_and_empty_tags() -> None:
    empty_title = """
    {
      "title": "",
      "markdown": "# Ferrari 导读",
      "tags": ["法拉利"],
      "variant": "a_guide"
    }
    """
    with pytest.raises(ParseError, match="title"):
        parse_note_document_json(empty_title, expected_variant="a_guide")

    empty_tags = """
    {
      "title": "Ferrari 导读",
      "markdown": "# Ferrari 导读",
      "tags": [],
      "variant": "a_guide"
    }
    """
    with pytest.raises(ParseError, match="tags"):
        parse_note_document_json(empty_tags, expected_variant="a_guide")


def test_parse_note_metadata_json_success() -> None:
    text = """
    {
      "source_title": "Ferrari",
      "stable_tags": ["法拉利", "赛车"],
      "guide_tags": ["导读版"],
      "longform_tags": ["扩展版"],
      "source_summary": "一段关于 Ferrari 的源材料摘要",
      "source_topics": ["赛车文化", "品牌叙事"]
    }
    """
    metadata = parse_note_metadata_json(text)
    assert metadata == NoteMetadata(
        source_title="Ferrari",
        stable_tags=["法拉利", "赛车"],
        guide_tags=["导读版"],
        longform_tags=["扩展版"],
        source_summary="一段关于 Ferrari 的源材料摘要",
        source_topics=["赛车文化", "品牌叙事"],
    )


def test_parse_note_metadata_json_missing_required_field_raises() -> None:
    text = """
    {
      "source_title": "Ferrari",
      "stable_tags": ["法拉利", "赛车"],
      "guide_tags": ["导读版"],
      "longform_tags": ["扩展版"],
      "source_summary": "一段关于 Ferrari 的源材料摘要"
    }
    """
    with pytest.raises(ParseError, match="source_topics"):
        parse_note_metadata_json(text)


def test_parse_note_metadata_json_rejects_empty_strings_and_empty_lists() -> None:
    empty_summary = """
    {
      "source_title": "Ferrari",
      "stable_tags": ["法拉利", "赛车"],
      "guide_tags": ["导读版"],
      "longform_tags": ["扩展版"],
      "source_summary": "",
      "source_topics": ["赛车文化", "品牌叙事"]
    }
    """
    with pytest.raises(ParseError, match="source_summary"):
        parse_note_metadata_json(empty_summary)

    empty_topics = """
    {
      "source_title": "Ferrari",
      "stable_tags": ["法拉利", "赛车"],
      "guide_tags": ["导读版"],
      "longform_tags": ["扩展版"],
      "source_summary": "一段关于 Ferrari 的源材料摘要",
      "source_topics": []
    }
    """
    with pytest.raises(ParseError, match="source_topics"):
        parse_note_metadata_json(empty_topics)


@pytest.mark.parametrize(
    ("backend", "call_attr"),
    [
        (ClaudeCodeModel(), "_call_claude"),
        (CodexCLIModel(), "_translate_caller"),
        ("anthropic", "_call_api"),
    ],
)
def test_compose_note_backend_smoke(
    backend: ClaudeCodeModel | CodexCLIModel | AnthropicAPIModel | str,
    call_attr: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guide_raw = """
    {
      "title": "Ferrari 导读",
      "markdown": "# Ferrari 导读",
      "tags": ["法拉利", "导读版"],
      "variant": "a_guide"
    }
    """
    longform_raw = """
    {
      "title": "Ferrari 扩展",
      "markdown": "# Ferrari 扩展",
      "tags": ["法拉利", "扩展版"],
      "variant": "b_longform"
    }
    """
    metadata_raw = """
    {
      "source_title": "Ferrari",
      "stable_tags": ["法拉利", "赛车"],
      "guide_tags": ["导读版"],
      "longform_tags": ["扩展版"],
      "source_summary": "一段关于 Ferrari 的源材料摘要",
      "source_topics": ["赛车文化", "品牌叙事"]
    }
    """

    if backend == "anthropic":
        import yt2notion.models.anthropic_api as anthropic_module

        monkeypatch.setattr(
            anthropic_module,
            "_anthropic",
            SimpleNamespace(Anthropic=lambda api_key: SimpleNamespace(api_key=api_key)),
        )
        backend = AnthropicAPIModel(api_key="test-key")

    assert not isinstance(backend, str)

    captured: list[tuple[str, str]] = []
    seen_max_tokens: list[int] = []

    if call_attr == "_translate_caller":
        monkeypatch.setattr(
            backend,
            "_translate_caller",
            SimpleNamespace(
                call=lambda system_prompt, user_prompt, max_tokens=4000: (
                    captured.append((system_prompt, user_prompt)) or guide_raw
                )
            ),
        )
    elif call_attr == "_call_api":
        def _fake_call(
            system_prompt: str,
            user_prompt: str,
            model: str,
            *,
            max_tokens: int = 4096,
        ) -> str:
            captured.append((system_prompt, user_prompt))
            seen_max_tokens.append(max_tokens)
            del model
            return next(responses)

        responses = iter([guide_raw, longform_raw, metadata_raw])
        monkeypatch.setattr(backend, call_attr, _fake_call)
    else:
        responses = iter([guide_raw, longform_raw, metadata_raw])

        def _fake_call(system_prompt: str, user_prompt: str, model: str) -> str:
            captured.append((system_prompt, user_prompt))
            del model
            return next(responses)

        monkeypatch.setattr(backend, call_attr, _fake_call)

    guide_note = backend.compose_guide_note(
        "source transcript",
        _sample_metadata(),
        target_chars=1200,
    )
    assert guide_note.variant == "a_guide"
    assert '"source"' in captured[0][1]
    assert '"target_chars": 1200' in captured[0][1]
    assert '"transcript"' in captured[0][1]

    if call_attr == "_translate_caller":
        monkeypatch.setattr(
            backend,
            "_translate_caller",
            SimpleNamespace(
                call=lambda system_prompt, user_prompt, max_tokens=4000: (
                    captured.append((system_prompt, user_prompt)) or longform_raw
                )
            ),
        )
    longform_note = backend.compose_longform_note(
        "source transcript",
        guide_note,
        _sample_metadata(),
        target_chars=2400,
    )
    assert longform_note.variant == "b_longform"
    assert '"guide_note"' in captured[1][1]
    assert '"target_chars": 2400' in captured[1][1]
    assert '"source"' in captured[1][1]
    assert '"transcript"' in captured[1][1]

    if call_attr == "_translate_caller":
        monkeypatch.setattr(
            backend,
            "_translate_caller",
            SimpleNamespace(
                call=lambda system_prompt, user_prompt, max_tokens=4000: (
                    captured.append((system_prompt, user_prompt)) or metadata_raw
                )
            ),
        )
    note_metadata = backend.compose_note_metadata(
        guide_note,
        longform_note,
        _sample_metadata(),
    )
    assert note_metadata.source_title == "Ferrari"
    assert '"source"' in captured[2][1]
    assert '"guide_note"' in captured[2][1]
    assert '"longform_note"' in captured[2][1]

    if call_attr == "_call_api":
        assert seen_max_tokens[0] == 8192
        assert seen_max_tokens[1] == 8192
        assert seen_max_tokens[2] == 4096
