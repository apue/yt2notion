# Bundle-Only Transcript Cleanup Design

## Goal

收敛 `yt2notion` 为当前认可的三篇输出：`source`、`A 导读`、`B 扩展`。同时把 YouTube auto caption、webpage transcript、Groq/remote ASR 都视为需要清洗的 transcript 输入，避免把 auto caption 当作足够干净的人工字幕。

## Non-Goals

- 不保留 legacy single summary 输出路径。
- 不保留 entity extraction / relation graph。
- 不保留旧 summary/map-reduce/chinese prompt 体系。
- 不设计新的 prompt 文风；本轮只保留当前 bundle 成稿 prompt。
- 不调用远程 ASR、LLM、Notion 或 Obsidian 在线验证。

## Product Decision

正式 pipeline 只产出 `NoteBundle`：

1. `source`：轻索引与来源入口。
2. `guide`：A 导读版。
3. `longform`：B 扩展成稿。

`output.note_mode` 和 `output.mode` 不再作为产品分支存在。`prepare` / `process --dry-run` 返回 bundle payload；publish 使用 storage backend 的 bundle writer。第一版 bundle-only publish 只支持 Obsidian，因为现有 Notion storage 尚未实现三篇 bundle 写入。若用户配置 Notion/Markdown 并尝试发布，应早失败并说明需要 Obsidian backend。

## Transcript Cleanup Policy

当前 `source` 字段只有 `subtitle` / `asr`，不能表达字幕质量。本轮新增 transcript cleanup policy：

| Input origin | Cleanup |
|---|---|
| manual YouTube subtitle | skip cleanup |
| YouTube auto caption | cleanup |
| webpage transcript | cleanup |
| Groq / remote ASR | cleanup |

实现上优先通过 transcript segment 的 `source` / `origin` / `kind` / `is_auto_generated` 字段判断。如果当前 extractor 暂时无法可靠区分 manual subtitle 与 auto caption，则保守策略是：只有明确标记为 `manual_subtitle` 的 transcript 才跳过清洗；其它 transcript 均清洗。

`review.md` 暂时继续作为 transcript cleanup prompt，后续可重命名为 `cleanup_transcript.md`。

## Prompt Policy

最终保留：

- `compose_guide.md`
- `compose_longform.md`
- `compose_note_metadata.md`
- `review.md`
- `topic_segment.md`

删除：

- `chinese.md`
- `extract_chapters.md`
- `extract_entities.md`
- `reduce_entities.md`
- `review_with_context.md`
- `summarize.md`
- `summarize_freeform.md`
- `summarize_reviewed.md`
- `summarize_reviewed_freeform.md`
- `summarize_chunk.md`
- `synthesize.md`

## Pipeline

Canonical pipeline becomes:

1. Download metadata and transcript/audio.
2. Segment or create coarse segments.
3. Transcribe audio when needed, with existing Groq checkpoint behavior.
4. Topic segment ASR-like transcripts when needed.
5. Cleanup transcript if policy says cleanup is required.
6. Build `note_bundle.json` using `note_bundle.build_note_bundle()`.
7. Publish source/A/B bundle via Obsidian storage.

Removed pipeline steps:

- Entity extraction.
- Legacy single summary generation.
- Deferred context review.
- Full transcript subpage output.

## Workspace Artifacts

Kept:

- `metadata.json`
- `segments.json`
- `transcripts.json`
- `reviewed.json` when cleanup ran
- `note_bundle.json`
- Groq checkpoint artifacts: `transcribe_plan.json`, `transcribe_state.json`, `transcribe_chunks/*`

Removed from canonical contract:

- `summary.json`
- `entities.json`

## Storage

- Obsidian remains the supported bundle publish backend.
- Notion/Markdown legacy single-note publishing code may remain temporarily only if tests require it, but pipeline must not route new runs into legacy single output.
- If non-Obsidian backend is configured for bundle publish, fail before remote LLM calls where practical.

## Acceptance Criteria

- Auto-caption-like transcript segments are cleaned before bundle composition unless explicitly marked as manual subtitle.
- Manual subtitle segments skip cleanup.
- Pipeline always builds `note_bundle.json`; it no longer writes `summary.json` or `entities.json` for new runs.
- Old summary/entity prompts are removed from `src/yt2notion/prompts/`.
- `PROJECT_MAP.md`, `README.md`, `config.example.yaml`, and tests reflect bundle-only behavior.
- Local tests and lint pass without online services.
