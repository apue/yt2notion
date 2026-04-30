"""Tests for Anthropic API backend (all mocked)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from yt2notion.models.base import NoteDocument, VideoMeta

GUIDE_JSON = {"title": "Guide", "markdown": "# Guide", "tags": ["guide"], "variant": "a_guide"}
META_JSON = {
    "source_title": "Source",
    "stable_tags": ["stable"],
    "guide_tags": ["guide"],
    "longform_tags": ["long"],
    "source_summary": "summary",
    "source_topics": ["topic"],
}


@pytest.fixture
def meta() -> VideoMeta:
    return VideoMeta(video_id="abc123", title="Test Video", channel="TestChannel", url="u")


@patch("yt2notion.models.anthropic_api._anthropic")
def test_compose_guide_note_calls_api_and_parses_note(mock_anthropic, meta):
    mock_client = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(GUIDE_JSON))]
    mock_client.messages.create.return_value = mock_response

    from yt2notion.models.anthropic_api import AnthropicAPIModel

    result = AnthropicAPIModel(api_key="test-key", translate_model="opus").compose_guide_note(
        "transcript", meta, target_chars=2000
    )

    assert result.variant == "a_guide"
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-opus-4-6"
    assert call_kwargs["max_tokens"] == 8192


@patch("yt2notion.models.anthropic_api._anthropic")
def test_compose_note_metadata_calls_api_and_parses_metadata(mock_anthropic, meta):
    mock_client = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(META_JSON))]
    mock_client.messages.create.return_value = mock_response

    from yt2notion.models.anthropic_api import AnthropicAPIModel

    guide = NoteDocument(title="Guide", markdown="# Guide", tags=[], variant="a_guide")
    long = NoteDocument(title="Long", markdown="# Long", tags=[], variant="b_longform")
    result = AnthropicAPIModel(api_key="test-key").compose_note_metadata(guide, long, meta)

    assert result.source_title == "Source"
    assert result.source_topics == ["topic"]


@patch("yt2notion.models.anthropic_api._anthropic")
def test_api_error_handling(mock_anthropic, meta):
    mock_client = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client
    mock_client.messages.create.side_effect = Exception("API error")

    from yt2notion.models.anthropic_api import AnthropicAPIError, AnthropicAPIModel

    model = AnthropicAPIModel(api_key="test-key")
    with pytest.raises(AnthropicAPIError, match="API call failed"):
        model.compose_guide_note("transcript", meta, target_chars=2000)
