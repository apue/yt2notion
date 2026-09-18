"""Offline deterministic contracts for model-produced subtitle data."""

from __future__ import annotations

import pytest

from yt2notion.subtitle_pack.models import SourceCue
from yt2notion.subtitle_pack.validation import (
    SubtitlePackError,
    parse_generated,
    parse_json_array,
)

SOURCE = [
    SourceCue("cue-000001", 1_000, 4_000, "First"),
    SourceCue("cue-000002", 5_000, 9_000, "Second"),
]


def test_generation_requires_exact_ordered_id_coverage() -> None:
    records = [{"id": "cue-000001", "source_text": "First", "translated_text": "第一"}]

    with pytest.raises(SubtitlePackError, match="exactly match"):
        parse_generated(records, SOURCE, "automatic_caption")


def test_manual_subtitle_generation_cannot_rewrite_source_text() -> None:
    records = [
        {"id": "cue-000001", "source_text": "Changed", "translated_text": "第一"},
        {"id": "cue-000002", "source_text": "Second", "translated_text": "第二"},
    ]

    with pytest.raises(SubtitlePackError, match="manual subtitle source text was changed"):
        parse_generated(records, SOURCE, "manual_subtitle")


def test_malformed_quality_json_cannot_be_treated_as_no_issues() -> None:
    with pytest.raises(SubtitlePackError, match="quality response is not valid JSON"):
        parse_json_array("quality looks good", "quality")
