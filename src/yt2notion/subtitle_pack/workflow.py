"""Bounded LLM workflow for context-aware subtitle translation and review."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from yt2notion.prompts import render_prompt
from yt2notion.runtime import CheckpointStore, RuntimeObserver
from yt2notion.subtitle_pack.artifacts import (
    fingerprint,
    prompt_fingerprint,
)
from yt2notion.subtitle_pack.models import BilingualCue, SourceCue
from yt2notion.subtitle_pack.validation import (
    SubtitlePackError,
    parse_generated,
    parse_json_array,
    parse_json_object,
)

if TYPE_CHECKING:
    from yt2notion.models.base import VideoMeta
    from yt2notion.models.llm import LLMCaller

_QUALITY_BATCH_CHAR_BUDGET = 12_000
_GENERATION_BATCH_CHAR_BUDGET = 8_000
_CONTEXT_CHAR_BUDGET = 24_000
_OVERLAP_CUES = 3


class SubtitleLLMWorkflow:
    """Build context, generate bilingual cues, and repair semantic issues."""

    def __init__(
        self,
        caller: LLMCaller,
        *,
        schema_version: int,
        model_label: str,
        target_language: str,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.caller = caller
        self.schema_version = schema_version
        self.model_label = model_label
        self.target_language = target_language
        self.progress_callback = progress_callback
        self.system_prompt = (
            "You edit professional subtitles. Treat IDs and timing as immutable. "
            "Return only the requested JSON and never omit or invent an ID."
        )

    def build_context(
        self,
        metadata: VideoMeta,
        cues: Sequence[SourceCue],
        workspace_dir: Path,
        source_fingerprint: str,
        profile: RuntimeObserver,
    ) -> dict[str, object]:
        """Build or restore bounded domain context for the complete source."""
        checkpoint = workspace_dir / "subtitle_checkpoints" / "context.json"
        source_evidence = _metadata_context(metadata)
        identity = {
            "schema_version": self.schema_version,
            "source_sha256": source_fingerprint,
            "metadata_sha256": fingerprint(source_evidence),
            "model_label": self.model_label,
            "prompt_sha256": prompt_fingerprint("subtitle_context"),
        }
        checkpoints: CheckpointStore[object] = CheckpointStore(profile)
        cached = checkpoints.load(checkpoint, identity=identity)
        if isinstance(cached, dict):
            self._progress("Subtitle context: reused checkpoint")
            return cached

        transcript = "\n".join(f"{cue.id}: {cue.original_text}" for cue in cues)
        sections = _split_text(transcript, _CONTEXT_CHAR_BUDGET)
        section_briefs: list[dict[str, object]] = []
        for index, section in enumerate(sections, start=1):
            payload = {
                "video": source_evidence,
                "section": section,
                "section_index": index,
                "section_count": len(sections),
            }
            prompt = render_prompt(
                "subtitle_context",
                source_json=json.dumps(payload, ensure_ascii=False),
            )
            raw = self._call(
                prompt,
                max_tokens=2_000,
                operation="context_section",
                batch_id=f"context-{index:03d}",
                cue_start=None,
                cue_end=None,
                profile=profile,
            )
            section_briefs.append(parse_json_object(raw, "subtitle context"))

        reduction_level = section_briefs
        level = 0
        while len(reduction_level) > 1:
            level += 1
            serialized = [json.dumps(item, ensure_ascii=False) for item in reduction_level]
            groups = _group_strings(serialized, _CONTEXT_CHAR_BUDGET)
            next_level: list[dict[str, object]] = []
            for group_index, group in enumerate(groups, start=1):
                reduction_payload = {
                    "video": source_evidence,
                    "section_briefs": [json.loads(item) for item in group],
                    "instruction": (
                        "Merge into one bounded global brief; retain names and terminology."
                    ),
                }
                prompt = render_prompt(
                    "subtitle_context",
                    source_json=json.dumps(reduction_payload, ensure_ascii=False),
                )
                raw = self._call(
                    prompt,
                    max_tokens=3_000,
                    operation="context_reduce",
                    batch_id=f"context-reduce-{level:02d}-{group_index:03d}",
                    cue_start=None,
                    cue_end=None,
                    profile=profile,
                )
                next_level.append(parse_json_object(raw, "reduced subtitle context"))
            reduction_level = next_level

        context = {
            "source_evidence": source_evidence,
            "global_brief": reduction_level[0],
            "section_contexts": section_briefs,
        }
        checkpoints.save(checkpoint, identity=identity, result=context)
        return context

    def generate_all(
        self,
        cues: Sequence[SourceCue],
        source_kind: str,
        context: dict[str, object],
        context_fingerprint: str,
        workspace_dir: Path,
        profile: RuntimeObserver,
    ) -> list[BilingualCue]:
        """Generate all owned cue batches with overlap and checkpoint recovery."""
        batches = _batch_cues(cues, _GENERATION_BATCH_CHAR_BUDGET)
        output: list[BilingualCue] = []
        for index, (start, end) in enumerate(batches, start=1):
            owned = cues[start:end]
            visible = cues[max(0, start - _OVERLAP_CUES) : min(len(cues), end + _OVERLAP_CUES)]
            identity = {
                "schema_version": self.schema_version,
                "context_sha256": context_fingerprint,
                "source_sha256": fingerprint([asdict(cue) for cue in owned]),
                "model_label": self.model_label,
                "prompt_sha256": prompt_fingerprint("subtitle_generate"),
                "source_kind": source_kind,
                "target_language": self.target_language,
                "ordered_ids": [cue.id for cue in owned],
                "generation_batch_char_budget": _GENERATION_BATCH_CHAR_BUDGET,
                "overlap_cues": _OVERLAP_CUES,
            }
            batch_id = f"batch-{index:04d}"
            checkpoint = workspace_dir / "subtitle_checkpoints" / f"{batch_id}.json"
            checkpoints: CheckpointStore[object] = CheckpointStore(profile)
            cached = checkpoints.load(checkpoint, identity=identity)
            reused_checkpoint = isinstance(cached, list)
            if isinstance(cached, list):
                records = cached
                self._progress(
                    f"Subtitle generation {batch_id}: reused checkpoint "
                    f"({owned[0].id}..{owned[-1].id})"
                )
            else:
                payload = {
                    "mode": "translate_only"
                    if source_kind == "manual_subtitle"
                    else "correct_then_translate",
                    "target_language": self.target_language,
                    "global_context": context["global_brief"],
                    "owned_ids": [cue.id for cue in owned],
                    "visible_cues": [asdict(cue) for cue in visible],
                }
                prompt = render_prompt(
                    "subtitle_generate",
                    source_json=json.dumps(payload, ensure_ascii=False),
                )
                raw = self._call(
                    prompt,
                    max_tokens=8_000,
                    operation="generate",
                    batch_id=batch_id,
                    cue_start=owned[0].id,
                    cue_end=owned[-1].id,
                    profile=profile,
                )
                records = parse_json_array(raw, "subtitle generation")
            parsed = parse_generated(records, owned, source_kind)
            if not reused_checkpoint:
                checkpoints.save(checkpoint, identity=identity, result=records)
            output.extend(parsed)
        return output

    def semantic_quality(
        self,
        cues: Sequence[BilingualCue],
        context: dict[str, object],
        profile: RuntimeObserver,
        *,
        operation: str = "semantic_quality",
    ) -> list[dict[str, str]]:
        """Return validated semantic issues from all quality batches."""
        issues: list[dict[str, str]] = []
        for index, (start, end) in enumerate(
            _batch_cues(cues, _QUALITY_BATCH_CHAR_BUDGET), start=1
        ):
            owned = cues[start:end]
            payload = {
                "global_context": context["global_brief"],
                "target_language": self.target_language,
                "cues": [asdict(cue) for cue in owned],
            }
            prompt = render_prompt(
                "subtitle_quality",
                source_json=json.dumps(payload, ensure_ascii=False),
            )
            raw = self._call(
                prompt,
                max_tokens=2_000,
                operation=operation,
                batch_id=f"quality-{index:04d}",
                cue_start=owned[0].id,
                cue_end=owned[-1].id,
                profile=profile,
            )
            records = parse_json_array(raw, "semantic quality")
            valid_ids = {cue.id for cue in owned}
            for record in records:
                if not isinstance(record, dict):
                    raise SubtitlePackError("semantic quality response must contain objects")
                cue_id = record.get("id")
                issue = record.get("issue")
                if cue_id not in valid_ids or not isinstance(issue, str) or not issue.strip():
                    raise SubtitlePackError("semantic quality response contains an invalid issue")
                issues.append({"id": str(cue_id), "issue": issue.strip()})
        return issues

    def repair_issues(
        self,
        cues: Sequence[BilingualCue],
        issues: Sequence[dict[str, str]],
        source_kind: str,
        context: dict[str, object],
        profile: RuntimeObserver,
    ) -> list[BilingualCue]:
        """Repair only cue IDs named by semantic quality checks."""
        by_id = {cue.id: cue for cue in cues}
        issue_by_id = {issue["id"]: issue["issue"] for issue in issues}
        affected = [cue for cue in cues if cue.id in issue_by_id]
        replacements: dict[str, BilingualCue] = {}
        indices = {cue.id: index for index, cue in enumerate(cues)}
        for batch_index, (start, end) in enumerate(
            _batch_cues(affected, _QUALITY_BATCH_CHAR_BUDGET), start=1
        ):
            repair_batch = affected[start:end]
            visible_ids: set[str] = set()
            for cue in repair_batch:
                index = indices[cue.id]
                visible_ids.update(
                    item.id
                    for item in cues[
                        max(0, index - _OVERLAP_CUES) : min(len(cues), index + _OVERLAP_CUES + 1)
                    ]
                )
            visible = [cue for cue in cues if cue.id in visible_ids]
            owned = [
                SourceCue(
                    id=cue.id,
                    start_ms=cue.start_ms,
                    end_ms=cue.end_ms,
                    original_text=cue.original_text,
                )
                for cue in repair_batch
            ]
            payload = {
                "mode": "repair_semantic_issues",
                "source_kind": source_kind,
                "target_language": self.target_language,
                "global_context": context["global_brief"],
                "owned_ids": [cue.id for cue in repair_batch],
                "issues": [{"id": cue.id, "issue": issue_by_id[cue.id]} for cue in repair_batch],
                "visible_cues": [asdict(cue) for cue in visible],
            }
            prompt = render_prompt(
                "subtitle_generate",
                source_json=json.dumps(payload, ensure_ascii=False),
            )
            raw = self._call(
                prompt,
                max_tokens=4_000,
                operation="repair",
                batch_id=f"repair-{batch_index:04d}",
                cue_start=repair_batch[0].id,
                cue_end=repair_batch[-1].id,
                profile=profile,
            )
            repaired = parse_generated(parse_json_array(raw, "subtitle repair"), owned, source_kind)
            replacements.update({cue.id: cue for cue in repaired})
        return [replacements.get(cue.id, by_id[cue.id]) for cue in cues]

    def _call(
        self,
        prompt: str,
        *,
        max_tokens: int,
        operation: str,
        batch_id: str,
        cue_start: str | None,
        cue_end: str | None,
        profile: RuntimeObserver,
    ) -> str:
        started = time.perf_counter()
        self._progress(
            f"LLM {operation} {batch_id}: started"
            + (f" ({cue_start}..{cue_end})" if cue_start and cue_end else "")
        )
        try:
            with (
                profile.span(
                    "batch",
                    batch_id,
                    attributes={"cue_start": cue_start, "cue_end": cue_end},
                ),
                profile.span(
                    "provider_call",
                    operation,
                    attributes={
                        "input_chars": len(self.system_prompt) + len(prompt),
                        "output_chars": 0,
                    },
                ) as call,
            ):
                try:
                    raw = self.caller.call(
                        self.system_prompt,
                        prompt,
                        max_tokens=max_tokens,
                    )
                except Exception:
                    profile.availability(
                        self.model_label,
                        available=False,
                        failure_category="provider",
                    )
                    raise
                profile.availability(self.model_label, available=True)
                call.attributes["output_chars"] = len(raw)
                return raw
        except BaseException:
            self._progress(f"LLM {operation} {batch_id}: failed")
            raise
        finally:
            if "raw" in locals():
                self._progress(
                    f"LLM {operation} {batch_id}: completed in {time.perf_counter() - started:.1f}s"
                )

    def _progress(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)


def _batch_cues(cues: Sequence[Any], budget: int) -> list[tuple[int, int]]:
    batches: list[tuple[int, int]] = []
    start = 0
    size = 0
    for index, cue in enumerate(cues):
        cue_size = len(getattr(cue, "original_text", "")) + len(getattr(cue, "translated_text", ""))
        if index > start and size + cue_size > budget:
            batches.append((start, index))
            start = index
            size = 0
        size += cue_size
    if start < len(cues):
        batches.append((start, len(cues)))
    return batches


def _split_text(text: str, budget: int) -> list[str]:
    lines = text.splitlines()
    sections: list[str] = []
    current: list[str] = []
    current_size = 0
    for line in lines:
        if current and current_size + len(line) + 1 > budget:
            sections.append("\n".join(current))
            current = []
            current_size = 0
        current.append(line)
        current_size += len(line) + 1
    if current:
        sections.append("\n".join(current))
    return sections


def _group_strings(items: Sequence[str], budget: int) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    current_size = 0
    for item in items:
        if len(current) >= 2 and current_size + len(item) > budget:
            groups.append(current)
            current = []
            current_size = 0
        current.append(item)
        current_size += len(item)
    if current:
        groups.append(current)
    return groups


def _metadata_context(metadata: VideoMeta) -> dict[str, object]:
    return {
        "title": metadata.title,
        "channel": metadata.channel,
        "url": metadata.url,
        "description": metadata.description,
        "series": metadata.series,
        "chapters": [asdict(chapter) for chapter in metadata.chapters],
    }
