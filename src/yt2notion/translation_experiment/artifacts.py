"""Experiment metrics, deterministic blinding, and artifact rendering."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from yt2notion.process import seconds_to_display
from yt2notion.translation_experiment.models import (
    CandidateCheckpoint,
    CandidateIdentity,
    TranslationItem,
)

if TYPE_CHECKING:
    from yt2notion.models.base import VideoMeta
    from yt2notion.translation_experiment.models import SourceChapter

_WHITESPACE = re.compile(r"\s+")
ARTIFACT_SCHEMA_VERSION = 1


def source_fingerprint(chapters: tuple[SourceChapter, ...]) -> str:
    """Return a stable fingerprint for candidate checkpoint validation."""
    payload = json.dumps(
        [asdict(chapter) for chapter in chapters],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def write_source_artifact(
    output_dir: Path, chapters: tuple[SourceChapter, ...], fingerprint: str
) -> None:
    """Persist the exact source contract used by both strategies."""
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        output_dir / "source.json",
        {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "source_sha256": fingerprint,
            "chapters": [asdict(chapter) for chapter in chapters],
        },
    )


def save_candidate_checkpoint(
    path: Path,
    *,
    identity: CandidateIdentity,
    items: tuple[TranslationItem, ...],
    generation_seconds: float,
) -> None:
    """Persist one completed candidate immediately after provider success."""
    _write_json(
        path,
        {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "identity": asdict(identity),
            "generation_seconds": round(generation_seconds, 3),
            "items": [asdict(item) for item in items],
        },
    )


def load_candidate_checkpoint(
    path: Path,
    *,
    identity: CandidateIdentity,
    expected_ids: list[str],
) -> CandidateCheckpoint | None:
    """Load only a complete checkpoint for the exact source and strategy."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != ARTIFACT_SCHEMA_VERSION or payload.get(
        "identity"
    ) != asdict(identity):
        return None
    records = payload.get("items")
    generation_seconds = payload.get("generation_seconds")
    if not isinstance(records, list) or not isinstance(generation_seconds, int | float):
        return None
    items: list[TranslationItem] = []
    for record in records:
        if not isinstance(record, dict):
            return None
        source_id = record.get("source_id")
        translation = record.get("translation")
        if (
            not isinstance(source_id, str)
            or not isinstance(translation, str)
            or not translation.strip()
        ):
            return None
        items.append(TranslationItem(source_id=source_id, translation=translation.strip()))
    if [item.source_id for item in items] != expected_ids:
        return None
    return CandidateCheckpoint(items=tuple(items), generation_seconds=float(generation_seconds))


def write_experiment_artifacts(
    *,
    output_dir: Path,
    metadata: VideoMeta,
    chapters: tuple[SourceChapter, ...],
    whole: tuple[TranslationItem, ...],
    blocks: tuple[TranslationItem, ...],
    model_label: str,
    timings_seconds: dict[str, float],
    generation_timings_seconds: dict[str, float],
    reused_checkpoints: dict[str, bool],
) -> tuple[Path, Path, Path]:
    """Write source, candidates, diagnostics, blind review, and answer key."""
    output_dir.mkdir(parents=True, exist_ok=True)
    chapter_whole = {item.source_id: item.translation for item in whole}
    block_translations = {item.source_id: item.translation for item in blocks}
    chapter_blocks = {
        chapter.chapter_id: " ".join(block_translations[block.block_id] for block in chapter.blocks)
        for chapter in chapters
    }
    assignments = _balanced_assignments(metadata.video_id, chapters)

    answer_key_path = output_dir / "answer_key.json"
    _write_json(
        answer_key_path,
        {
            "warning": "Do not open before completing blind_review.md.",
            "assignments": assignments,
        },
    )

    manifest_path = output_dir / "manifest.json"
    _write_json(
        manifest_path,
        {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "video": {
                "id": metadata.video_id,
                "title": metadata.title,
                "channel": metadata.channel,
                "url": metadata.url,
            },
            "controlled_variables": {
                "model": model_label,
                "source": "identical canonical transcripts.json",
                "target_language": "zh-CN",
                "calls_per_strategy": 1,
                "formula_enrichment": "disabled",
            },
            "counts": {
                "chapters": len(chapters),
                "semantic_blocks": sum(len(chapter.blocks) for chapter in chapters),
            },
            "diagnostics": {
                "whole_chapter": _length_diagnostics(chapters, chapter_whole),
                "semantic_blocks": _length_diagnostics(chapters, chapter_blocks),
            },
            "timings_seconds": timings_seconds,
            "generation_timings_seconds": generation_timings_seconds,
            "reused_checkpoints": reused_checkpoints,
        },
    )

    blind_review_path = output_dir / "blind_review.md"
    blind_review_path.write_text(
        _render_blind_review(
            metadata=metadata,
            chapters=chapters,
            chapter_whole=chapter_whole,
            chapter_blocks=chapter_blocks,
            assignments=assignments,
        ),
        encoding="utf-8",
    )
    return blind_review_path, answer_key_path, manifest_path


def _balanced_assignments(
    video_id: str, chapters: tuple[SourceChapter, ...]
) -> dict[str, dict[str, str]]:
    whole_positions = ["A"] * ((len(chapters) + 1) // 2) + ["B"] * (len(chapters) // 2)
    ranked = sorted(
        chapters,
        key=lambda chapter: hashlib.sha256(f"{video_id}:{chapter.chapter_id}".encode()).digest(),
    )
    whole_position_by_id = {
        chapter.chapter_id: position
        for chapter, position in zip(ranked, whole_positions, strict=True)
    }
    return {
        chapter.chapter_id: {
            "A": "whole_chapter"
            if whole_position_by_id[chapter.chapter_id] == "A"
            else "semantic_blocks",
            "B": "semantic_blocks"
            if whole_position_by_id[chapter.chapter_id] == "A"
            else "whole_chapter",
        }
        for chapter in chapters
    }


def _length_diagnostics(
    chapters: tuple[SourceChapter, ...], translations: dict[str, str]
) -> list[dict[str, Any]]:
    return [
        {
            "chapter_id": chapter.chapter_id,
            "source_chars": len(chapter.source_text),
            "translation_chars": len(translations[chapter.chapter_id]),
            "translation_source_ratio": round(
                len(translations[chapter.chapter_id]) / len(chapter.source_text), 3
            ),
        }
        for chapter in chapters
    ]


def _render_blind_review(
    *,
    metadata: VideoMeta,
    chapters: tuple[SourceChapter, ...],
    chapter_whole: dict[str, str],
    chapter_blocks: dict[str, str],
    assignments: dict[str, dict[str, str]],
) -> str:
    lines = [
        f"# 翻译盲评：{metadata.title}",
        "",
        f"- 频道：{metadata.channel}",
        f"- 来源：{metadata.url}",
        "- 说明：A/B 标签已按章节做平衡盲化；请在完成评价前不要打开 `answer_key.json`。",
        "- 优先判断整体胜负或平局；维度分数可选。1=很差，5=很好。",
        "- 维度：忠实度、中文自然度、术语一致性、学习价值。",
        "",
    ]
    candidates = {
        "whole_chapter": chapter_whole,
        "semantic_blocks": chapter_blocks,
    }
    for chapter in chapters:
        mapping = assignments[chapter.chapter_id]
        candidate_a = candidates[mapping["A"]][chapter.chapter_id]
        candidate_b = candidates[mapping["B"]][chapter.chapter_id]
        lines.extend(
            [
                f"## {seconds_to_display(chapter.start_seconds)} {chapter.title}",
                "",
                "### 英文原文",
                "",
                _normalize_for_review(chapter.source_text),
                "",
                "### 候选 A",
                "",
                _normalize_for_review(candidate_a),
                "",
                "### 候选 B",
                "",
                _normalize_for_review(candidate_b),
                "",
                "### 评价",
                "",
                "- 整体：A / B / 平局",
                "- 忠实度：A __/5；B __/5",
                "- 中文自然度：A __/5；B __/5",
                "- 术语一致性：A __/5；B __/5",
                "- 学习价值：A __/5；B __/5",
                "- 关键问题或理由：",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _normalize_for_review(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
