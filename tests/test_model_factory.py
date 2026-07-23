"""Tests for note-composer construction."""

from unittest.mock import patch

import pytest

from yt2notion.models import create_summarizer
from yt2notion.models.anthropic_api import AnthropicAPICaller
from yt2notion.models.codex_cli import CodexCLICaller
from yt2notion.models.note_composer import NoteComposer


def test_create_codex_composer() -> None:
    composer = create_summarizer({"model": {"backend": "codex_cli", "translate_model": "gpt-5.4"}})

    assert isinstance(composer, NoteComposer)
    assert isinstance(composer.caller, CodexCLICaller)


@patch("yt2notion.models.anthropic_api._anthropic")
def test_create_anthropic_composer(_anthropic) -> None:
    composer = create_summarizer(
        {
            "model": {
                "backend": "anthropic_api",
                "api_key": "test-key",
                "translate_model": "opus",
            }
        }
    )

    assert isinstance(composer, NoteComposer)
    assert isinstance(composer.caller, AnthropicAPICaller)


def test_create_anthropic_requires_key() -> None:
    with pytest.raises(ValueError, match="API key required"):
        create_summarizer({"model": {"backend": "anthropic_api"}})


def test_unknown_backend_raises() -> None:
    with pytest.raises(ValueError, match="Unknown LLM backend"):
        create_summarizer({"model": {"backend": "gpt4"}})
