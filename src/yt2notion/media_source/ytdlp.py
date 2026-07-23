"""yt-dlp backed MediaSource adapter."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import typer

from yt2notion.audio import extract_audio_from_video, get_duration
from yt2notion.extract import (
    ExtractionError,
    extract_audio,
    extract_metadata,
    extract_subtitles_with_source,
    extract_video,
    extract_webpage_transcript,
    write_transcript_srt,
)
from yt2notion.media_source.base import (
    ContentMediaAcquireResult,
    MediaAcquireRequest,
    MediaAcquireResult,
    MediaAcquisitionError,
    TranscriptMediaAcquireResult,
)
from yt2notion.process import seconds_to_display
from yt2notion.workspace import Workspace


class YtDlpMediaSource:
    """Acquire media through the existing yt-dlp extraction implementation."""

    def __init__(self, config: dict, *, verbose: bool = False) -> None:
        self.config = config
        self.verbose = verbose

    def acquire(self, request: MediaAcquireRequest) -> MediaAcquireResult:
        """Acquire media according to the requested use-case profile."""
        if request.profile == "content":
            return self._acquire_content(request)
        if request.profile == "transcript":
            return self._acquire_transcript(request)
        raise ValueError(f"Unknown media acquisition profile: {request.profile!r}")

    def _acquire_content(self, request: MediaAcquireRequest) -> MediaAcquireResult:
        if self.verbose:
            typer.echo("Extracting metadata...")
        metadata = extract_metadata(request.url)
        if self.verbose:
            typer.echo(f"  Title: {metadata.title}")
            typer.echo(f"  Channel: {metadata.channel}")
            duration = (
                seconds_to_display(metadata.duration_seconds)
                if metadata.duration_seconds
                else "unknown"
            )
            typer.echo(f"  Duration: {duration}")
            typer.echo(f"  Chapters: {len(metadata.chapters)} found")
            typer.echo(f"  Subtitles available: {metadata.subtitles_available}")

        ws = Workspace(request.workspace_base_dir, metadata.video_id)
        try:
            ws.save_metadata(metadata)

            subtitle_path: Path | None = None
            subtitle_source: str | None = None
            audio_path: Path | None = None
            if metadata.subtitles_available:
                if self.verbose:
                    typer.echo("Downloading subtitles...")
                try:
                    with tempfile.TemporaryDirectory() as tmp_dir:
                        sub_path, subtitle_source = extract_subtitles_with_source(
                            request.url,
                            self.config,
                            Path(tmp_dir),
                            video_id=metadata.video_id,
                        )
                        subtitle_path = ws.save_subtitles(sub_path)
                        ws.save_subtitle_source(subtitle_source)
                        if self.verbose:
                            typer.echo(f"  Saved: subtitles{sub_path.suffix}")
                except ExtractionError:
                    if self.verbose:
                        typer.echo("  Subtitle download failed, downloading audio instead...")
                    audio_path = self._acquire_webpage_or_audio(request, metadata, ws)
            else:
                audio_path = self._acquire_webpage_or_audio(request, metadata, ws)

            return ContentMediaAcquireResult(
                metadata=metadata,
                workspace=ws,
                audio_path=audio_path or ws.audio_path,
                subtitle_path=subtitle_path or ws.subtitle_path,
                subtitle_source=subtitle_source or ws.load_subtitle_source(),
            )
        except Exception as exc:
            raise MediaAcquisitionError(ws, exc) from exc

    def _acquire_transcript(self, request: MediaAcquireRequest) -> MediaAcquireResult:
        metadata = extract_metadata(request.url)
        workspace_id = metadata.video_id or _stable_workspace_id(metadata.url or request.url)
        ws = Workspace(request.workspace_base_dir, workspace_id)
        try:
            ws.save_metadata(metadata)
            ws.discard_transcribe_artifacts(audio_path=ws.audio_path)
            ws.discard_video_artifacts()
            ws.clear_asr_fallback_used()
            markdown_path = ws.dir / "transcript.md"
            if markdown_path.exists():
                markdown_path.unlink()

            cookies_from = self.config.get("extract", {}).get("cookies_from")
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                downloaded_video = extract_video(
                    request.url,
                    tmp_path,
                    video_id=metadata.video_id,
                    cookies_from=cookies_from,
                )
                saved_video = ws.save_video(downloaded_video) if request.keep_video else None
                source_video = saved_video or downloaded_video
                audio_path = extract_audio_from_video(source_video, ws.dir / "audio.mp3")

            if metadata.duration_seconds == 0:
                metadata.duration_seconds = int(get_duration(audio_path))
                ws.save_metadata(metadata)

            return TranscriptMediaAcquireResult(
                metadata=metadata,
                workspace=ws,
                audio_path=audio_path,
                video_path=saved_video,
            )
        except Exception as exc:
            raise MediaAcquisitionError(ws, exc) from exc

    def _acquire_webpage_or_audio(
        self,
        request: MediaAcquireRequest,
        metadata,
        ws: Workspace,
    ) -> Path | None:
        if self._download_webpage_transcript(request.url, metadata, ws):
            return None
        return self._download_audio(request.url, metadata, self.config, ws)

    def _download_audio(self, url: str, metadata, config: dict, ws: Workspace) -> Path:
        if self.verbose:
            typer.echo("Downloading audio...")
        cookies_from = config.get("extract", {}).get("cookies_from")
        with tempfile.TemporaryDirectory() as tmp_dir:
            audio_path = extract_audio(
                url,
                Path(tmp_dir),
                video_id=metadata.video_id,
                cookies_from=cookies_from,
            )
            saved = ws.save_audio(audio_path)
            if self.verbose:
                size_mb = saved.stat().st_size / 1e6
                typer.echo(f"  Saved: {saved.name} ({size_mb:.1f} MB)")

        if metadata.duration_seconds == 0:
            duration = get_duration(saved)
            metadata.duration_seconds = int(duration)
            ws.save_metadata(metadata)
            if self.verbose:
                typer.echo(
                    f"  Duration (from audio): {seconds_to_display(metadata.duration_seconds)}"
                )
        return saved

    def _download_webpage_transcript(self, url: str, metadata, ws: Workspace) -> bool:
        try:
            entries = extract_webpage_transcript(url, metadata)
        except Exception:
            return False

        if not entries:
            return False

        with tempfile.TemporaryDirectory() as tmp_dir:
            transcript_path = Path(tmp_dir) / f"{metadata.video_id or 'transcript'}.srt"
            write_transcript_srt(entries, transcript_path)
            saved = ws.save_subtitles(transcript_path)
            ws.save_subtitle_source("webpage_transcript")

        if self.verbose:
            typer.echo(f"  Found webpage transcript: {saved.name} ({len(entries)} entries)")
        return True


def _stable_workspace_id(value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    return f"media-{digest}"
