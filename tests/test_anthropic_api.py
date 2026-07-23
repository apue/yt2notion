"""Tests for the Anthropic text-call adapter."""

from unittest.mock import MagicMock, patch

import pytest

from yt2notion.models.anthropic_api import AnthropicAPICaller, AnthropicAPIError


@patch("yt2notion.models.anthropic_api._anthropic")
def test_call_forwards_model_prompt_and_token_limit(anthropic) -> None:
    client = MagicMock()
    anthropic.Anthropic.return_value = client
    client.messages.create.return_value.content = [MagicMock(text="result")]
    caller = AnthropicAPICaller(api_key="test-key", model="opus")

    result = caller.call("system", "user", max_tokens=8192)

    assert result == "result"
    assert client.messages.create.call_args.kwargs == {
        "model": "claude-opus-4-6",
        "max_tokens": 8192,
        "system": "system",
        "messages": [{"role": "user", "content": "user"}],
    }


@patch("yt2notion.models.anthropic_api._anthropic")
def test_call_translates_provider_error(anthropic) -> None:
    client = MagicMock()
    anthropic.Anthropic.return_value = client
    client.messages.create.side_effect = Exception("API error")

    with pytest.raises(AnthropicAPIError, match="API call failed"):
        AnthropicAPICaller(api_key="test-key").call("system", "user")
