# Sync Documentation with PR #4–#9 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update README.md, CLAUDE.md, and PROJECT_MAP.md to accurately reflect all changes introduced in PRs #4 through #9.

**Architecture:** Pure documentation update — no code changes. Each doc file is updated independently based on a diff audit of what PRs #4–#9 changed versus what each doc currently says.

**Tech Stack:** Markdown only.

---

## Change Audit

Below is the complete list of code changes from PR #4–#9 that affect documentation, grouped by which doc needs updating.

### PR #4: Add parent_page_id support to NotionStorage
- Added `storage.notion.parent_page_id` config field (slash command / MCP mode)
- `config.example.yaml` already updated in PR #7

### PR #6: Fun facts extraction + pipeline optimization
- Added `fun_facts` field to `ChineseContent` dataclass
- Added `FUN_FACTS_CATEGORIES` constant in `models/base.py`
- Added `review_with_context.md` prompt template (used when review context is available)
- Added `synthesize.md` prompt template (Opus reduce for long content)
- `chinese.md` prompt updated with fun facts section
- `summarize_chunk.md` prompt updated
- Pipeline now has **deferred review** — review happens after summarize for long content, not before
- `Storage` protocol gained `add_transcript_subpage()` method

### PR #7: Obsidian storage backend
- Docs were updated for Obsidian — this is the baseline

### PR #8: Fix tags parsing + fun facts in Obsidian + remove --max-tokens
- Removed `--max-tokens` flag from `ClaudeCodeCaller`
- Fun facts rendering added to Obsidian output
- Tags regex fix in `_parsers.py`

### PR #9: Fix transcript for long content + clean up storage protocol
- `Storage.add_transcript_subpage()` signature: `parent_page_id: str` → `summary_ref: str`
- Removed `_extract_page_id()` helper from `pipeline.py`
- Pipeline passes `summary_ref` (return value of `save()`) directly to `add_transcript_subpage()`
- Deferred review now has error handling (falls back to unreviewed transcript)

---

## File Structure

All modifications — no new files created:

| File | Action | Responsibility |
|------|--------|---------------|
| `README.md` | Modify | User-facing overview: pipeline diagram, features list |
| `CLAUDE.md` | Modify | Developer-facing: architecture, data models, pipeline flow |
| `PROJECT_MAP.md` | Modify | Code navigator: data contracts, prompt table, storage protocol, dependency graph |

---

### Task 1: Update README.md

**Files:**
- Modify: `README.md:67-83` (pipeline diagram)
- Modify: `README.md:1-16` (features list)

- [ ] **Step 1: Update the pipeline diagram to reflect deferred review**

The current diagram shows review (step 4) always before summarize (step 5). Since PR #6, long content does review *after* summarize. Update the "How It Works" section:

```markdown
## How It Works

```
YouTube / Podcast URL
    │
    1. DOWNLOAD ─── yt-dlp: metadata + subtitles or audio
    │
    2. SEGMENT ──── chapters → LLM extract from description → N/A
    │
    3. TRANSCRIBE ─ subtitle assignment or per-segment ASR
    │       │
    │       └── 3.5 TOPIC SEGMENT ── Haiku splits oversized segments
    │
    4. REVIEW ───── Haiku cleans ASR errors, fixes proper nouns
    │
    5. SUMMARIZE ── Sonnet map (per-segment) + Opus reduce (global)
    │       │
    │       └── 5.5 DEFERRED REVIEW ── for long content: review + transcript after summary
    │
    └── Storage: summary + transcript (Notion page / Obsidian note)
```
```

Key changes from current:
- Add step 5.5 (deferred review) line
- Change final line from "Notion API: summary page + transcript sub-page" to "Storage: summary + transcript (Notion page / Obsidian note)" — reflects multiple backends

- [ ] **Step 2: Add fun facts to the features list**

Add after the "Timestamped key points" bullet:

```markdown
- **Fun facts extraction**: hot takes, nerd stats, and media mentions pulled from content
```

- [ ] **Step 3: Verify no other README sections need changes**

Review the rest of README.md:
- Storage Backends table already shows Obsidian ✅ (updated in PR #7)
- Quick Start, Prerequisites, Model Backends, Configuration, Development, Contributing — all still accurate
- No changes needed

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: update README pipeline diagram and features for PR #4-#9 changes"
```

---

### Task 2: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` — Architecture section, pipeline flow, model table

- [ ] **Step 1: Update the pipeline flow diagram**

Replace the current pipeline flow in the "### 管道流程（5-step metadata-driven）" section:

```markdown
### 管道流程（5-step metadata-driven）

```
URL
 ↓
1. DOWNLOAD     → metadata.json + (subtitles.srt | audio.mp3)
 ↓
2. SEGMENT      → segments.json  (chapters > LLM提取 > N/A)
 ↓
3. TRANSCRIBE   → transcripts.json  (字幕分配 | 逐段ASR | 全量ASR+句分)
 ↓                    ↓
 │              3.5 TOPIC SEGMENT  (超长段落 → Haiku 按话题拆分)
 ↓
4. REVIEW       → reviewed.json  (Haiku 校对 ASR 错误)
 ↓
5. SUMMARIZE    → summary.json   (Sonnet map × N + Opus reduce → Storage)
 ↓                    ↓
 │              5.5 DEFERRED REVIEW  (长内容：总结后再校对 + 写入 transcript)
 ↓
6. PUBLISH      → Notion page / Obsidian note + transcript sub-page/文件
```
```

Key changes:
- Add step 5.5 deferred review
- Change "→ Notion" to "→ Storage" in step 5
- Add step 6 PUBLISH to make storage explicit

- [ ] **Step 2: Update the data contract description**

The `ChineseContent` description in the pipeline section currently reads:
```
Step 5 → summary.json     : ChineseContent {overview, key_points[{timestamp, title, summary}], tags, raw_markdown, ?mindmap}
```

Update to include `fun_facts`:
```
Step 5 → summary.json     : ChineseContent {overview, key_points[{timestamp, title, summary}], tags, fun_facts, raw_markdown, ?mindmap}
```

- [ ] **Step 3: Update the description line at top**

Current:
```
媒体内容（YouTube 视频、Podcast 等）→ 字幕/转写 → LLM 总结 → Notion 发布的 CLI 管道工具。
```

Update to reflect multiple storage backends:
```
媒体内容（YouTube 视频、Podcast 等）→ 字幕/转写 → LLM 总结 → Notion / Obsidian 发布的 CLI 管道工具。
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md architecture for fun facts, deferred review, multi-backend"
```

---

### Task 3: Update PROJECT_MAP.md

**Files:**
- Modify: `PROJECT_MAP.md` — data contract, prompt table, storage protocol, dependency graph

- [ ] **Step 1: Update the data contract section**

In "## 步骤间数据契约", update the Step 5 line:

Current:
```
Step 5 → summary.json     : ChineseContent {overview, key_points[{timestamp, title, summary}], tags, raw_markdown, ?mindmap}
```

Replace with:
```
Step 5 → summary.json     : ChineseContent {overview, key_points[{timestamp, title, summary}], tags, fun_facts, raw_markdown, ?mindmap}
```

Also add after the data models line:
```
所有数据模型定义在 `models/base.py`：VideoMeta, Chapter, Summary, ChunkSummary, ChineseContent, FUN_FACTS_CATEGORIES 等。
```

- [ ] **Step 2: Update the prompt template table**

Add the two new prompt templates from PR #6. The current table is missing `review_with_context.md` and `synthesize.md`. Add these rows:

```markdown
| `review_with_context.md` | `review.py` (当有 review context 时) | Haiku | `{title}`, `{channel}` |
| `synthesize.md` | Summarizer.synthesize() | Opus | `{title}`, `{channel}`, `{duration}`, `{url}` |
```

Note: `synthesize.md` is already listed in the current table. Verify the row is accurate and only add `review_with_context.md`.

- [ ] **Step 3: Update the Storage protocol description**

The current "扩展 Checklist > 加新 storage backend" section mentions `save()` but not `add_transcript_subpage()`. Add a note about the two-method protocol:

After "实现 `Storage` protocol 的 `save()` 方法", add:
```
   （Storage protocol 有两个方法：`save()` 返回 summary_ref，`add_transcript_subpage(summary_ref, ...)` 添加转录子页面）
```

- [ ] **Step 4: Update the dependency graph**

Add the `models/base.py` → `FUN_FACTS_CATEGORIES` dependency from `storage/obsidian.py`:

Current:
```
storage/notion.py → notion_client (外部库)
```

Add after:
```
storage/obsidian.py → models/base.py (FUN_FACTS_CATEGORIES)
```

- [ ] **Step 5: Commit**

```bash
git add PROJECT_MAP.md
git commit -m "docs: update PROJECT_MAP.md for fun facts, review_with_context prompt, storage protocol"
```

---

### Task 4: Final verification

- [ ] **Step 1: Verify all three docs are internally consistent**

Read through each file and check:
- Pipeline step numbering is consistent across README, CLAUDE.md, PROJECT_MAP.md
- `ChineseContent` fields match across CLAUDE.md and PROJECT_MAP.md
- Prompt template table in PROJECT_MAP.md matches actual files in `src/yt2notion/prompts/`
- Storage protocol description matches `storage/base.py`

- [ ] **Step 2: Run linter to catch any markdown issues**

```bash
# No markdown linter configured, just eyeball check
```

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git add README.md CLAUDE.md PROJECT_MAP.md
git commit -m "docs: fix consistency issues across doc files"
```
