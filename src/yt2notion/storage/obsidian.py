"""Obsidian source/A/B bundle storage adapter."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from yt2notion.models.base import (
    NOTE_VARIANT_GUIDE,
    NOTE_VARIANT_LONGFORM,
    NOTE_VARIANT_SOURCE,
    NoteVariant,
)
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
    note_stems: Mapping[NoteVariant, str],
    current_variant: NoteVariant,
) -> list[str]:
    linked_variants: dict[NoteVariant, tuple[NoteVariant, NoteVariant]] = {
        NOTE_VARIANT_SOURCE: (NOTE_VARIANT_GUIDE, NOTE_VARIANT_LONGFORM),
        NOTE_VARIANT_GUIDE: (NOTE_VARIANT_SOURCE, NOTE_VARIANT_LONGFORM),
        NOTE_VARIANT_LONGFORM: (NOTE_VARIANT_SOURCE, NOTE_VARIANT_GUIDE),
    }
    try:
        targets = linked_variants[current_variant]
    except KeyError as exc:
        raise ObsidianStorageError(f"Unknown note variant: {current_variant!r}") from exc
    return [f"- [[{note_stems[target]}]]" for target in targets]


def _render_note(
    note: NoteDocument,
    metadata: VideoMeta,
    today: str,
    *,
    note_stems: Mapping[NoteVariant, str],
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
            *_navigation(note_stems, note.variant),
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
        note_paths = self._resolve_bundle_paths(metadata, today)
        note_stems = {variant: path.stem for variant, path in note_paths.items()}
        notes = {
            NOTE_VARIANT_SOURCE: bundle.source,
            NOTE_VARIANT_GUIDE: bundle.guide,
            NOTE_VARIANT_LONGFORM: bundle.longform,
        }

        for variant, note in notes.items():
            path = note_paths[variant]
            path.write_text(
                _render_note(
                    note,
                    metadata,
                    today,
                    note_stems=note_stems,
                ),
                encoding="utf-8",
            )

        return str(note_paths[NOTE_VARIANT_SOURCE])

    def _resolve_bundle_paths(self, metadata: VideoMeta, today: str) -> dict[NoteVariant, Path]:
        summaries_path = self.vault_path / self.summaries_dir
        summaries_path.mkdir(parents=True, exist_ok=True)
        base = _sanitize_title(metadata.title)
        counter = 1
        while True:
            stem = f"{today} {base}" if counter == 1 else f"{today} {base}-{counter}"
            paths: dict[NoteVariant, Path] = {
                NOTE_VARIANT_SOURCE: summaries_path / f"{stem}.md",
                NOTE_VARIANT_GUIDE: summaries_path / f"{stem} - 导读.md",
                NOTE_VARIANT_LONGFORM: summaries_path / f"{stem} - 扩展.md",
            }
            if not any(path.exists() for path in paths.values()):
                return paths
            counter += 1
