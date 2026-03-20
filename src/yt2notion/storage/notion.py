"""Notion storage backend. Creates pages with rich content."""

from __future__ import annotations

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
        database_id: str,
        directory_rules: list[dict] | None = None,
        credit_format: str = "来源：{channel} 「{title}」\n链接：{url}",
    ) -> None:
        if _NotionClient is None:
            raise NotionStorageError("notion-client not installed. Run: uv sync --extra notion")
        self.client = _NotionClient(auth=token)
        self.database_id = database_id
        self.directory_rules = directory_rules or []
        self.credit_format = credit_format

    def save(self, content: ChineseContent, metadata: VideoMeta) -> str:
        """Create a Notion page and return its URL."""
        properties = self._build_page_properties(content, metadata)
        blocks = self._build_blocks(content, metadata)

        try:
            page = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
                children=blocks,
            )
            return page.get("url", "")
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
    """Convert M:SS or MM:SS to seconds."""
    parts = ts.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return 0


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
