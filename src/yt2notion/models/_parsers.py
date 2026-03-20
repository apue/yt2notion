"""Shared parsers for LLM output → data models."""

from __future__ import annotations

import json
import re

from yt2notion.models.base import ChineseContent, Section, Summary


class ParseError(Exception):
    """Raised when LLM output cannot be parsed."""


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

    # Extract tags
    tags_match = re.search(r"##\s*标签\s*\n(.*?)(?=##|\Z)", text, re.DOTALL)
    if tags_match:
        tags_text = tags_match.group(1).strip()
        tags = [t.strip() for t in tags_text.split(",") if t.strip()]

    return ChineseContent(
        overview=overview,
        key_points=key_points,
        tags=tags,
        raw_markdown=text,
    )
