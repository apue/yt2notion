"""Notion storage backend. Creates pages with rich content."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yt2notion.models.base import ChineseContent, VideoMeta

try:
    from notion_client import Client as _NotionClient
except ImportError:
    _NotionClient = None  # type: ignore[assignment,misc]


class NotionStorageError(Exception):
    """Raised when Notion API operations fail."""


class NotionStorage:
    """Storage backend that creates Notion pages."""

    def __init__(
        self,
        token: str,
        database_id: str = "",
        parent_page_id: str = "",
        directory_rules: list[dict] | None = None,
        credit_format: str = "来源：{channel} 「{title}」\n链接：{url}",
    ) -> None:
        if _NotionClient is None:
            raise NotionStorageError("notion-client not installed. Run: uv sync --extra notion")
        if not database_id and not parent_page_id:
            raise NotionStorageError("Either database_id or parent_page_id is required")
        self.client = _NotionClient(auth=token)
        self.database_id = database_id
        self.parent_page_id = parent_page_id
        self.directory_rules = directory_rules or []
        self.credit_format = credit_format

    def save(
        self,
        content: ChineseContent,
        metadata: VideoMeta,
        *,
        transcript_segments: list[dict] | None = None,
    ) -> str:
        """Create a Notion page and return its URL.

        If transcript_segments is provided, also creates a child page
        with the full transcript organized by segments.
        """
        blocks = self._build_blocks(content, metadata)

        try:
            if self.database_id:
                properties = self._build_page_properties(content, metadata)
                page = self.client.pages.create(
                    parent={"database_id": self.database_id},
                    properties=properties,
                    children=blocks[:100],
                )
                self._append_blocks(page["id"], blocks[100:])
            else:
                title = (
                    content.overview.split("\n")[0][:100] if content.overview else metadata.title
                )
                page = self._create_child_page(self.parent_page_id, title, blocks)

            page_url = page.get("url", "")

            # Create transcript sub-page if segments provided
            if transcript_segments:
                self._create_transcript_page(page["id"], metadata, transcript_segments)

            return page_url
        except NotionStorageError:
            raise
        except Exception as e:
            raise NotionStorageError(f"Failed to create Notion page: {e}") from e

    def _build_page_properties(self, content: ChineseContent, metadata: VideoMeta) -> dict:
        """Build Notion page properties."""
        # Use overview first line as title, fallback to video title
        title_text = content.overview.split("\n")[0][:100] if content.overview else metadata.title

        properties: dict = {
            "title": {"title": [{"text": {"content": title_text}}]},
        }

        # Tags as multi-select
        if content.tags:
            properties["Tags"] = {
                "multi_select": [{"name": tag} for tag in content.tags],
            }

        # Source URL
        properties["URL"] = {"url": metadata.url}

        return properties

    def _build_blocks(self, content: ChineseContent, metadata: VideoMeta) -> list[dict]:
        """Build Notion block children."""
        blocks: list[dict] = []

        # Credit callout
        blocks.append(self._make_credit_block(metadata))

        # Overview heading + paragraph
        blocks.append({"heading_2": {"rich_text": [{"text": {"content": "概要"}}]}})
        for chunk in _split_text(content.overview, 2000):
            blocks.append({"paragraph": {"rich_text": [{"text": {"content": chunk}}]}})

        # Key points heading
        blocks.append({"heading_2": {"rich_text": [{"text": {"content": "关键节点"}}]}})

        for point in content.key_points:
            ts = point.get("timestamp", "0:00")
            title = point.get("title", "")
            summary = point.get("summary", "")

            # Convert timestamp to YouTube link
            ts_link = f"https://youtu.be/{metadata.video_id}?t={_timestamp_to_seconds(ts)}"

            rich_text = [
                {
                    "text": {"content": f"[{ts}] ", "link": {"url": ts_link}},
                    "annotations": {"bold": True, "color": "blue"},
                },
                {"text": {"content": f"{title}"}, "annotations": {"bold": True}},
                {"text": {"content": f"：{summary}"}},
            ]
            blocks.append({"bulleted_list_item": {"rich_text": rich_text}})

        # Fun facts section
        if content.fun_facts:
            from yt2notion.models.base import FUN_FACTS_CATEGORIES

            blocks.append({"heading_2": {"rich_text": [{"text": {"content": "有趣发现"}}]}})

            for cat_key, cat_label in FUN_FACTS_CATEGORIES.items():
                items = content.fun_facts.get(cat_key, [])
                if not items:
                    continue
                blocks.append({"heading_3": {"rich_text": [{"text": {"content": cat_label}}]}})
                for item in items:
                    rich_text = _markdown_links_to_rich_text(item)
                    blocks.append({"bulleted_list_item": {"rich_text": rich_text}})

        # Mindmap section (long content only)
        if content.mindmap:
            blocks.append({"heading_2": {"rich_text": [{"text": {"content": "思维导图"}}]}})
            blocks.append(
                {
                    "code": {
                        "rich_text": [{"text": {"content": content.mindmap}}],
                        "language": "markdown",
                    }
                }
            )

        # Tags section
        if content.tags:
            blocks.append({"heading_2": {"rich_text": [{"text": {"content": "标签"}}]}})
            tags_text = ", ".join(content.tags)
            blocks.append({"paragraph": {"rich_text": [{"text": {"content": tags_text}}]}})

        return blocks

    def _make_credit_block(self, metadata: VideoMeta) -> dict:
        """Create a callout block with source credit."""
        credit_text = self.credit_format.format(
            channel=metadata.channel,
            title=metadata.title,
            url=metadata.url,
        )
        return {
            "callout": {
                "icon": {"emoji": "📺"},
                "rich_text": [{"text": {"content": credit_text}}],
            }
        }

    def _create_transcript_page(
        self,
        parent_page_id: str,
        metadata: VideoMeta,
        transcript_segments: list[dict],
    ) -> None:
        """Create a child page with the full transcript."""
        blocks: list[dict] = []

        # Credit callout
        blocks.append(self._make_credit_block(metadata))

        for seg in transcript_segments:
            title = seg.get("title", "")
            start = seg.get("start_seconds", 0)
            ts_display = f"{start // 3600}:{(start % 3600) // 60:02d}:{start % 60:02d}"
            ts_link = f"https://youtu.be/{metadata.video_id}?t={start}"

            # Segment heading with timestamp link
            blocks.append(
                {
                    "heading_3": {
                        "rich_text": [
                            {
                                "text": {"content": f"[{ts_display}] ", "link": {"url": ts_link}},
                                "annotations": {"bold": True, "color": "blue"},
                            },
                            {"text": {"content": title}},
                        ]
                    }
                }
            )

            # Segment text (split for Notion 2000-char limit)
            text = seg.get("text", "")
            for chunk in _split_text(text, 2000):
                blocks.append({"paragraph": {"rich_text": [{"text": {"content": chunk}}]}})

        self._create_child_page(
            parent_page_id,
            f"逐字稿：{metadata.title[:80]}",
            blocks,
        )

    def _create_child_page(self, parent_page_id: str, title: str, blocks: list[dict]) -> dict:
        """Create a child page under a parent, handling Notion's 100-block limit."""
        page = self.client.pages.create(
            parent={"page_id": parent_page_id},
            properties={"title": {"title": [{"text": {"content": title}}]}},
            children=blocks[:100],
        )
        self._append_blocks(page["id"], blocks[100:])
        return page

    def _append_blocks(self, page_id: str, blocks: list[dict]) -> None:
        """Append blocks in 100-block batches."""
        for i in range(0, len(blocks), 100):
            self.client.blocks.children.append(
                block_id=page_id,
                children=blocks[i : i + 100],
            )

    def add_transcript_subpage(
        self,
        parent_page_id: str,
        transcript_segments: list[dict],
        metadata: VideoMeta,
    ) -> None:
        """Add a transcript child page to an existing summary page."""
        try:
            self._create_transcript_page(parent_page_id, metadata, transcript_segments)
        except Exception as e:
            raise NotionStorageError(f"Failed to add transcript sub-page: {e}") from e

    def route_directory(self, tags: list[str], title: str) -> str:
        """Match content to a directory based on rules."""
        search_text = " ".join(tags + [title]).lower()

        for rule in self.directory_rules:
            if "match" in rule:
                keywords = [k.lower() for k in rule["match"]]
                if any(kw in search_text for kw in keywords):
                    return rule.get("parent", "收件箱")
            if "default" in rule:
                return rule["default"]

        return "收件箱"


def _timestamp_to_seconds(ts: str) -> int:
    """Convert M:SS, MM:SS, or H:MM:SS to seconds."""
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return 0


def _markdown_links_to_rich_text(text: str) -> list[dict]:
    """Convert markdown text with [label](url) links into Notion rich_text array."""

    parts: list[dict] = []
    last_end = 0

    for m in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", text):
        # Text before the link
        before = text[last_end : m.start()]
        if before:
            parts.append({"text": {"content": before}})
        # The link itself
        parts.append({"text": {"content": m.group(1), "link": {"url": m.group(2)}}})
        last_end = m.end()

    # Remaining text after last link
    after = text[last_end:]
    if after:
        parts.append({"text": {"content": after}})

    return parts or [{"text": {"content": text}}]


def _split_text(text: str, max_len: int) -> list[str]:
    """Split text into chunks of max_len characters."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to split at a newline or space
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = text.rfind(" ", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    return chunks
