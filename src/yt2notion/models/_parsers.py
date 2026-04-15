"""Shared parsers for LLM output → data models."""

from __future__ import annotations

import json
import re
import textwrap
from typing import TYPE_CHECKING

from yt2notion.models.base import (
    FUN_FACTS_CATEGORIES,
    ChineseContent,
    NoteDocument,
    NoteMetadata,
    ReviewSummaryResult,
    Section,
    Summary,
)

if TYPE_CHECKING:
    from yt2notion.models.base import ChunkSummary


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


def parse_summary_json(text: str) -> Summary:
    """Parse LLM output into a Summary object.

    Handles raw JSON or JSON wrapped in ```json fences.
    """
    # Try to extract JSON from markdown code fences
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    json_str = fence_match.group(1) if fence_match else text

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ParseError(f"Failed to parse summary JSON: {e}\nRaw text: {text[:200]}") from e

    sections = [
        Section(
            title=s.get("title", ""),
            timestamp=s.get("timestamp", "0:00"),
            timestamp_seconds=int(s.get("timestamp_seconds", 0)),
            summary=s.get("summary", ""),
        )
        for s in data.get("sections", [])
    ]

    return Summary(
        sections=sections,
        overall_summary=data.get("overall_summary", ""),
        suggested_tags=data.get("suggested_tags", []),
    )


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


def parse_review_summary_json(text: str) -> ReviewSummaryResult:
    """Parse combined review + summary JSON output."""
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    json_str = fence_match.group(1) if fence_match else text

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ParseError(
            f"Failed to parse review+summary JSON: {e}\nRaw text: {text[:200]}"
        ) from e

    reviewed_transcript = data.get("reviewed_transcript", "")
    if not isinstance(reviewed_transcript, str):
        reviewed_transcript = ""

    return ReviewSummaryResult(
        reviewed_transcript=reviewed_transcript,
        summary=parse_summary_json(json.dumps(data, ensure_ascii=False)),
    )


def _fix_google_search_urls(text: str) -> str:
    """URL-encode query parameters in Google search links.

    LLMs often produce un-encoded URLs like:
        [《Project Hail Mary》](https://www.google.com/search?q=Project Hail Mary)
    This encodes the query so the link actually works.
    """
    from urllib.parse import quote

    def _encode_match(m: re.Match) -> str:
        query = m.group(1)
        return f"](https://www.google.com/search?q={quote(query)})"

    return re.sub(
        r"\]\(https://www\.google\.com/search\?q=([^)]+)\)",
        _encode_match,
        text,
    )


# Build reverse lookup: emoji label → slug key (also match without emoji)
_FUN_FACTS_LABEL_TO_KEY: dict[str, str] = {}
for _key, _label in FUN_FACTS_CATEGORIES.items():
    _FUN_FACTS_LABEL_TO_KEY[_label] = _key
    # Strip leading emoji for fallback matching
    _stripped = _label.lstrip("🔥🤓📚 ")
    if _stripped != _label:
        _FUN_FACTS_LABEL_TO_KEY[_stripped] = _key


def _parse_fun_facts(text: str) -> dict[str, list[str]]:
    """Extract fun_facts section from markdown.

    Looks for ## 有趣发现 with ### sub-headings for each category.
    Returns dict keyed by category slug with list of bullet items.
    """
    section_match = re.search(r"##\s*有趣发现\s*\n(.*?)(?=\n##(?!#)|\Z)", text, re.DOTALL)
    if not section_match:
        return {}

    section_text = section_match.group(1)
    result: dict[str, list[str]] = {}

    # Split by ### headings
    sub_sections = re.split(r"###\s*", section_text)
    for sub in sub_sections:
        if not sub.strip():
            continue
        # First line is heading, rest is content
        lines = sub.strip().split("\n", 1)
        heading = lines[0].strip()
        body = lines[1] if len(lines) > 1 else ""

        # Match heading to category
        category_key = None
        for label, key in _FUN_FACTS_LABEL_TO_KEY.items():
            if label in heading:
                category_key = key
                break
        if not category_key:
            continue

        # Extract bullet items
        items: list[str] = []
        for item_match in re.finditer(r"-\s+(.*?)(?=\n-|\Z)", body, re.DOTALL):
            item_text = item_match.group(1).strip()
            if item_text:
                # Fix Google search URLs
                item_text = _fix_google_search_urls(item_text)
                items.append(item_text)

        if items:
            result[category_key] = items

    return result


def parse_chinese_markdown(text: str) -> ChineseContent:
    """Parse Chinese markdown output into ChineseContent.

    Expected format:
    ## 概要
    ...overview...
    ## 关键节点
    - [0:00] **title**: summary
    ## 标签
    tag1, tag2
    """
    overview = ""
    key_points: list[dict] = []
    tags: list[str] = []

    # Extract overview
    overview_match = re.search(r"##\s*概要\s*\n(.*?)(?=##|\Z)", text, re.DOTALL)
    if overview_match:
        overview = overview_match.group(1).strip()

    # Extract key points
    points_match = re.search(r"##\s*关键节点\s*\n(.*?)(?=##|\Z)", text, re.DOTALL)
    if points_match:
        point_pattern = re.compile(
            r"-\s*\[(\d+:\d{2})\]\s*\*\*(.*?)\*\*[：:]\s*(.*?)(?=\n-|\n##|\Z)",
            re.DOTALL,
        )
        for m in point_pattern.finditer(points_match.group(1)):
            key_points.append(
                {
                    "timestamp": m.group(1),
                    "title": m.group(2).strip(),
                    "summary": m.group(3).strip(),
                }
            )

    tags_match = re.search(r"##\s*标签\s*\n(.*?)(?=\n##|\n---|\Z)", text, re.DOTALL)
    if tags_match:
        tags_text = tags_match.group(1).strip()
        tags = [t.strip() for t in tags_text.split(",") if t.strip()]

    fun_facts = _parse_fun_facts(text)

    return ChineseContent(
        overview=overview,
        key_points=key_points,
        tags=tags,
        raw_markdown=text,
        fun_facts=fun_facts,
    )


def parse_chunk_summary_json(text: str) -> ChunkSummary:
    """Parse map-phase LLM output into a ChunkSummary."""
    from yt2notion.models.base import ChunkSummary

    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    json_str = fence_match.group(1) if fence_match else text

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ParseError(f"Failed to parse chunk summary JSON: {e}\nRaw text: {text[:200]}") from e

    return ChunkSummary(
        segment_title=data.get("segment_title", ""),
        timestamp=data.get("timestamp", "0:00"),
        timestamp_seconds=int(data.get("timestamp_seconds", 0)),
        summary=data.get("summary", ""),
        key_points=data.get("key_points", []),
        key_terms=data.get("key_terms", []),
    )


def parse_synthesized_markdown(text: str) -> ChineseContent:
    """Parse synthesize-phase output (includes mindmap section)."""
    content = parse_chinese_markdown(text)

    # Additionally extract mindmap
    mindmap_match = re.search(r"```markmap\s*\n(.*?)```", text, re.DOTALL)
    if mindmap_match:
        content.mindmap = mindmap_match.group(1).strip()

    return content
