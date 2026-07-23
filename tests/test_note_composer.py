"""Tests for provider-independent note composition."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from yt2notion.models.base import VideoMeta
from yt2notion.models.note_composer import NoteComposer


def test_composer_builds_all_prompt_payloads_and_parses_results() -> None:
    guide_json = {
        "title": "Ferrari 导读",
        "markdown": "# Ferrari 导读",
        "tags": ["法拉利", "导读版"],
        "variant": "a_guide",
    }
    longform_json = {
        "title": "Ferrari 扩展",
        "markdown": "# Ferrari 扩展",
        "tags": ["法拉利", "扩展版"],
        "variant": "b_longform",
    }
    metadata_json = {
        "source_title": "Ferrari",
        "stable_tags": ["法拉利", "赛车"],
        "guide_tags": ["导读版"],
        "longform_tags": ["扩展版"],
        "source_summary": "摘要",
        "source_topics": ["赛车文化"],
    }
    caller = MagicMock()
    caller.call.side_effect = [
        json.dumps(guide_json, ensure_ascii=False),
        json.dumps(longform_json, ensure_ascii=False),
        json.dumps(metadata_json, ensure_ascii=False),
    ]
    composer = NoteComposer(caller)
    source = VideoMeta(
        video_id="video123",
        title="Ferrari",
        channel="Channel",
        url="https://youtu.be/video123",
        duration_seconds=3600,
    )

    guide = composer.compose_guide_note("transcript", source, target_chars=1200)
    longform = composer.compose_longform_note(
        "transcript",
        guide,
        source,
        target_chars=2400,
    )
    metadata = composer.compose_note_metadata(guide, longform, source)

    assert guide.variant == "a_guide"
    assert longform.variant == "b_longform"
    assert metadata.source_title == "Ferrari"
    payloads = [json.loads(call.args[1]) for call in caller.call.call_args_list]
    assert payloads[0]["source"]["video_id"] == "video123"
    assert payloads[0]["target_chars"] == 1200
    assert payloads[0]["transcript"] == "transcript"
    assert payloads[1]["guide_note"]["variant"] == "a_guide"
    assert payloads[1]["target_chars"] == 2400
    assert payloads[2]["longform_note"]["variant"] == "b_longform"
    assert [call.kwargs["max_tokens"] for call in caller.call.call_args_list] == [
        8192,
        8192,
        4096,
    ]
