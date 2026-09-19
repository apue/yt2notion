"""Contract tests for typed transcript domain objects and JSON codecs."""

from __future__ import annotations

import pytest

from yt2notion.artifact_codecs import (
    decode_segment_specs,
    decode_transcript_segments,
    encode_segment_specs,
    encode_transcript_segments,
)
from yt2notion.domain import SegmentSpec, TranscriptSegment


def test_segment_codec_preserves_existing_json_shape() -> None:
    payload = [
        {
            "title": "Long chapter (Part 2)",
            "start_seconds": 12,
            "end_seconds": 27.5,
            "parent_title": "Long chapter",
        }
    ]

    decoded = decode_segment_specs(payload)

    assert decoded == (
        SegmentSpec(
            title="Long chapter (Part 2)",
            start_seconds=12,
            end_seconds=27.5,
            parent_title="Long chapter",
        ),
    )
    assert encode_segment_specs(decoded) == payload


def test_transcript_codec_preserves_existing_json_shape_and_source() -> None:
    payload = [
        {
            "title": "Example",
            "start_seconds": 3.25,
            "end_seconds": 8,
            "text": "asymmetric sample",
            "source": "automatic_caption",
        }
    ]

    decoded = decode_transcript_segments(payload)

    assert decoded == (
        TranscriptSegment(
            title="Example",
            start_seconds=3.25,
            end_seconds=8,
            text="asymmetric sample",
            source="automatic_caption",
        ),
    )
    assert encode_transcript_segments(decoded) == payload


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"title": "not-a-list"}, "must be a list"),
        ([{"title": "missing timing", "start_seconds": 0}], "end_seconds"),
        (
            [{"title": "backwards", "start_seconds": 9, "end_seconds": 2}],
            "ends before it starts",
        ),
    ],
)
def test_segment_codec_rejects_invalid_ingress(payload: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        decode_segment_specs(payload)


def test_transcript_codec_rejects_non_text_required_field() -> None:
    with pytest.raises(ValueError, match="text"):
        decode_transcript_segments(
            [
                {
                    "title": "Invalid",
                    "start_seconds": 0,
                    "end_seconds": 1,
                    "text": 17,
                    "source": "asr",
                }
            ]
        )
