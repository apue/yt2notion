"""Provider-independent translation strategies and strict response validation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from yt2notion.models._parsers import extract_json_array
from yt2notion.prompts import load_prompt, render_prompt
from yt2notion.translation_experiment.models import (
    SourceChapter,
    TranslationItem,
)

if TYPE_CHECKING:
    from yt2notion.models.llm import LLMCaller


class TranslationResponseError(ValueError):
    """Raised when a model response violates the experiment contract."""


class TranslationGenerator:
    """Generate both controlled translation candidates through one caller."""

    def __init__(self, caller: LLMCaller) -> None:
        self.caller = caller
        self.system_prompt = load_prompt("translation_experiment_system")

    def translate_whole_chapters(
        self, chapters: tuple[SourceChapter, ...]
    ) -> tuple[TranslationItem, ...]:
        """Translate each chapter as one unit in one batched provider call."""
        source = [
            {
                "chapter_id": chapter.chapter_id,
                "title": chapter.title,
                "source_text": chapter.source_text,
            }
            for chapter in chapters
        ]
        prompt = render_prompt(
            "translation_experiment_whole",
            source_json=json.dumps(source, ensure_ascii=False, indent=2),
        )
        raw = self.caller.call(self.system_prompt, prompt, max_tokens=16_000)
        return _parse_translations(
            raw,
            expected_ids=[chapter.chapter_id for chapter in chapters],
            id_field="chapter_id",
        )

    def translate_semantic_blocks(
        self, chapters: tuple[SourceChapter, ...]
    ) -> tuple[TranslationItem, ...]:
        """Translate stable semantic blocks with full chapter context in one call."""
        source = [
            {
                "chapter_id": chapter.chapter_id,
                "title": chapter.title,
                "blocks": [
                    {"block_id": block.block_id, "source_text": block.source_text}
                    for block in chapter.blocks
                ],
            }
            for chapter in chapters
        ]
        prompt = render_prompt(
            "translation_experiment_blocks",
            source_json=json.dumps(source, ensure_ascii=False, indent=2),
        )
        raw = self.caller.call(self.system_prompt, prompt, max_tokens=16_000)
        return _parse_translations(
            raw,
            expected_ids=[block.block_id for chapter in chapters for block in chapter.blocks],
            id_field="block_id",
        )


def _parse_translations(
    raw: str, *, expected_ids: list[str], id_field: str
) -> tuple[TranslationItem, ...]:
    payload = extract_json_array(raw)
    if not payload:
        raise TranslationResponseError("model response did not contain a JSON array")

    items: list[TranslationItem] = []
    for index, record in enumerate(payload):
        if not isinstance(record, dict):
            raise TranslationResponseError(f"response item {index} is not an object")
        source_id = record.get(id_field)
        translation = record.get("translation")
        if not isinstance(source_id, str) or not source_id.strip():
            raise TranslationResponseError(f"response item {index} has invalid {id_field}")
        if not isinstance(translation, str) or not translation.strip():
            raise TranslationResponseError(f"response item {index} has empty translation")
        items.append(TranslationItem(source_id=source_id, translation=translation.strip()))

    actual_ids = [item.source_id for item in items]
    if actual_ids != expected_ids:
        raise TranslationResponseError(
            "response IDs must exactly match source order: "
            f"expected {expected_ids}, got {actual_ids}"
        )
    return tuple(items)
