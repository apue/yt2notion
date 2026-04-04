"""Contract checks for agent slash-command instructions."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "relative_path",
    [
        ".claude/commands/youtube2notion.md",
        ".codex/commands/youtube2notion.md",
    ],
)
def test_agent_command_instructions_use_prepare_contract(relative_path: str) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    command_path = repo_root / relative_path
    assert command_path.exists(), f"Missing command file: {relative_path}"

    text = command_path.read_text(encoding="utf-8").lower()
    assert "uv run yt2notion prepare" in text
    assert "summary" in text and "full" in text
    assert "transcript_markdown" in text
    assert "re-summarize" in text
