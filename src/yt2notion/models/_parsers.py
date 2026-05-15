"""Shared parsers for LLM output → data models."""

from __future__ import annotations

import json
import re
import textwrap

from yt2notion.models.base import NoteDocument, NoteMetadata


class ParseError(Exception):
    """Raised when LLM output cannot be parsed."""


def _extract_json_payload(text: str) -> str:
    """Extract a JSON payload from raw or fenced LLM output."""
    stripped = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    return stripped


def _extract_tagged_block(text: str, tag: str) -> str | None:
    """Extract a tagged block like <tag>...</tag> from raw text."""
    match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, re.DOTALL)
    if not match:
        return None
    block = textwrap.dedent(match.group(1))
    return "\n".join(line.strip() for line in block.splitlines()).strip()


def _load_json_object(text: str, *, context: str) -> dict:
    """Load a JSON object from text, raising ParseError on failure."""
    json_text = _extract_json_payload(text)
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise ParseError(f"Failed to parse {context} JSON: {e}\nRaw text: {text[:200]}") from e
    if not isinstance(data, dict):
        raise ParseError(f"Expected {context} JSON object, got {type(data).__name__}")
    return data


def _require_string(data: dict, key: str, *, context: str) -> str:
    """Return a required string field or raise ParseError."""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ParseError(f"Missing or invalid required field '{key}' in {context} JSON")
    return value


def _require_string_list(data: dict, key: str, *, context: str) -> list[str]:
    """Return a required list[str] field or raise ParseError."""
    value = data.get(key)
    if not isinstance(value, list) or not value:
        raise ParseError(f"Missing or invalid required field '{key}' in {context} JSON")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ParseError(f"Field '{key}' in {context} JSON must contain only strings")
    return value


def _parse_note_markdown(data: dict) -> str:
    """Parse note markdown from either a flat string or paragraph array."""
    markdown = data.get("markdown")
    if isinstance(markdown, str) and markdown.strip():
        return markdown

    paragraphs = data.get("markdown_paragraphs")
    if not isinstance(paragraphs, list) or not paragraphs:
        raise ParseError(
            "Missing or invalid required field 'markdown' or 'markdown_paragraphs' "
            "in note document JSON"
        )
    if any(not isinstance(item, str) or not item.strip() for item in paragraphs):
        raise ParseError(
            "Field 'markdown_paragraphs' in note document JSON must contain only strings"
        )
    return "\n\n".join(item.strip() for item in paragraphs)


def extract_json_array(raw: str) -> list:
    """Extract a JSON array from LLM output, stripping markdown fences."""
    text = raw.strip()
    if "```" in text:
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if m:
            text = m.group(0)
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def parse_note_document_json(text: str, *, expected_variant: str) -> NoteDocument:
    """Parse a strict note document JSON payload."""
    tagged_json = _extract_tagged_block(text, "note_json")
    tagged_markdown = _extract_tagged_block(text, "note_markdown")

    if tagged_json is not None:
        data = _load_json_object(tagged_json, context="note document")
    else:
        data = _load_json_object(text, context="note document")

    title = _require_string(data, "title", context="note document")
    markdown = tagged_markdown if tagged_markdown else _parse_note_markdown(data)
    if not markdown.strip():
        raise ParseError("Missing or invalid note markdown body")
    tags = _require_string_list(data, "tags", context="note document")
    variant = _require_string(data, "variant", context="note document")
    if variant != expected_variant:
        raise ParseError(
            f"Note document variant mismatch: expected {expected_variant!r}, got {variant!r}"
        )
    return NoteDocument(title=title, markdown=markdown, tags=tags, variant=variant)


def parse_note_metadata_json(text: str) -> NoteMetadata:
    """Parse a strict note metadata JSON payload."""
    data = _load_json_object(text, context="note metadata")
    source_title = _require_string(data, "source_title", context="note metadata")
    stable_tags = _require_string_list(data, "stable_tags", context="note metadata")
    guide_tags = _require_string_list(data, "guide_tags", context="note metadata")
    longform_tags = _require_string_list(data, "longform_tags", context="note metadata")
    source_summary = _require_string(data, "source_summary", context="note metadata")
    source_topics = _require_string_list(data, "source_topics", context="note metadata")
    return NoteMetadata(
        source_title=source_title,
        stable_tags=stable_tags,
        guide_tags=guide_tags,
        longform_tags=longform_tags,
        source_summary=source_summary,
        source_topics=source_topics,
    )
