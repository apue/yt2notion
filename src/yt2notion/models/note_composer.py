"""Provider-independent note composition."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from yt2notion.models._parsers import (
    parse_note_document_json,
    parse_note_metadata_json,
)
from yt2notion.prompts import load_prompt

if TYPE_CHECKING:
    from yt2notion.models.base import NoteDocument, NoteMetadata, VideoMeta
    from yt2notion.models.llm import LLMCaller


def _source_context(metadata: VideoMeta) -> dict[str, object]:
    return {
        "video_id": metadata.video_id,
        "title": metadata.title,
        "channel": metadata.channel,
        "url": metadata.url,
        "duration_seconds": metadata.duration_seconds,
        "description": metadata.description,
        "series": metadata.series,
    }


def _note_payload(note: NoteDocument) -> dict[str, object]:
    return {
        "title": note.title,
        "markdown": note.markdown,
        "tags": note.tags,
        "variant": note.variant,
    }


class NoteComposer:
    """Compose source/A/B notes through one injected LLM caller."""

    def __init__(self, caller: LLMCaller) -> None:
        self.caller = caller

    def compose_guide_note(
        self,
        transcript: str,
        metadata: VideoMeta,
        *,
        target_chars: int,
        prompt_name: str = "compose_guide",
    ) -> NoteDocument:
        raw = self._call(
            prompt_name,
            {
                "source": _source_context(metadata),
                "target_chars": target_chars,
                "transcript": transcript,
            },
            max_tokens=8192,
        )
        return parse_note_document_json(raw, expected_variant="a_guide")

    def compose_longform_note(
        self,
        transcript: str,
        guide_note: NoteDocument,
        metadata: VideoMeta,
        *,
        target_chars: int,
        prompt_name: str = "compose_longform",
    ) -> NoteDocument:
        raw = self._call(
            prompt_name,
            {
                "source": _source_context(metadata),
                "guide_note": _note_payload(guide_note),
                "target_chars": target_chars,
                "transcript": transcript,
            },
            max_tokens=8192,
        )
        return parse_note_document_json(raw, expected_variant="b_longform")

    def compose_note_metadata(
        self,
        guide_note: NoteDocument,
        longform_note: NoteDocument,
        metadata: VideoMeta,
        *,
        prompt_name: str = "compose_note_metadata",
    ) -> NoteMetadata:
        raw = self._call(
            prompt_name,
            {
                "source": _source_context(metadata),
                "guide_note": _note_payload(guide_note),
                "longform_note": _note_payload(longform_note),
            },
            max_tokens=4096,
        )
        return parse_note_metadata_json(raw)

    def _call(self, prompt_name: str, payload: dict[str, object], *, max_tokens: int) -> str:
        return self.caller.call(
            load_prompt(prompt_name),
            json.dumps(payload, ensure_ascii=False, indent=2),
            max_tokens=max_tokens,
        )
