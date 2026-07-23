"""Obsidian source/A/B bundle storage adapter."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from yt2notion.process import seconds_to_display

if TYPE_CHECKING:
    from yt2notion.models.base import NoteBundle, NoteDocument, VideoMeta


class ObsidianStorageError(Exception):
    """Raised when the configured Obsidian vault cannot be used."""


_INVALID_FILENAME_CHARS = re.compile(r'[/\\:*?"<>|\[\]#]')
_MAX_TITLE_LEN = 100


def _sanitize_title(title: str) -> str:
    """Return a filesystem-safe note title."""
    clean = _INVALID_FILENAME_CHARS.sub("", title).strip() or "Untitled"
    return clean[:_MAX_TITLE_LEN].rstrip()


def _detect_media_type(url: str) -> str:
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    return "podcast"


def _navigation(
    source_stem: str,
    guide_stem: str,
    longform_stem: str,
    current_variant: str,
) -> list[str]:
    if current_variant == "source":
        targets = [guide_stem, longform_stem]
    elif current_variant == "a_guide":
        targets = [source_stem, longform_stem]
    else:
        targets = [source_stem, guide_stem]
    return [f"- [[{target}]]" for target in targets]


def _render_note(
    note: NoteDocument,
    metadata: VideoMeta,
    today: str,
    *,
    source_stem: str,
    guide_stem: str,
    longform_stem: str,
) -> str:
    frontmatter = {
        "source_url": metadata.url,
        "channel": metadata.channel or metadata.series or "Unknown",
        "title": note.title,
        "media_type": _detect_media_type(metadata.url),
        "duration": seconds_to_display(metadata.duration_seconds),
        "date_processed": today,
        "tags": note.tags,
        "variant": note.variant,
    }
    frontmatter_yaml = yaml.dump(
        frontmatter,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip()
    nav = "\n".join(
        [
            "## 导航",
            "",
            *_navigation(source_stem, guide_stem, longform_stem, note.variant),
        ]
    )
    return (
        "\n\n".join(
            [
                f"---\n{frontmatter_yaml}\n---",
                nav,
                note.markdown.strip(),
            ]
        ).strip()
        + "\n"
    )


class ObsidianStorage:
    """Write source/A/B note bundles to an Obsidian vault."""

    def __init__(
        self,
        vault_path: str,
        summaries_dir: str = "yt2notion/summaries",
    ) -> None:
        self.vault_path = Path(vault_path).expanduser()
        self.summaries_dir = summaries_dir
        if not self.vault_path.is_dir():
            raise ObsidianStorageError(
                f"Vault path does not exist or is not a directory: {vault_path}"
            )

    def save_note_bundle(self, bundle: NoteBundle, metadata: VideoMeta) -> str:
        """Write three linked notes and return the source-note path."""
        today = date.today().isoformat()
        source_file, guide_file, longform_file = self._resolve_bundle_paths(metadata, today)
        paths_and_notes = (
            (source_file, bundle.source),
            (guide_file, bundle.guide),
            (longform_file, bundle.longform),
        )

        for path, note in paths_and_notes:
            path.write_text(
                _render_note(
                    note,
                    metadata,
                    today,
                    source_stem=source_file.stem,
                    guide_stem=guide_file.stem,
                    longform_stem=longform_file.stem,
                ),
                encoding="utf-8",
            )

        return str(source_file)

    def _resolve_bundle_paths(self, metadata: VideoMeta, today: str) -> tuple[Path, Path, Path]:
        summaries_path = self.vault_path / self.summaries_dir
        summaries_path.mkdir(parents=True, exist_ok=True)
        base = _sanitize_title(metadata.title)
        counter = 1
        while True:
            stem = f"{today} {base}" if counter == 1 else f"{today} {base}-{counter}"
            paths = (
                summaries_path / f"{stem}.md",
                summaries_path / f"{stem} - 导读.md",
                summaries_path / f"{stem} - 扩展.md",
            )
            if not any(path.exists() for path in paths):
                return paths
            counter += 1
