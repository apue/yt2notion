"""Tests for subtitle processing."""

from __future__ import annotations

import pytest

from yt2notion.process import (
    Chunk,
    SubtitleEntry,
    chunk_by_time,
    clean_text,
    format_chunks,
    parse_srt,
    parse_subtitle_file,
    parse_vtt,
)


def test_parse_srt(sample_srt):
    entries = parse_srt(sample_srt)
    assert len(entries) == 4
    assert entries[0].start_seconds == pytest.approx(1.0)
    assert entries[0].end_seconds == pytest.approx(5.5)
    assert "Welcome" in entries[0].text


def test_parse_vtt(sample_vtt):
    entries = parse_vtt(sample_vtt)
    assert len(entries) == 4
    assert entries[0].start_seconds == pytest.approx(1.0)
    assert "Welcome" in entries[0].text


def test_srt_vtt_consistency(sample_srt, sample_vtt):
    srt_entries = parse_srt(sample_srt)
    vtt_entries = parse_vtt(sample_vtt)
    assert len(srt_entries) == len(vtt_entries)
    for srt, vtt in zip(srt_entries, vtt_entries, strict=False):
        assert srt.start_seconds == pytest.approx(vtt.start_seconds, abs=0.01)
        assert srt.text == vtt.text


def test_parse_subtitle_file_srt(sample_srt):
    entries = parse_subtitle_file(sample_srt)
    assert len(entries) == 4


def test_parse_subtitle_file_vtt(sample_vtt):
    entries = parse_subtitle_file(sample_vtt)
    assert len(entries) == 4


def test_parse_subtitle_file_unsupported(tmp_path):
    p = tmp_path / "video.ass"
    p.write_text("some content")
    with pytest.raises(Exception, match="Unsupported"):
        parse_subtitle_file(p)


def test_clean_text():
    assert clean_text("<b>bold</b> text") == "bold text"
    assert clean_text("line1\nline2") == "line1 line2"
    assert clean_text("too   many   spaces") == "too many spaces"
    assert clean_text("  leading trailing  ") == "leading trailing"


def test_chunk_by_time(sample_srt):
    entries = parse_srt(sample_srt)
    chunks = chunk_by_time(entries, chunk_seconds=120)
    # Entries at 1s, 5.5s (within first 120s), 124s, 243s -> 3 chunks
    assert len(chunks) >= 2
    assert chunks[0].start_seconds == 1


def test_chunk_boundary():
    entries = [
        SubtitleEntry(start_seconds=0, end_seconds=10, text="A"),
        SubtitleEntry(start_seconds=119, end_seconds=120, text="B"),
        SubtitleEntry(start_seconds=120, end_seconds=130, text="C"),
        SubtitleEntry(start_seconds=240, end_seconds=250, text="D"),
    ]
    chunks = chunk_by_time(entries, chunk_seconds=120)
    assert len(chunks) == 3
    assert chunks[0].text == "A B"
    assert chunks[1].text == "C"
    assert chunks[2].text == "D"


def test_empty_subtitle(tmp_path):
    p = tmp_path / "empty.srt"
    p.write_text("")
    entries = parse_srt(p)
    assert entries == []


def test_empty_vtt(tmp_path):
    p = tmp_path / "empty.vtt"
    p.write_text("")
    entries = parse_vtt(p)
    assert entries == []


def test_empty_entries_chunk():
    chunks = chunk_by_time([])
    assert chunks == []


def test_unicode_subtitle(tmp_path):
    srt_content = """\
1
00:00:01,000 --> 00:00:05,000
这是一段中文字幕测试

2
00:00:05,000 --> 00:00:10,000
日本語テスト
"""
    p = tmp_path / "unicode.srt"
    p.write_text(srt_content, encoding="utf-8")
    entries = parse_srt(p)
    assert len(entries) == 2
    assert "中文" in entries[0].text
    assert "日本語" in entries[1].text


def test_format_chunks():
    chunks = [
        Chunk(start_seconds=0, text="First chunk"),
        Chunk(start_seconds=120, text="Second chunk"),
    ]
    output = format_chunks(chunks, "abc123")
    assert "[CHUNK start=0:00]" in output
    assert "[CHUNK start=2:00]" in output
    assert "First chunk" in output
    assert "Second chunk" in output
