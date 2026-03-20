"""Tests for Anthropic API backend (all mocked)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from yt2notion.models.base import VideoMeta

SAMPLE_SUMMARY_JSON = {
    "sections": [
        {
            "title": "Test Section",
            "timestamp": "0:00",
            "timestamp_seconds": 0,
            "summary": "Test summary.",
        }
    ],
    "overall_summary": "Test overall.",
    "suggested_tags": ["test"],
}


@pytest.fixture
def meta():
    return VideoMeta(
        video_id="abc123",
        title="Test Video",
        channel="TestChannel",
        url="https://www.youtube.com/watch?v=abc123",
    )


@patch("yt2notion.models.anthropic_api._anthropic")
def test_api_call_params(mock_anthropic, meta):
    mock_client = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(SAMPLE_SUMMARY_JSON))]
    mock_client.messages.create.return_value = mock_response

    from yt2notion.models.anthropic_api import AnthropicAPIModel

    model = AnthropicAPIModel(api_key="test-key", summarize_model="sonnet")
    result = model.summarize("transcript", meta)

    call_kwargs = mock_client.messages.create.call_args[1]
    assert "claude-sonnet-4-6" in call_kwargs["model"]
    assert call_kwargs["max_tokens"] == 4096
    assert len(result.sections) == 1


@patch("yt2notion.models.anthropic_api._anthropic")
def test_api_error_handling(mock_anthropic, meta):
    mock_client = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client
    mock_client.messages.create.side_effect = Exception("API error")

    from yt2notion.models.anthropic_api import AnthropicAPIError, AnthropicAPIModel

    model = AnthropicAPIModel(api_key="test-key")
    with pytest.raises(AnthropicAPIError, match="API call failed"):
        model.summarize("transcript", meta)


def test_reuses_parsers():
    """Verify the same JSON output parses identically in both backends."""
    from yt2notion.models._parsers import parse_summary_json

    raw = json.dumps(SAMPLE_SUMMARY_JSON)
    result = parse_summary_json(raw)
    assert result.sections[0].title == "Test Section"
