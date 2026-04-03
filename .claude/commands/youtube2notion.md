---
name: youtube2notion
description: Extract YouTube video, summarize, and publish to Notion
---

Process a YouTube video into a Chinese Notion page: $ARGUMENTS

The first argument is the YouTube URL. Follow these steps precisely:

Before starting:
1. Read `AGENTS.md`
2. Read `handoff.md`
3. Follow the repository workflow and safety rules from those files

## Step 1: Extract video data

Run this command to extract metadata and transcript:

```bash
uv run python -m yt2notion.extract_cmd "$ARGUMENTS"
```

Parse the JSON output. It contains:
- `metadata`: video_id, title, channel, url, upload_date, chapter_count
- `transcript`: formatted transcript (chapter-grouped or timestamped)
- `prompt_mode`: "chapters" or "freeform"

## Step 2: Summarize the transcript

Based on `prompt_mode`, produce a structured JSON summary:

**If prompt_mode is "chapters"** — the transcript has `[CHAPTER start=M:SS title="..."]` markers:
- Summarize EACH chapter (do not skip or merge)
- Use the ACTUAL timestamps from chapter markers

**If prompt_mode is "freeform"** — the transcript has per-line `[M:SS]` timestamps:
- Identify 3-8 key topic segments yourself
- Use ACTUAL timestamps from transcript lines

Output this JSON structure (do NOT output it to the user, keep it in your working memory):
```json
{
  "sections": [
    {"title": "...", "timestamp": "M:SS", "timestamp_seconds": N, "summary": "..."}
  ],
  "overall_summary": "...",
  "suggested_tags": ["tag1", "tag2", "tag3"]
}
```

Rules:
- Summaries in English, factual and dense
- 3-5 suggested_tags in English
- Keep timestamps accurate from source data

## Step 3: Rewrite in Chinese

Transform the summary into natural Chinese notes. NOT literal translation — rewrite like a native Chinese speaker's study notes.

Format:
```
## 概要
（2-3 句话总结，50-100 字）

## 关键节点
- [M:SS] **节点标题**：1-2 句摘要
- [M:SS] **节点标题**：1-2 句摘要
...

## 标签
标签1, 标签2, 标签3
```

Rules:
- Timestamps from the summary data, do not fabricate
- Tags in Chinese (e.g. "hip mobility" → "髋关节灵活性")
- Tone: personal learning notes, not formal documentation

## Step 4: Read config for Notion parent page

Read `config.yaml` in the project root. Look for `storage.notion.parent_page_id`. This is the root page under which to organize notes.

If no config.yaml or no parent_page_id, ask the user.

## Step 5: Determine Notion placement

Use `notion-fetch` to read the parent page and see its existing sub-pages (categories like "健身", "技术", "AI" etc.).

Based on the video content and tags, decide:
- If an existing sub-page is a good fit → use it as parent
- If no sub-page fits → create a new category sub-page first, with a fitting emoji icon

Tell the user which category you chose and why (one line).

## Step 6: Create the Notion page

Use `notion-create-pages` with the parameters below. The MCP server name for Notion is `claude.ai Notion`.

**Parent**: use `{"page_id": "<chosen_parent_page_id>"}` — the page_id is a UUID (with or without dashes).

**Page structure**:

```json
{
  "parent": {"page_id": "<parent_id>"},
  "pages": [{
    "properties": {"title": "<Chinese title or original>"},
    "icon": "<topic-fitting emoji>",
    "content": "<Notion-flavored markdown content>"
  }]
}
```

**Content** must use Notion-flavored markdown (NOT standard markdown). Key syntax:

- Callout block (for source credit):
  ```
  <callout icon="📺" color="gray_bg">
  \t**来源**：{channel} 「{title}」
  \t**链接**：[{url}]({url})
  </callout>
  ```
- Headings: `## 概要`, `## 关键节点`, `## 标签`
- Bulleted list: `- item` (use standard markdown dash)
- Bold: `**text**`
- Links: `[text](url)`
- Timestamps as clickable YouTube links: `[M:SS](https://youtu.be/{video_id}?t={seconds})`
- Use `\n` for line breaks between blocks — do NOT use `<br>` between blocks
- Do NOT use `<empty-block/>` unless you specifically need a blank line
- Indent children with tabs

**Content order**:
1. Callout block with source credit
2. `## 概要` + summary paragraph
3. `## 关键节点` + bulleted list with timestamp links
4. `## 标签` + comma-separated Chinese tags

After creation, output the Notion page URL to the user.
