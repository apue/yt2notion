"""Entity extraction from reviewed transcripts using LLM."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from yt2notion.models.base import Entity, EntityResult
from yt2notion.models.llm import LLMCaller  # noqa: TC001
from yt2notion.prompts import load_prompt


def _strip_code_block(text: str) -> str:
    """Remove markdown code block wrapper if present."""
    text = text.strip()
    match = re.match(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _parse_entity(d: dict) -> Entity:
    """Parse a single entity dict into an Entity dataclass."""
    return Entity(
        name=d["name"],
        type=d["type"],
        attributes=d.get("attributes", {}),
        linkable=d.get("linkable", True),
    )


def parse_segment_entities(raw: str) -> tuple[list[Entity], list[dict]]:
    """Parse per-segment extraction output.

    Returns (entities, relations).
    """
    text = _strip_code_block(raw)
    data = json.loads(text)
    entities = [_parse_entity(e) for e in data.get("entities", [])]
    relations = data.get("relations", [])
    return entities, relations


def parse_entity_result(raw: str) -> EntityResult:
    """Parse final reduce-phase output into EntityResult."""
    text = _strip_code_block(raw)
    data = json.loads(text)
    entities = [_parse_entity(e) for e in data.get("entities", [])]
    return EntityResult(
        domain=data.get("domain", ""),
        is_entity_centric=data.get("is_entity_centric", False),
        entity_types=data.get("entity_types", []),
        entities=entities,
        relations=data.get("relations", []),
    )


SINGLE_PASS_THRESHOLD = 30_000  # tokens (rough estimate: 1 token ≈ 4 chars)
MAP_REDUCE_BATCH_CHAR_LIMIT = 24_000
MAP_REDUCE_BATCH_SEGMENT_LIMIT = 60


def _estimate_tokens(segments: list[dict]) -> int:
    """Rough token estimate: ~4 chars per token."""
    total_chars = sum(len(seg.get("text", "")) for seg in segments)
    return total_chars // 4


def _concat_segments(segments: list[dict]) -> str:
    """Join segment texts with title headers."""
    parts: list[str] = []
    for seg in segments:
        title = seg.get("title", "")
        text = seg.get("text", "")
        if title:
            parts.append(f"[{title}]\n{text}")
        else:
            parts.append(text)
    return "\n\n".join(parts)


def _batch_segments_for_map_reduce(segments: list[dict]) -> list[list[dict]]:
    """Batch segments to keep map-phase calls bounded for long content."""
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_chars = 0

    for segment in segments:
        segment_chars = len(segment.get("text", ""))
        exceeds_char_limit = current_chars + segment_chars > MAP_REDUCE_BATCH_CHAR_LIMIT
        exceeds_segment_limit = len(current_batch) >= MAP_REDUCE_BATCH_SEGMENT_LIMIT

        if current_batch and (exceeds_char_limit or exceeds_segment_limit):
            batches.append(current_batch)
            current_batch = []
            current_chars = 0

        current_batch.append(segment)
        current_chars += segment_chars

    if current_batch:
        batches.append(current_batch)

    return batches


def extract_entities(
    segments: list[dict],
    caller: LLMCaller,
    *,
    max_workers: int = 1,
) -> EntityResult:
    """Extract entities from reviewed segments.

    Uses single-pass for short content, map-reduce for long content.
    """
    if not segments:
        return EntityResult(
            domain="",
            is_entity_centric=False,
            entity_types=[],
            entities=[],
            relations=[],
        )

    total_tokens = _estimate_tokens(segments)

    if total_tokens < SINGLE_PASS_THRESHOLD:
        return _extract_single_pass(segments, caller)
    else:
        return _extract_map_reduce(segments, caller, max_workers=max_workers)


def _extract_single_pass(segments: list[dict], caller: LLMCaller) -> EntityResult:
    """Single Haiku call with all segments concatenated."""
    system_prompt = load_prompt("reduce_entities")
    user_prompt = _concat_segments(segments)
    raw = caller.call(system_prompt, user_prompt, max_tokens=4000)
    return parse_entity_result(raw)


def _extract_map_reduce(
    segments: list[dict],
    caller: LLMCaller,
    *,
    max_workers: int = 1,
) -> EntityResult:
    """Map phase: one call per segment batch. Reduce phase: one merge call."""
    map_prompt = load_prompt("extract_entities")
    batches = _batch_segments_for_map_reduce(segments)

    def _extract_batch(i: int, batch: list[dict]) -> dict | None:
        text = _concat_segments(batch)
        if not text.strip():
            return None
        raw = caller.call(map_prompt, text, max_tokens=4000)
        try:
            entities, relations = parse_segment_entities(raw)
            return {
                "segment_id": i,
                "entities": [
                    {
                        "name": e.name,
                        "type": e.type,
                        "attributes": e.attributes,
                        "linkable": e.linkable,
                    }
                    for e in entities
                ],
                "relations": relations,
            }
        except (json.JSONDecodeError, KeyError):
            return None

    all_entities: list[dict] = []
    worker_count = max(1, min(max_workers, len(batches)))

    if worker_count == 1:
        for i, batch in enumerate(batches):
            extracted = _extract_batch(i, batch)
            if extracted:
                all_entities.append(extracted)
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_index = {
                executor.submit(_extract_batch, i, batch): i for i, batch in enumerate(batches)
            }
            for future in as_completed(future_to_index):
                extracted = future.result()
                if extracted:
                    all_entities.append(extracted)

    all_entities.sort(key=lambda item: item["segment_id"])

    if not all_entities:
        return EntityResult(
            domain="",
            is_entity_centric=False,
            entity_types=[],
            entities=[],
            relations=[],
        )

    # Reduce phase
    reduce_prompt = load_prompt("reduce_entities")
    user_prompt = json.dumps(all_entities, ensure_ascii=False, indent=2)
    raw = caller.call(reduce_prompt, user_prompt, max_tokens=4000)
    return parse_entity_result(raw)
