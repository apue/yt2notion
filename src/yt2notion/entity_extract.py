"""Entity extraction from reviewed transcripts using LLM."""

from __future__ import annotations

import json
import re

from yt2notion.models.base import Entity, EntityResult


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
