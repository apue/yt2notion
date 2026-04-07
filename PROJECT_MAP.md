# Project Map

`PROJECT_MAP.md` is the canonical anchor for the repo's architecture truth. When docs disagree about pipeline order, branch logic, workspace artifacts, JSON contracts, prompt bindings, or extension entry points, this file wins.

## Canonical Role

- `PROJECT_MAP.md` owns:
  - pipeline step order and actual execution sequence
  - metadata-driven branch logic
  - workspace artifact and JSON contracts
  - config-to-code mapping
  - prompt-to-code binding
  - backend extension entry points
- `AGENTS.md` owns collaboration rules only.
- `CLAUDE.md` owns developer workflow, commands, and engineering constraints only.
- `.cursorrules` owns policy and style constraints only.
- `README.md` owns user-facing overview only.

## Canonical Parts

- Today: this file is the only canonical part.
- Future growth rule: if this file becomes too large, keep it as the anchor index and split details into `docs/project-map/*.md`.
- Only files linked from this section inherit canonical status. Any other doc may summarize, but must not become a competing source of truth.

## Entry Points

| Entry | File | Purpose |
|---|---|---|
| `uv run yt2notion process "URL"` | `cli.py` → `pipeline.run_pipeline()` | Main CLI entrypoint via Typer (publishes by default) |
| `uv run yt2notion prepare "URL"` | `cli.py` → `pipeline.prepare_content()` | Shared no-publish JSON entrypoint for Claude/Codex wrappers |
| `uv run yt2notion agent <subcommand>` | `cli.py` → `agent_runtime.py` / `agent_worker.py` | File-backed local agent wrapper for queued Codex→Obsidian summary runs |
| `python -m yt2notion.extract_cmd` | `extract_cmd.py` | Legacy transcript-only extraction helper |

`pyproject.toml` registers: `yt2notion = "yt2notion.cli:app"`.

### Agent Runtime Entry Points

The CLI agent is a thin wrapper around the canonical pipeline, not a separate pipeline.

Supported subcommands:

- `agent init`
- `agent add <url>`
- `agent status`
- `agent list`
- `agent show <job-id>`
- `agent logs <job-id>`
- `agent retry <job-id>`
- `agent run [--foreground]`
- hidden internal worker entrypoint: `agent _worker`

Runtime files live under `~/.yt2notion-agent/` by default, overridable via `--agent-home` or `YT2NOTION_AGENT_HOME`:

```text
agent.yaml
AGENTS.md
queue.json
worker.json
jobs/<job-id>.json
logs/<job-id>.log
logs/worker.log
workspace/<video-id>/
```

MVP scope note:

- This runtime is intentionally file-backed and optimized for single-user local use.
- Normal supported usage includes enqueuing new jobs while one worker is already draining the queue.
- It does not claim database-grade consistency under arbitrary concurrent CLI invocations.
- If stronger consistency is needed later, replace this state layer with SQLite rather than continuing to harden ad hoc JSON transactions.

## Canonical Pipeline Map

Precision rule: this ordered list reflects the current implementation in `src/yt2notion/pipeline.py`. Older summaries may still call transcript review "deferred", but current `full` mode performs long-content context review after summary generation and before publish.

1. `DOWNLOAD`
   `metadata.json` + one of `subtitles.*` or `audio.*`
2. `SEGMENT`
   `segments.json`
   Branch: author chapters → LLM chapter extraction from description → no pre-segmentation
3. `TRANSCRIBE`
   `transcripts.json`
   Branch: subtitle assignment → per-segment ASR → full-audio ASR then duration split
4. `TOPIC SEGMENT`
   rewrites `transcripts.json` only after transcription
   Trigger: oversized transcript segments
5. `REVIEW`
   `reviewed.json` in `full` mode only
   Branch: subtitle-sourced content skips review; short ASR in `summary` mode does internal review+summary in one analysis call; short ASR in `full` mode does blocking transcript review; long ASR content skips blocking review in this step
6. `EXTRACT`
   `entities.json`
7. `SUMMARIZE`
   `summary.json`
8. `CONTEXT REVIEW`
   long ASR content in `full` mode only; review transcript with summary context before publish
9. `PUBLISH`
   summary page/note via storage backend
   For long content, publish summary first without transcript subpage

### Pipeline Truth by Step

| Step | Main function | Input | Output | Notes |
|---|---|---|---|---|
| `DOWNLOAD` | `pipeline._step_download()` + subtitle/audio download helpers | URL | `metadata.json`, `subtitles.*` or `audio.*` | Uses `subtitles_available` to choose subtitle vs audio path |
| `SEGMENT` | `pipeline._step_segment()` | `VideoMeta` | `segments.json` | LLM may be used here before ASR when description exists and chapters do not |
| `TRANSCRIBE` | `pipeline._step_transcribe()` | workspace media + optional segments | `transcripts.json` | Subtitles bypass ASR entirely |
| `TOPIC SEGMENT` | `topic_segment.segment_transcript()` | `transcripts.json` | rewritten `transcripts.json` | Runs after transcription, never before |
| `REVIEW` | `pipeline._step_review()` | transcripts | `reviewed.json` | Subtitle transcripts skip cleanup; long ASR content defers to context review step |
| `EXTRACT` | `pipeline._step_extract()` | reviewed transcripts | `entities.json` | Uses `LLMCaller` |
| `SUMMARIZE` | `pipeline._step_summarize()` | reviewed transcripts | `summary.json` | Short content single pass or chapter-aware; long content map-reduce |
| `CONTEXT REVIEW` | `pipeline._review_transcript_with_summary_context()` | long-form transcripts + summary context | rewritten `reviewed.json` | `full` mode long ASR only; retries-exhausted falls back to unreviewed transcript with warning note |
| `PUBLISH` | `storage.save()` | summary + metadata + optional transcript/entities | backend artifact | Long content omits transcript subpage in this call |

### Branch Rules

- `metadata.subtitles_available = true`:
  - try subtitle download first
  - if subtitle download fails, fall back to audio download
- `metadata.chapters` non-empty:
  - use author chapters directly in `SEGMENT`
- `metadata.chapters` empty and `metadata.description` non-empty:
  - call `chapter_extract.extract_chapters_llm()`
  - if LLM returns nothing or fails, fall back to regex-like timestamp parsing from description
- no chapters and no usable description structure:
  - proceed without pre-segmentation
  - transcription creates coarse transcript segments
  - topic segmentation may refine them afterwards
- subtitle-sourced transcripts:
  - skip blocking review
- long content:
  - skip blocking review in `REVIEW`
  - summarize first
  - in `full` mode, run context review before publish
  - publish summary first, then attach transcript subpage/file

## Workspace Artifacts and Contracts

Canonical workspace artifacts:

| Artifact | Producer | Shape / meaning |
|---|---|---|
| `metadata.json` | `DOWNLOAD` | `VideoMeta` dataclass from `models/base.py` |
| `segments.json` | `SEGMENT` | `list[{title, start_seconds, end_seconds, ?parent_title}]` |
| `transcripts.json` | `TRANSCRIBE` / `TOPIC SEGMENT` | `list[{title, start_seconds, end_seconds, text, source}]`, `source = "subtitle" | "asr"` |
| `reviewed.json` | `REVIEW` / `CONTEXT REVIEW` | same shape as `transcripts.json`; `text` cleaned or context-reviewed |
| `entities.json` | `EXTRACT` | `EntityResult {domain, is_entity_centric, entity_types, entities, relations}` |
| `summary.json` | `SUMMARIZE` | `ChineseContent {overview, key_points, tags, fun_facts, raw_markdown, ?mindmap}` |
| `failed.json` | top-level pipeline error handling | `{url, step, error_type, error_message, retries_exhausted, timestamp}` style failure record |

Common non-JSON side artifacts:

| Artifact | Producer | Notes |
|---|---|---|
| `subtitles.srt` / `subtitles.vtt` | subtitle download | exact suffix depends on source |
| `audio.mp3` | audio download | used for ASR path |
| `segments/*.mp3` | per-segment ASR | transient workspace split files |

All core model types live in `models/base.py`: `VideoMeta`, `Chapter`, `Summary`, `ChunkSummary`, `ChineseContent`, `Entity`, `EntityResult`, `FUN_FACTS_CATEGORIES`.

## Config ↔ Code Map

| `config.yaml` path | Consumer | Purpose |
|---|---|---|
| `model.backend` | `models/__init__.py:create_summarizer()` | choose `Summarizer` backend |
| `model.summarize_model` | summarizer map phase | Sonnet-like per-segment summary model |
| `model.translate_model` | summarizer reduce phase | Opus-like Chinese synthesis model |
| `model.review_model` | `models/llm.py:create_llm_caller()` | lightweight LLM tasks such as chapter extraction / review / topic split |
| `storage.backend` | `storage/__init__.py:create_storage()` | choose storage backend |
| `storage.notion.*` | `storage/notion.py:NotionStorage.__init__()` | token / database / parent / rules |
| `storage.obsidian.*` | `storage/obsidian.py:ObsidianStorage.__init__()` | vault and directory paths |
| `extract.subtitle_priority` | `extract.py:extract_subtitles()` | subtitle language preference |
| `extract.asr.backend` | `transcribe/__init__.py:create_transcriber()` | choose ASR backend |
| `extract.asr.endpoint` | `transcribe/remote.py:RemoteTranscriber` | remote ASR endpoint or `ASR_ENDPOINT` env override |
| `extract.asr.healthcheck_path` | `transcribe/remote.py:RemoteTranscriber` | ASR health endpoint (default `/health`) |
| `extract.asr.healthcheck_timeout_seconds` | `transcribe/remote.py:RemoteTranscriber` | timeout for ASR health checks |
| `extract.asr.restart_before_transcribe` | `transcribe/remote.py:RemoteTranscriber` | restart ASR once before first transcription call |
| `extract.asr.restart_on_unhealthy` | `transcribe/remote.py:RemoteTranscriber` | restart ASR only when health check fails |
| `extract.asr.restart_command` | `transcribe/remote.py:RemoteTranscriber` | shell command to restart remote ASR service |
| `extract.asr.restart_readiness_timeout_seconds` | `transcribe/remote.py:RemoteTranscriber` | max wait time for ASR to become healthy after restart |
| `extract.asr.restart_readiness_interval_seconds` | `transcribe/remote.py:RemoteTranscriber` | polling interval for post-restart health checks |
| `extract.asr.restart_grace_seconds` | `transcribe/remote.py:RemoteTranscriber` | fallback fixed wait when health endpoint is unavailable |
| `output.mode` | `pipeline.py:_resolve_output_mode()` | `summary` or `full` output behavior |
| `output.max_segment_seconds` | `pipeline.py` + `topic_segment.py` | pre-split long chapter segments and trigger topic split threshold |
| `output.long_content_threshold_seconds` | `pipeline.py:_is_long_content()` | short vs long content branching |
| `output.chunk_duration_seconds` | `process.py` | timestamp chunking granularity |
| `workspace.base_dir` | `workspace.py:Workspace` | workspace root |
| `model._runtime.codex_workdir` | `models/llm.py:create_llm_caller()`, `models/__init__.py:create_summarizer()`, `models/codex_cli.py` | optional internal override so Codex subprocesses run under agent home and inherit runtime `AGENTS.md` |

### Agent Config Expansion

`agent_runtime.py:build_runtime_app_config()` maps the minimal runtime `agent.yaml` into an `AppConfig` for the canonical pipeline:

- forces `model.backend = "codex_cli"`
- forces `storage.backend = "obsidian"`
- forces `output.mode = "summary"`
- sets `model.summarize_model`, `model.translate_model`, `model.review_model` from `agent.yaml`
- sets `model.reasoning_effort` from `agent.yaml`
- sets `model._runtime.codex_workdir = <agent_home>`
- sets `storage.obsidian.*` from `agent.yaml`
- sets `workspace.base_dir` from `agent.yaml`
- preserves repo `config.yaml` values outside that override set, especially `extract.asr.*`

This is how the agent reuses current ASR self-healing behavior without exposing those knobs in the minimal runtime config.

Config load path: `config.py:load_config()` → read YAML → deep-merge with defaults → validate backend values → return `AppConfig`.
ASR operations runbook: `docs/operations/asr-service.md`.

## Factory Functions

Backends are selected by explicit `if/elif` factories, not registries:

| Factory | Location | Config field | Current implementations |
|---|---|---|---|
| `create_summarizer(config)` | `models/__init__.py` | `model.backend` | `claude_code`, `anthropic_api`, `codex_cli`, `openai_api` alias |
| `create_storage(config)` | `storage/__init__.py` | `storage.backend` | `notion`, `obsidian` |
| `create_transcriber(config)` | `transcribe/__init__.py` | `extract.asr.backend` | `remote` |
| `create_llm_caller(config, model_key=)` | `models/llm.py` | `model.backend` + `model.{model_key}` | `claude_code`, `codex_cli`, `openai_api` alias |

## Prompt Templates ↔ Code Bindings

Prompt rendering uses `prompts/__init__.py:render_prompt(name, **kwargs)`, implemented with `str.replace("{key}", value)` rather than `str.format()`.

| Template | Caller | Model role | Variables |
|---|---|---|---|
| `extract_chapters.md` | `chapter_extract.py` | chapter extraction | `{total_duration}` |
| `topic_segment.md` | `topic_segment.py` | topic boundary splitting | `{channel}`, `{title}`, `{duration_seconds}`, `{char_count}` |
| `review.md` | `review.py` | baseline transcript cleanup | `{title}`, `{channel}` |
| `review_with_context.md` | `review.py` | context-aware transcript cleanup | `{title}`, `{channel}`, review-context vars |
| `extract_entities.md` | `entity_extract.py` map phase | entity extraction | none |
| `reduce_entities.md` | `entity_extract.py` reduce phase | entity reduction | none |
| `summarize.md` | summarizer | short content with chapters | none |
| `summarize_freeform.md` | summarizer | short content without chapters | none |
| `summarize_asr.md` | `pipeline._summarize_short_asr_single_pass()` | short ASR internal review+summary (chapters, summary mode) | none |
| `summarize_asr_freeform.md` | `pipeline._summarize_short_asr_single_pass()` | short ASR internal review+summary (freeform, summary mode) | none |
| `summarize_reviewed.md` | summarizer | short ASR review+summary (chapters) | none |
| `summarize_reviewed_freeform.md` | summarizer | short ASR review+summary (freeform) | none |
| `summarize_chunk.md` | summarizer map phase | long-form chunk summary | `{segment_title}`, `{start_time}`, `{end_time}`, `{segment_index}`, `{total_segments}` |
| `chinese.md` | summarizer reduce phase | Chinese synthesis | none |
| `synthesize.md` | summarizer final synthesis | output polishing | `{title}`, `{channel}`, `{duration}`, `{url}` |

## Extension Checklist

### Add a model backend

1. Create `src/yt2notion/models/<backend>.py` implementing `Summarizer`.
2. Extend `src/yt2notion/models/__init__.py:create_summarizer()`.
3. Extend `src/yt2notion/models/llm.py:create_llm_caller()` if the backend also supports lightweight calls.
4. Update `src/yt2notion/config.py` valid backend list.
5. Update `config.example.yaml`.

### Add a storage backend

1. Create `src/yt2notion/storage/<backend>.py` implementing `Storage`.
2. Extend `src/yt2notion/storage/__init__.py:create_storage()`.
3. Update `src/yt2notion/config.py` valid storage backends if needed.
4. Update `config.example.yaml`.

### Add an ASR backend

1. Create `src/yt2notion/transcribe/<backend>.py` implementing `Transcriber`.
2. Extend `src/yt2notion/transcribe/__init__.py:create_transcriber()`.
3. Update `config.example.yaml`.

### Add a prompt template

1. Create `src/yt2notion/prompts/<template>.md`.
2. Load it with `render_prompt("<template>", ...)`.
3. Update the prompt binding table in this file.

### Change pipeline behavior

1. Update `src/yt2notion/pipeline.py` and any affected step modules.
2. Update this file first if step order, branch logic, artifact shape, or prompt binding changes.
3. Then update summaries in `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, and `README.md` only as needed.

## Dependency Map

```text
cli.py -> config.py, pipeline.py
pipeline.py -> extract.py, process.py, workspace.py,
               chapter_extract.py, segment.py, topic_segment.py, review.py, entity_extract.py,
               models/__init__.py, storage/__init__.py, transcribe/__init__.py
chapter_extract.py, review.py, topic_segment.py, entity_extract.py -> models/llm.py, prompts/
models/claude_code.py, models/anthropic_api.py -> prompts/, models/_parsers.py
models/codex_cli.py -> prompts/, models/_parsers.py
models/_parsers.py -> models/base.py
storage/notion.py -> notion_client
transcribe/remote.py -> httpx
extract.py -> subprocess (yt-dlp CLI)
audio.py -> subprocess (ffmpeg / ffprobe CLI)
models/llm.py ClaudeCodeCaller -> subprocess (claude CLI)
models/codex_cli.py -> subprocess (codex CLI)
```

## Maintenance Rules

- If pipeline order changes, update `PROJECT_MAP.md` first.
- If branch conditions or workspace artifact shapes change, update `PROJECT_MAP.md` first.
- If prompt bindings change, update `PROJECT_MAP.md` first.
- If this file grows too large, split canonical sections into `docs/project-map/*.md` and register each canonical part in `## Canonical Parts`.
- Do not let any other active doc become a parallel source of architecture truth.
