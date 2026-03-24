"""Shared test fixtures."""

from __future__ import annotations

import pytest

from yt2notion.models.base import VideoMeta

SAMPLE_SRT = """\
1
00:00:01,000 --> 00:00:05,500
Welcome to this video about hip flexor strengthening.

2
00:00:05,500 --> 00:00:12,000
Today we'll cover five exercises that target the iliopsoas muscle.

3
00:02:04,000 --> 00:02:18,000
The first exercise is the supine leg raise. Make sure your lower back stays flat on the ground.

4
00:04:03,000 --> 00:04:15,000
Now let's work on releasing the posterior thigh using a foam roller.
"""

SAMPLE_VTT = """\
WEBVTT

00:00:01.000 --> 00:00:05.500
Welcome to this video about hip flexor strengthening.

00:00:05.500 --> 00:00:12.000
Today we'll cover five exercises that target the iliopsoas muscle.

00:02:04.000 --> 00:02:18.000
The first exercise is the supine leg raise. Make sure your lower back stays flat on the ground.

00:04:03.000 --> 00:04:15.000
Now let's work on releasing the posterior thigh using a foam roller.
"""


@pytest.fixture
def sample_srt(tmp_path):
    """Write sample SRT to a temp file and return path."""
    p = tmp_path / "video.en.srt"
    p.write_text(SAMPLE_SRT)
    return p


@pytest.fixture
def sample_vtt(tmp_path):
    """Write sample VTT to a temp file and return path."""
    p = tmp_path / "video.en.vtt"
    p.write_text(SAMPLE_VTT)
    return p


@pytest.fixture
def sample_meta():
    """Sample video metadata."""
    return VideoMeta(
        title="5 Hip Flexor Exercises You Need",
        channel="FitnessPro",
        url="https://www.youtube.com/watch?v=abc123",
        upload_date="20260319",
        video_id="abc123",
        duration_seconds=300,
        subtitles_available=True,
    )
