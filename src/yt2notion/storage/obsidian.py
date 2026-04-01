"""Obsidian storage backend. Writes markdown files to vault."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from yt2notion.models.base import FUN_FACTS_CATEGORIES
from yt2notion.process import display_to_seconds, seconds_to_display

if TYPE_CHECKING:
    from yt2notion.models.base import ChineseContent, EntityResult, VideoMeta


class ObsidianStorageError(Exception):
    """Raised when Obsidian vault operations fail."""


# Characters not allowed in file names across OS
_INVALID_FILENAME_CHARS = re.compile(r'[/\\:*?"<>|]')
_MAX_TITLE_LEN = 100


def _sanitize_title(title: str) -> str:
    """Remove filesystem-unsafe characters and truncate."""
    clean = _INVALID_FILENAME_CHARS.sub("", title).strip()
    if not clean:
        clean = "Untitled"
    if len(clean) > _MAX_TITLE_LEN:
        clean = clean[:_MAX_TITLE_LEN].rstrip()
    return clean


def _resolve_unique_path(path: Path) -> Path:
    """If path exists, append -2, -3, etc. until unique."""
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _make_timestamp_link(timestamp: str, url: str) -> str:
    """Create a clickable timestamp link for YouTube, plain text for others."""
    secs = display_to_seconds(timestamp)
    if "youtube.com" in url or "youtu.be" in url:
        # Normalize to watch URL with time param
        video_id = ""
        if "youtu.be/" in url:
            video_id = url.split("youtu.be/")[1].split("?")[0]
        elif "v=" in url:
            video_id = url.split("v=")[1].split("&")[0]
        if video_id:
            return f"[{timestamp}](https://youtube.com/watch?v={video_id}&t={secs})"
    # Non-YouTube (podcast etc.): plain timestamp
    return f"[{timestamp}]"


def _detect_media_type(url: str) -> str:
    """Infer media type from URL."""
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    return "podcast"


class ObsidianStorage:
    """Storage backend that writes markdown files to an Obsidian vault."""

    def __init__(
        self,
        vault_path: str,
        summaries_dir: str = "yt2notion/summaries",
        transcripts_dir: str = "yt2notion/transcripts",
    ) -> None:
        self.vault_path = Path(vault_path)
        self.summaries_dir = summaries_dir
        self.transcripts_dir = transcripts_dir

        if not self.vault_path.is_dir():
            raise ObsidianStorageError(
                f"Vault path does not exist or is not a directory: {vault_path}"
            )

    def _resolve_transcript_path(self, metadata: VideoMeta) -> Path:
        """Create transcripts dir and return a unique transcript file path."""
        today = date.today().isoformat()
        sanitized = _sanitize_title(metadata.title)
        transcripts_path = self.vault_path / self.transcripts_dir
        transcripts_path.mkdir(parents=True, exist_ok=True)
        return _resolve_unique_path(transcripts_path / f"T-{today} {sanitized}.md")

    def save(
        self,
        content: ChineseContent,
        metadata: VideoMeta,
        *,
        transcript_segments: list[dict] | None = None,
        entities: EntityResult | None = None,
    ) -> str:
        """Write summary + transcript files to vault. Return summary path."""
        today = date.today().isoformat()
        sanitized = _sanitize_title(metadata.title)

        summaries_path = self.vault_path / self.summaries_dir
        summaries_path.mkdir(parents=True, exist_ok=True)
        summary_file = _resolve_unique_path(summaries_path / f"{today} {sanitized}.md")

        transcript_file = self._resolve_transcript_path(metadata)
        transcript_stem = transcript_file.stem

        summary_md = self._render_summary(content, metadata, transcript_stem, today, entities)
        summary_file.write_text(summary_md, encoding="utf-8")

        if transcript_segments:
            transcript_md = self._render_transcript(
                metadata, transcript_segments, summary_file.stem
            )
            transcript_file.write_text(transcript_md, encoding="utf-8")

        return str(summary_file)

    def add_transcript_subpage(
        self,
        summary_path: str,
        transcript_segments: list[dict],
        metadata: VideoMeta,
    ) -> None:
        """Write transcript file for deferred long-content scenario.

        summary_path is the summary file path returned by save().
        """
        summary_file = Path(summary_path)
        transcript_file = self._resolve_transcript_path(metadata)

        transcript_md = self._render_transcript(metadata, transcript_segments, summary_file.stem)
        transcript_file.write_text(transcript_md, encoding="utf-8")

    def _render_summary(
        self,
        content: ChineseContent,
        metadata: VideoMeta,
        transcript_stem: str,
        today: str,
        entities: EntityResult | None = None,
    ) -> str:
        """Render the summary markdown file."""
        url = metadata.url
        channel = metadata.channel or metadata.series or "Unknown"
        duration = seconds_to_display(metadata.duration_seconds)
        media_type = _detect_media_type(url)

        # Frontmatter
        fm: dict = {
            "source_url": url,
            "channel": channel,
            "title": metadata.title,
            "media_type": media_type,
            "duration": duration,
        }
        if metadata.upload_date:
            # Convert YYYYMMDD to YYYY-MM-DD
            ud = metadata.upload_date
            if len(ud) == 8:
                fm["date_published"] = f"{ud[:4]}-{ud[4:6]}-{ud[6:8]}"
        fm["date_processed"] = today
        fm["tags"] = content.tags
        fm["transcript"] = f"[[{transcript_stem}]]"

        frontmatter = (
            "---\n"
            + yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False).rstrip()
            + "\n---"
        )

        # Body
        lines = [
            frontmatter,
            "",
            f"# {metadata.title}",
            "",
            f"> **{channel}** \u00b7 {duration} \u00b7 [\u539f\u59cb\u89c6\u9891]({url})",
            "",
            "## \u6982\u8ff0",
            "",
            content.overview,
            "",
            "## \u8981\u70b9",
            "",
        ]

        for kp in content.key_points:
            ts = kp.get("timestamp", "")
            title = kp.get("title", "")
            summary = kp.get("summary", "")
            ts_link = _make_timestamp_link(ts, url) if ts else ""
            lines.append(f"- {ts_link} **{title}**\uff1a{summary}")

        # Fun facts
        if content.fun_facts:
            lines.append("")
            lines.append("## 有趣发现")
            for cat_key, cat_label in FUN_FACTS_CATEGORIES.items():
                items = content.fun_facts.get(cat_key, [])
                if not items:
                    continue
                lines.append("")
                lines.append(f"### {cat_label}")
                for item in items:
                    lines.append(f"- {item}")

        # Entities section
        if entities and entities.entities:
            if entities.is_entity_centric:
                lines.append("")
                lines.append("## Entities")
                # Build lookup: entity name -> Entity object
                entity_map = {e.name: e for e in entities.entities}
                # Build relations lookup: from_name -> list of (relation, to_name)
                relations_by_from: dict[str, list[tuple[str, str]]] = {}
                for rel in entities.relations:
                    from_name = rel.get("from", "")
                    to_name = rel.get("to", "")
                    relation = rel.get("relation", "")
                    if from_name not in relations_by_from:
                        relations_by_from[from_name] = []
                    relations_by_from[from_name].append((relation, to_name))
                # Group entities by type, preserving entity_types order
                type_order = list(entities.entity_types)
                # Collect any types not in entity_types at the end
                extra_types = [e.type for e in entities.entities if e.type not in type_order]
                for t in extra_types:
                    if t not in type_order:
                        type_order.append(t)
                entities_by_type: dict[str, list] = {}
                for e in entities.entities:
                    entities_by_type.setdefault(e.type, []).append(e)
                for type_key in type_order:
                    group = entities_by_type.get(type_key, [])
                    if not group:
                        continue
                    lines.append("")
                    lines.append(f"**{type_key.capitalize()}**")
                    for ent in group:
                        name_part = f"[[{ent.name}]]" if ent.linkable else ent.name
                        # First attribute value in parentheses
                        attr_part = ""
                        if ent.attributes:
                            first_val = next(iter(ent.attributes.values()))
                            attr_part = f" ({first_val})"
                        # Related entities from relations where this entity is "from"
                        related_parts: list[str] = []
                        for _rel, to_name in relations_by_from.get(ent.name, []):
                            target = entity_map.get(to_name)
                            if target and target.linkable:
                                related_parts.append(f"[[{to_name}]]")
                            else:
                                related_parts.append(to_name)
                        related_str = ""
                        if related_parts:
                            related_str = " — " + ", ".join(related_parts)
                        lines.append(f"- {name_part}{attr_part}{related_str}")
            else:
                # Non-entity-centric: one-liner with linkable entities only
                linkable = [e for e in entities.entities if e.linkable]
                if linkable:
                    mentions = ", ".join(f"[[{e.name}]]" for e in linkable)
                    lines.append("")
                    lines.append(f"Mentioned: {mentions}")

        lines.append("")
        lines.append("## 标签")
        lines.append("")
        lines.append(" ".join(f"#{tag}" for tag in content.tags))
        lines.append("")

        return "\n".join(lines)

    def _render_transcript(
        self,
        metadata: VideoMeta,
        segments: list[dict],
        summary_stem: str,
    ) -> str:
        """Render the transcript markdown file."""
        url = metadata.url

        # Frontmatter
        fm = {
            "parent": f"[[{summary_stem}]]",
            "source_url": url,
            "type": "transcript",
        }
        frontmatter = (
            "---\n"
            + yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False).rstrip()
            + "\n---"
        )

        lines = [
            frontmatter,
            "",
            f"# Transcript: {metadata.title}",
            "",
        ]

        for seg in segments:
            title = seg.get("title", "")
            start = seg.get("start_seconds", 0)
            end = seg.get("end_seconds", 0)
            text = seg.get("text", "")

            start_display = seconds_to_display(start)
            end_display = seconds_to_display(end)
            ts_link = _make_timestamp_link(start_display, url)

            lines.append(f"## {title} ({start_display}-{end_display})")
            lines.append("")
            lines.append(ts_link)
            lines.append("")
            lines.append(text)
            lines.append("")

        return "\n".join(lines)
