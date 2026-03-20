"""Tests for model backend factory."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from yt2notion.models import create_summarizer


def test_create_claude_code():
    config = {"model": {"backend": "claude_code", "summarize_model": "sonnet"}}
    model = create_summarizer(config)
    from yt2notion.models.claude_code import ClaudeCodeModel

    assert isinstance(model, ClaudeCodeModel)


@patch("yt2notion.models.anthropic_api._anthropic")
def test_create_anthropic(mock_anthropic):
    config = {"model": {"backend": "anthropic_api", "api_key": "test-key"}}
    model = create_summarizer(config)
    from yt2notion.models.anthropic_api import AnthropicAPIModel

    assert isinstance(model, AnthropicAPIModel)


def test_create_anthropic_no_key():
    config = {"model": {"backend": "anthropic_api"}}
    with pytest.raises(ValueError, match="API key required"):
        create_summarizer(config)


def test_unknown_backend_raises():
    config = {"model": {"backend": "gpt4"}}
    with pytest.raises(ValueError, match="Unknown model backend"):
        create_summarizer(config)
