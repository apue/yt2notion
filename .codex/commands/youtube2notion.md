---
name: youtube2notion
description: Process media with the repo pipeline and publish the prepared result
---

Process a YouTube video or podcast into a final note/page: $ARGUMENTS

The first argument is the media URL. Optional flags such as `--mode full` may be forwarded to the shared repo CLI.

Before starting:
1. Read `AGENTS.md`
2. Read `handoff.md`
3. Follow the repository workflow and safety rules from those files

## Step 1: Prepare processed content

Run the shared no-publish repo command:

```bash
uv run yt2notion prepare "$ARGUMENTS"
```

Parse the JSON output. It contains:
- `mode`: `summary` or `full`
- `metadata`: source metadata
- `summary.raw_markdown`: final Chinese markdown already produced by the repo pipeline
- `summary.key_points` / `summary.tags`: structured summary data
- `transcript_segments` and `transcript_markdown`: only present in `full` mode
- `workspace_dir`: workspace artifact directory for inspection or resume

Do not re-summarize the transcript yourself. Use the repo-generated output as the single source for publishing.

## Step 2: Publish using the target storage workflow

If the task is about Notion, read `config.yaml` for `storage.notion.parent_page_id` and use the available Notion tooling to place the page under the best matching category.

If the task is about Obsidian or local verification, prefer the repo pipeline or workspace artifacts instead of regenerating content.

Rules:
- Preserve source credit from `metadata`
- Use `summary.raw_markdown` as the main body
- If `mode` is `full`, use `transcript_markdown` instead of regenerating transcript text
- If `mode` is `summary`, do not fabricate transcript output
