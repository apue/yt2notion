"""Standalone media download and ASR transcription workflow."""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from yt2notion.audio import extract_audio_from_video, get_duration
from yt2notion.config import AppConfig, ConfigError
from yt2notion.extract import extract_metadata, extract_video
from yt2notion.pipeline import _step_segment, _transcribe_from_audio
from yt2notion.process import seconds_to_display
from yt2notion.workspace import Workspace

if TYPE_CHECKING:
    from yt2notion.models.base import VideoMeta

DEFAULT_AGENT_CONFIG_PATH = Path.home() / ".yt2notion-agent" / "config.yaml"
DEFAULT_REPO_CONFIG_PATH = Path("config.yaml")


@dataclass
class MediaTranscribeResult:
    """Artifacts produced by the standalone transcription workflow."""

    metadata: VideoMeta
    workspace: Workspace
    video_path: Path | None
    audio_path: Path
    transcripts_path: Path
    transcript_markdown_path: Path

    def to_dict(self) -> dict:
        """Return a JSON-serializable summary for CLI and agent wrappers."""
        return {
            "video_id": self.metadata.video_id,
            "title": self.metadata.title,
            "channel": self.metadata.channel,
            "url": self.metadata.url,
            "workspace_dir": str(self.workspace.dir),
            "video_path": str(self.video_path) if self.video_path else None,
            "audio_path": str(self.audio_path),
            "transcripts_path": str(self.transcripts_path),
            "transcript_markdown_path": str(self.transcript_markdown_path),
        }


def resolve_media_transcribe_config_path(config_path: str | None) -> Path:
    """Resolve config for transcribe command.

    Defaults to the local agent runtime config before falling back to repo config.
    """
    if config_path:
        explicit = Path(config_path).expanduser()
        if explicit.exists():
            return explicit
        raise ConfigError(f"Config file not found: {config_path}")

    candidates = [DEFAULT_AGENT_CONFIG_PATH, DEFAULT_REPO_CONFIG_PATH]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    tried = ", ".join(str(path) for path in candidates)
    raise ConfigError(f"Config file not found. Tried: {tried}")


def transcribe_media(
    url: str,
    config: AppConfig,
    *,
    workspace_dir: str | None = None,
    keep_video: bool = True,
    verbose: bool = False,
) -> MediaTranscribeResult:
    """Download media, extract audio, transcribe via configured ASR, and save artifacts."""
    raw_config = {
        "extract": config.extract,
        "model": config.model,
        "storage": config.storage,
        "credit": config.credit,
        "output": config.output,
    }

    metadata = extract_metadata(url)
    workspace_id = metadata.video_id or _stable_workspace_id(metadata.url or url)
    base_dir = Path(workspace_dir or config.workspace.get("base_dir", "./workspace")).expanduser()
    ws = Workspace(base_dir, workspace_id)
    ws.save_metadata(metadata)
    ws.discard_transcribe_artifacts(audio_path=ws.audio_path)
    ws.discard_video_artifacts()
    ws.clear_asr_fallback_used()
    markdown_path = ws.dir / "transcript.md"
    if markdown_path.exists():
        markdown_path.unlink()

    cookies_from = config.extract.get("cookies_from")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        downloaded_video = extract_video(
            url,
            tmp_path,
            video_id=metadata.video_id,
            cookies_from=cookies_from,
        )
        saved_video = ws.save_video(downloaded_video) if keep_video else None
        source_video = saved_video or downloaded_video
        audio_path = extract_audio_from_video(source_video, ws.dir / "audio.mp3")

    if metadata.duration_seconds == 0:
        metadata.duration_seconds = int(get_duration(audio_path))
        ws.save_metadata(metadata)

    segments = _step_segment(metadata, raw_config, verbose)
    ws.save_segments(segments)

    from yt2notion.transcribe import create_fallback_transcriber, create_transcriber

    asr_cfg = config.extract.get("asr", {})
    primary_backend = asr_cfg.get("backend", "remote")
    fallback_backend = asr_cfg.get("fallback_backend")
    fallback_transcriber = None
    transcriber = create_transcriber(raw_config)

    def _load_fallback_transcriber():
        nonlocal fallback_transcriber
        if not fallback_backend:
            return None
        if fallback_transcriber is None:
            fallback_transcriber = create_fallback_transcriber(raw_config)
        return fallback_transcriber

    transcripts = _transcribe_from_audio(
        audio_path,
        segments,
        metadata,
        raw_config,
        ws,
        verbose,
        transcriber=transcriber,
        primary_backend=primary_backend,
        fallback_backend=fallback_backend,
        fallback_transcriber_factory=_load_fallback_transcriber,
    )
    ws.save_transcripts(transcripts)

    transcript_markdown = render_media_transcript_markdown(metadata, transcripts, primary_backend)
    markdown_path.write_text(transcript_markdown, encoding="utf-8")

    return MediaTranscribeResult(
        metadata=metadata,
        workspace=ws,
        video_path=ws.video_path,
        audio_path=audio_path,
        transcripts_path=ws.dir / "transcripts.json",
        transcript_markdown_path=markdown_path,
    )


def render_media_transcript_markdown(
    metadata: VideoMeta,
    transcript_segments: list[dict],
    asr_backend: str,
) -> str:
    """Render a readable Markdown transcript with source metadata."""
    lines = [
        f"# Transcript: {metadata.title}",
        "",
        f"- Channel: {metadata.channel}",
        f"- URL: {metadata.url}",
        f"- ASR backend: {asr_backend}",
        "",
    ]
    for seg in transcript_segments:
        start = int(seg.get("start_seconds", 0))
        title = str(seg.get("title", "")).strip() or "Segment"
        text = str(seg.get("text", "")).strip()
        lines.extend(
            [
                f"## [{seconds_to_display(start)}] {title}",
                "",
                text,
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def write_result_json(result: MediaTranscribeResult) -> str:
    """Serialize CLI result summary as formatted JSON."""
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


def _stable_workspace_id(value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    return f"media-{digest}"
