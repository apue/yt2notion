"""Context-aware bilingual subtitle package generation."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from yt2notion.process import parse_subtitle_file
from yt2notion.prompts import load_prompt, render_prompt
from yt2notion.subtitle_pack.models import BilingualCue, SourceCue, SubtitlePackResult
from yt2notion.subtitle_pack.profile import ProfileRecorder

if TYPE_CHECKING:
    from collections.abc import Sequence

    from yt2notion.models.base import VideoMeta
    from yt2notion.models.llm import LLMCaller
    from yt2notion.transcript_artifacts import MediaTranscribeResult

SCHEMA_VERSION = 1
_BATCH_CHAR_BUDGET = 12_000
_GENERATION_BATCH_CHAR_BUDGET = 8_000
_CONTEXT_CHAR_BUDGET = 24_000
_OVERLAP_CUES = 3


class SubtitlePackError(ValueError):
    """Raised when source or model output violates the subtitle contract."""


class SubtitlePackService:
    """Build context, translate immutable cues, validate, and write artifacts."""

    def __init__(
        self,
        caller: LLMCaller,
        *,
        model_label: str,
        target_language: str,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.caller = caller
        self.model_label = model_label
        self.target_language = target_language
        self.progress_callback = progress_callback
        self.system_prompt = (
            "You edit professional subtitles. Treat IDs and timing as immutable. "
            "Return only the requested JSON and never omit or invent an ID."
        )

    def run(self, transcription: MediaTranscribeResult) -> SubtitlePackResult:
        """Generate a browser-consumable bilingual package from local transcription artifacts."""
        ws = transcription.workspace
        profile = ProfileRecorder(ws.dir, inherited_timings=transcription.timings_seconds)
        error: BaseException | None = None
        try:
            self._progress("Subtitle pack: building source cues")
            with profile.stage("build_source_cues"):
                source_kind, cues = _build_source_cues(transcription)
                _validate_source_cues(cues)
                _write_json(ws.dir / "source_cues.json", [asdict(cue) for cue in cues])
            self._progress(f"Subtitle pack: {len(cues)} source cues ({source_kind})")

            source_fingerprint = _fingerprint([asdict(cue) for cue in cues])
            self._progress("Subtitle pack: building bounded global context")
            with profile.stage("build_context"):
                context = self._build_context(
                    transcription.metadata,
                    cues,
                    ws.dir,
                    source_fingerprint,
                    profile,
                )
                context_fingerprint = _fingerprint(context)
                _write_json(
                    ws.dir / "subtitle_context.json",
                    {
                        "schema_version": SCHEMA_VERSION,
                        "source_sha256": source_fingerprint,
                        "context_sha256": context_fingerprint,
                        **context,
                    },
                )

            self._progress("Subtitle pack: correcting and translating cue batches")
            with profile.stage("generate_batches"):
                generated = self._generate_all(
                    cues,
                    source_kind,
                    context,
                    context_fingerprint,
                    ws.dir,
                    profile,
                )

            self._progress("Subtitle pack: running semantic quality checks")
            with profile.stage("semantic_quality"):
                semantic_issues = self._semantic_quality(generated, context, profile)
            if semantic_issues:
                self._progress(f"Subtitle pack: repairing {len(semantic_issues)} semantic issue(s)")
                with profile.stage("repair"):
                    generated = self._repair_issues(
                        generated,
                        semantic_issues,
                        source_kind,
                        context,
                        profile,
                    )
                with profile.stage("semantic_quality_after_repair"):
                    semantic_issues = self._semantic_quality(
                        generated,
                        context,
                        profile,
                        operation="semantic_quality_after_repair",
                    )

            self._progress("Subtitle pack: validating and writing artifacts")
            with profile.stage("validate_and_write"):
                report = _validate_bilingual(cues, generated, semantic_issues)
                if source_kind != "manual_subtitle":
                    _write_json(
                        ws.dir / "reviewed_cues.json",
                        [{"id": cue.id, "source_text": cue.source_text} for cue in generated],
                    )
                package = {
                    "schema_version": SCHEMA_VERSION,
                    "video": {
                        "id": transcription.metadata.video_id,
                        "title": transcription.metadata.title,
                        "channel": transcription.metadata.channel,
                        "url": transcription.metadata.url,
                    },
                    "source_language": transcription.metadata.language or "und",
                    "target_language": self.target_language,
                    "source_kind": source_kind,
                    "context_fingerprint": context_fingerprint,
                    "quality": {
                        "passed": report["passed"],
                        "semantic_issue_count": len(semantic_issues),
                    },
                    "cues": [asdict(cue) for cue in generated],
                }
                package_path = ws.dir / "bilingual_subtitles.json"
                srt_path = ws.dir / "bilingual_subtitles.srt"
                report_path = ws.dir / "subtitle_quality_report.json"
                _write_json(package_path, package)
                srt_path.write_text(_render_srt(generated), encoding="utf-8")
                _write_json(report_path, report)
            self._progress(f"Subtitle pack: complete ({package_path})")
        except BaseException as exc:
            error = exc
            raise
        finally:
            profile_path = profile.finish(error=error)

        return SubtitlePackResult(
            workspace_dir=ws.dir,
            package_path=package_path,
            srt_path=srt_path,
            context_path=ws.dir / "subtitle_context.json",
            quality_report_path=report_path,
            profile_path=profile_path,
            cue_count=len(generated),
            source_kind=source_kind,
            quality_passed=bool(report["passed"]),
        )

    def _build_context(
        self,
        metadata: VideoMeta,
        cues: Sequence[SourceCue],
        workspace_dir: Path,
        source_fingerprint: str,
        profile: ProfileRecorder,
    ) -> dict[str, object]:
        checkpoint = workspace_dir / "subtitle_checkpoints" / "context.json"
        source_evidence = _metadata_context(metadata)
        identity = {
            "schema_version": SCHEMA_VERSION,
            "source_sha256": source_fingerprint,
            "metadata_sha256": _fingerprint(source_evidence),
            "model_label": self.model_label,
            "prompt_sha256": _prompt_fingerprint("subtitle_context"),
        }
        cached = _load_checkpoint(checkpoint, identity)
        if isinstance(cached, dict):
            self._progress("Subtitle context: reused checkpoint")
            profile.record_call(
                operation="context",
                batch_id="context",
                cue_start=cues[0].id,
                cue_end=cues[-1].id,
                input_chars=0,
                output_chars=0,
                elapsed_seconds=0,
                reused_checkpoint=True,
                status="completed",
            )
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
            section_briefs.append(_parse_json_object(raw, "subtitle context"))

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
                next_level.append(_parse_json_object(raw, "reduced subtitle context"))
            reduction_level = next_level

        context = {
            "source_evidence": source_evidence,
            "global_brief": reduction_level[0],
            "section_contexts": section_briefs,
        }

        _save_checkpoint(checkpoint, identity, context)
        return context

    def _generate_all(
        self,
        cues: Sequence[SourceCue],
        source_kind: str,
        context: dict[str, object],
        context_fingerprint: str,
        workspace_dir: Path,
        profile: ProfileRecorder,
    ) -> list[BilingualCue]:
        batches = _batch_cues(cues, _GENERATION_BATCH_CHAR_BUDGET)
        output: list[BilingualCue] = []
        for index, (start, end) in enumerate(batches, start=1):
            owned = cues[start:end]
            visible = cues[max(0, start - _OVERLAP_CUES) : min(len(cues), end + _OVERLAP_CUES)]
            identity = {
                "schema_version": SCHEMA_VERSION,
                "context_sha256": context_fingerprint,
                "source_sha256": _fingerprint([asdict(cue) for cue in owned]),
                "model_label": self.model_label,
                "prompt_sha256": _prompt_fingerprint("subtitle_generate"),
                "source_kind": source_kind,
                "target_language": self.target_language,
                "ordered_ids": [cue.id for cue in owned],
                "generation_batch_char_budget": _GENERATION_BATCH_CHAR_BUDGET,
                "overlap_cues": _OVERLAP_CUES,
            }
            batch_id = f"batch-{index:04d}"
            checkpoint = workspace_dir / "subtitle_checkpoints" / f"{batch_id}.json"
            cached = _load_checkpoint(checkpoint, identity)
            reused_checkpoint = isinstance(cached, list)
            if isinstance(cached, list):
                records = cached
                self._progress(
                    f"Subtitle generation {batch_id}: reused checkpoint "
                    f"({owned[0].id}..{owned[-1].id})"
                )
                profile.record_call(
                    operation="generate",
                    batch_id=batch_id,
                    cue_start=owned[0].id,
                    cue_end=owned[-1].id,
                    input_chars=0,
                    output_chars=0,
                    elapsed_seconds=0,
                    reused_checkpoint=True,
                    status="completed",
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
                records = _parse_json_array(raw, "subtitle generation")
            parsed = _parse_generated(records, owned, source_kind)
            if not reused_checkpoint:
                _save_checkpoint(checkpoint, identity, records)
            output.extend(parsed)
        return output

    def _semantic_quality(
        self,
        cues: Sequence[BilingualCue],
        context: dict[str, object],
        profile: ProfileRecorder,
        *,
        operation: str = "semantic_quality",
    ) -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []
        for index, (start, end) in enumerate(_batch_cues(cues, _BATCH_CHAR_BUDGET), start=1):
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
            records = _parse_json_array(raw, "semantic quality")
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

    def _repair_issues(
        self,
        cues: Sequence[BilingualCue],
        issues: Sequence[dict[str, str]],
        source_kind: str,
        context: dict[str, object],
        profile: ProfileRecorder,
    ) -> list[BilingualCue]:
        by_id = {cue.id: cue for cue in cues}
        issue_by_id = {issue["id"]: issue["issue"] for issue in issues}
        affected = [cue for cue in cues if cue.id in issue_by_id]
        replacements: dict[str, BilingualCue] = {}
        indices = {cue.id: index for index, cue in enumerate(cues)}
        for batch_index, (start, end) in enumerate(
            _batch_cues(affected, _BATCH_CHAR_BUDGET), start=1
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
            repaired = _parse_generated(
                _parse_json_array(raw, "subtitle repair"), owned, source_kind
            )
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
        profile: ProfileRecorder,
    ) -> str:
        started = time.perf_counter()
        status = "completed"
        raw = ""
        self._progress(
            f"LLM {operation} {batch_id}: started"
            + (f" ({cue_start}..{cue_end})" if cue_start and cue_end else "")
        )
        try:
            raw = self.caller.call(self.system_prompt, prompt, max_tokens=max_tokens)
            return raw
        except BaseException:
            status = "failed"
            raise
        finally:
            elapsed_seconds = time.perf_counter() - started
            profile.record_call(
                operation=operation,
                batch_id=batch_id,
                cue_start=cue_start,
                cue_end=cue_end,
                input_chars=len(self.system_prompt) + len(prompt),
                output_chars=len(raw),
                elapsed_seconds=elapsed_seconds,
                reused_checkpoint=False,
                status=status,
            )
            self._progress(f"LLM {operation} {batch_id}: {status} in {elapsed_seconds:.1f}s")

    def _progress(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)


def _build_source_cues(transcription: MediaTranscribeResult) -> tuple[str, list[SourceCue]]:
    subtitle_path = transcription.workspace.subtitle_path
    source_kind = transcription.workspace.load_subtitle_source()
    if subtitle_path is not None:
        entries = parse_subtitle_file(subtitle_path)
        cues = [
            SourceCue(
                id=f"cue-{index:06d}",
                start_ms=round(entry.start_seconds * 1000),
                end_ms=round(entry.end_seconds * 1000),
                original_text=entry.text,
            )
            for index, entry in enumerate(entries, start=1)
        ]
        return source_kind or "subtitle", cues

    chunk_cues = _asr_cues_from_chunks(transcription)
    if chunk_cues:
        return "asr", chunk_cues

    transcripts = transcription.workspace.load_transcripts() or []
    cues = [
        SourceCue(
            id=f"cue-{index:06d}",
            start_ms=round(float(segment.get("start_seconds", 0)) * 1000),
            end_ms=round(float(segment.get("end_seconds", 0)) * 1000),
            original_text=str(segment.get("text", "")).strip(),
        )
        for index, segment in enumerate(transcripts, start=1)
        if str(segment.get("text", "")).strip()
    ]
    sources = {str(item.get("source", "")) for item in transcripts}
    return ("asr" if "asr" in sources else "transcript"), cues


def _asr_cues_from_chunks(transcription: MediaTranscribeResult) -> list[SourceCue]:
    plan = transcription.workspace.load_transcribe_plan()
    if not isinstance(plan, list) or not plan:
        return []
    entries: list[tuple[float, float, str]] = []
    for chunk in plan:
        if not isinstance(chunk, dict) or "chunk_id" not in chunk:
            return []
        payload = transcription.workspace.load_transcribe_chunk_result(str(chunk["chunk_id"]))
        if not isinstance(payload, list):
            return []
        chunk_start = float(chunk.get("start_seconds", 0))
        chunk_duration = float(chunk.get("end_seconds", 0)) - chunk_start
        payload_end = max(
            (float(item.get("end_seconds", 0)) for item in payload if isinstance(item, dict)),
            default=0,
        )
        offset = (
            chunk_start if "segment_index" in chunk and payload_end <= chunk_duration + 0.001 else 0
        )
        for item in payload:
            if not isinstance(item, dict):
                return []
            text = str(item.get("text", "")).strip()
            if text:
                entries.append(
                    (
                        float(item.get("start_seconds", 0)) + offset,
                        float(item.get("end_seconds", 0)) + offset,
                        text,
                    )
                )
    entries.sort(key=lambda item: (item[0], item[1]))
    return [
        SourceCue(
            id=f"cue-{index:06d}",
            start_ms=round(start * 1000),
            end_ms=round(end * 1000),
            original_text=text,
        )
        for index, (start, end, text) in enumerate(entries, start=1)
    ]


def _validate_source_cues(cues: Sequence[SourceCue]) -> None:
    if not cues:
        raise SubtitlePackError("no timed source cues were produced")
    previous_start = -1
    for cue in cues:
        if cue.start_ms < 0 or cue.end_ms <= cue.start_ms:
            raise SubtitlePackError(f"invalid timing for {cue.id}")
        if cue.start_ms < previous_start:
            raise SubtitlePackError("source cues are not ordered by start time")
        previous_start = cue.start_ms


def _parse_generated(
    records: object, owned: Sequence[SourceCue], source_kind: str
) -> list[BilingualCue]:
    if not isinstance(records, list):
        raise SubtitlePackError("generation response must be a JSON array")
    expected_ids = [cue.id for cue in owned]
    actual_ids = [record.get("id") for record in records if isinstance(record, dict)]
    if actual_ids != expected_ids or len(records) != len(owned):
        raise SubtitlePackError(
            "generation IDs must exactly match source order: "
            f"expected {expected_ids}, got {actual_ids}"
        )
    result: list[BilingualCue] = []
    for cue, record in zip(owned, records, strict=True):
        source_text = record.get("source_text")
        translated_text = record.get("translated_text")
        if not isinstance(source_text, str) or not source_text.strip():
            raise SubtitlePackError(f"empty source_text for {cue.id}")
        if not isinstance(translated_text, str) or not translated_text.strip():
            raise SubtitlePackError(f"empty translated_text for {cue.id}")
        if source_kind == "manual_subtitle" and source_text.strip() != cue.original_text:
            raise SubtitlePackError(f"manual subtitle source text was changed for {cue.id}")
        result.append(
            BilingualCue(
                id=cue.id,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
                original_text=cue.original_text,
                source_text=source_text.strip(),
                translated_text=translated_text.strip(),
            )
        )
    return result


def _validate_bilingual(
    source: Sequence[SourceCue],
    generated: Sequence[BilingualCue],
    semantic_issues: list[dict[str, str]],
) -> dict[str, object]:
    expected = [cue.id for cue in source]
    actual = [cue.id for cue in generated]
    if expected != actual:
        raise SubtitlePackError("final cue coverage or order differs from source")
    for source_cue, generated_cue in zip(source, generated, strict=True):
        if (source_cue.start_ms, source_cue.end_ms) != (
            generated_cue.start_ms,
            generated_cue.end_ms,
        ):
            raise SubtitlePackError(f"timing changed for {source_cue.id}")
    return {
        "schema_version": SCHEMA_VERSION,
        "passed": not semantic_issues,
        "deterministic_checks": {
            "cue_count": len(source),
            "ordered_id_coverage": True,
            "timeline_unchanged": True,
            "nonempty_source_and_translation": True,
        },
        "semantic_issues": semantic_issues,
    }


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


def _parse_json_object(raw: str, label: str) -> dict[str, object]:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SubtitlePackError(f"{label} response is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise SubtitlePackError(f"{label} response must be a JSON object")
    return payload


def _parse_json_array(raw: str, label: str) -> list[object]:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SubtitlePackError(f"{label} response is not valid JSON") from exc
    if not isinstance(payload, list):
        raise SubtitlePackError(f"{label} response must be a JSON array")
    return payload


def _prompt_fingerprint(name: str) -> str:
    return hashlib.sha256(load_prompt(name).encode()).hexdigest()


def _fingerprint(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _load_checkpoint(path: Path, identity: dict[str, object]) -> object | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("identity") != identity:
        return None
    return payload.get("result")


def _save_checkpoint(path: Path, identity: dict[str, object], result: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, {"identity": identity, "result": result})


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _render_srt(cues: Sequence[BilingualCue]) -> str:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n{_srt_timestamp(cue.start_ms)} --> {_srt_timestamp(cue.end_ms)}\n"
            f"{cue.source_text}\n{cue.translated_text}"
        )
    return "\n\n".join(blocks) + "\n"


def _srt_timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"
