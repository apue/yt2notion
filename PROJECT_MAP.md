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
config.yaml
AGENTS.md
queue.json
worker.json
jobs/<job-id>.json
logs/<job-id>.log
logs/worker.log
workspace/<video-id>/
```

Runtime config split:
- `agent.yaml`: runtime control plane only
- `config.yaml`: pipeline config for agent jobs

Agent config default:
- `agent add` / `agent run` / `agent retry` / `agent _worker` read pipeline config from `<agent_home>/config.yaml` by default
- `--config` overrides that default path

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
   ASR backend rule: primary backend comes from `extract.asr.backend`; Groq hourly quota waits through the current window from persisted checkpoint state, while Groq daily quota can switch the current failed chunk plus remaining pending chunks to `extract.asr.fallback_backend`
4. `TOPIC SEGMENT`
   rewrites `transcripts.json` only after transcription
   Trigger: oversized transcript segments
5. `REVIEW`
   `reviewed.json` in `full` mode only
   Branch: subtitle-sourced content skips review; short ASR in `summary` mode does internal review+summary in one analysis call; short ASR in `full` mode does blocking transcript review; long ASR content skips blocking review in this step
6. `EXTRACT`
   `entities.json`
7. `SUMMARIZE`
   `summary.json` or `note_bundle.json`
8. `CONTEXT REVIEW`
   long ASR content in `full` mode only; review transcript with summary context before publish
9. `PUBLISH`
   summary page/note via storage backend, or source/A/B bundle via Obsidian bundle publish
   For long single-note content, publish summary first without transcript subpage

### Pipeline Truth by Step

| Step | Main function | Input | Output | Notes |
|---|---|---|---|---|
| `DOWNLOAD` | `pipeline._step_download()` + subtitle/audio download helpers | URL | `metadata.json`, `subtitles.*` or `audio.*` | Uses `subtitles_available` to choose subtitle vs audio path |
| `SEGMENT` | `pipeline._step_segment()` | `VideoMeta` | `segments.json` | LLM may be used here before ASR when description exists and chapters do not |
| `TRANSCRIBE` | `pipeline._step_transcribe()` | workspace media + optional segments | `transcripts.json` | Subtitles bypass ASR entirely; audio path persists `transcribe_plan.json`, `transcribe_state.json`, and `transcribe_chunks/<chunk_id>.json` while running chunked ASR, then writes final `transcripts.json` only after every chunk completes |
| `TOPIC SEGMENT` | `topic_segment.segment_transcript()` | `transcripts.json` | rewritten `transcripts.json` | Runs after transcription, never before |
| `REVIEW` | `pipeline._step_review()` | transcripts | `reviewed.json` | Subtitle transcripts skip cleanup; long ASR content defers to context review step |
| `EXTRACT` | `pipeline._step_extract()` | reviewed transcripts | `entities.json` | Uses `LLMCaller` |
| `SUMMARIZE` | `pipeline._step_summarize()` or `note_bundle.build_note_bundle()` | reviewed transcripts | `summary.json` or `note_bundle.json` | Obsidian workflows default to `source_ab_bundle` (`source -> A导读 -> B扩展`); other backends default to legacy `single` unless explicitly overridden |
| `CONTEXT REVIEW` | `pipeline._review_transcript_with_summary_context()` | long-form transcripts + summary context | rewritten `reviewed.json` | `full` mode long ASR only; retries-exhausted falls back to unreviewed transcript with warning note |
| `PUBLISH` | `storage.save()` or `storage.save_note_bundle()` | summary or note bundle + metadata + optional transcript/entities | backend artifact | Bundle publish currently requires `storage.backend = obsidian`; long transcript subpage remains single-note only |

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
- audio-sourced transcripts:
  - primary transcriber from `extract.asr.backend`
  - when primary is `groq`, `TranscriptionHourlyLimitError` waits through the current hourly window and retries the same pending chunk
  - when primary is `groq`, `TranscriptionDailyLimitError` switches the current failed chunk and all remaining pending chunks of the current job to `extract.asr.fallback_backend`
  - chunk-level progress is persisted in workspace checkpoint artifacts, so completed chunks are not recomputed after a resume
  - rerunning from an earlier step than `TRANSCRIBE` discards prior transcribe checkpoint artifacts before starting a new ASR pass
  - Groq request errors outside the quota path (for example `400/401/403`) fail directly without fallback
- long content:
  - skip blocking review in `REVIEW`
  - summarize first
  - in `full` mode, run context review before publish
  - publish summary first, then attach transcript subpage/file
- `output.note_mode = source_ab_bundle`:
  - only supported with `output.mode = summary`
  - short ASR content runs blocking transcript review before bundle generation so A/B notes do not regress versus single-note mode
  - summarize step builds `NoteBundle` from reviewed transcript via `note_bundle.build_note_bundle()`
  - publish currently requires `storage.backend = obsidian`

## Workspace Artifacts and Contracts

Canonical workspace artifacts:

| Artifact | Producer | Shape / meaning |
|---|---|---|
| `metadata.json` | `DOWNLOAD` | `VideoMeta` dataclass from `models/base.py` |
| `segments.json` | `SEGMENT` | `list[{title, start_seconds, end_seconds, ?parent_title}]` |
| `transcribe_plan.json` | `TRANSCRIBE` | `list[{chunk_id, title, start_seconds, end_seconds, audio_relpath, preferred_backend, ?segment_index}]` |
| `transcribe_state.json` | `TRANSCRIBE` | `{version, job_mode, status, next_attempt_at, last_error, defer_reason, ash_defer_count, chunks[]}` |
| `transcribe_chunks/<chunk_id>.json` | `TRANSCRIBE` | `list[{start_seconds, end_seconds, text, source}]` for each completed chunk |
| `transcripts.json` | `TRANSCRIBE` / `TOPIC SEGMENT` | `list[{title, start_seconds, end_seconds, text, source}]`, `source = "subtitle" | "asr"` |
| `reviewed.json` | `REVIEW` / `CONTEXT REVIEW` | same shape as `transcripts.json`; `text` cleaned or context-reviewed |
| `entities.json` | `EXTRACT` | `EntityResult {domain, is_entity_centric, entity_types, entities, relations}` |
| `summary.json` | `SUMMARIZE` | `ChineseContent {overview, key_points, tags, fun_facts, raw_markdown, ?mindmap}` |
| `note_bundle.json` | `SUMMARIZE` | `NoteBundle {source, guide, longform, stable_tags, source_topics}` where each note is `NoteDocument {title, markdown, tags, variant}` |
| `failed.json` | top-level pipeline error handling | `{url, step, error_type, error_message, retries_exhausted, timestamp}` style failure record |

Common non-JSON side artifacts:

| Artifact | Producer | Notes |
|---|---|---|
| `subtitles.srt` / `subtitles.vtt` | subtitle download | exact suffix depends on source |
| `audio.mp3` | audio download | used for ASR path |
| `segments/*.mp3` | per-segment ASR | transient workspace split files |

All core model types live in `models/base.py`: `VideoMeta`, `Chapter`, `Summary`, `ChunkSummary`, `ChineseContent`, `NoteMetadata`, `NoteDocument`, `NoteBundle`, `Entity`, `EntityResult`, `FUN_FACTS_CATEGORIES`.

## Config ↔ Code Map

Path resolution note:
- Main CLI (`process` / `prepare`) uses normal `config.yaml` resolution.
- Agent commands use `<agent_home>/config.yaml` by default unless `--config` is provided.

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
| `extract.asr.backend` | `transcribe/__init__.py:create_transcriber()` | choose primary ASR backend (`remote` / `groq`) |
| `extract.asr.fallback_backend` | `transcribe/__init__.py:create_fallback_transcriber()` | choose optional fallback ASR backend (must differ from primary); current pipeline only uses it for Groq daily-quota remainder fallback |
| `extract.asr.endpoint` | `transcribe/remote.py:RemoteTranscriber` | remote ASR endpoint or `ASR_ENDPOINT` env override (primary/fallback when backend is `remote`) |
| `extract.asr.healthcheck_path` | `transcribe/remote.py:RemoteTranscriber` | ASR health endpoint (default `/health`) |
| `extract.asr.healthcheck_timeout_seconds` | `transcribe/remote.py:RemoteTranscriber` | timeout for ASR health checks |
| `extract.asr.restart_before_transcribe` | `transcribe/remote.py:RemoteTranscriber` | restart ASR once before first transcription call |
| `extract.asr.restart_on_unhealthy` | `transcribe/remote.py:RemoteTranscriber` | restart ASR only when health check fails |
| `extract.asr.restart_command` | `transcribe/remote.py:RemoteTranscriber` | shell command to restart remote ASR service |
| `extract.asr.restart_readiness_timeout_seconds` | `transcribe/remote.py:RemoteTranscriber` | max wait time for ASR to become healthy after restart |
| `extract.asr.restart_readiness_interval_seconds` | `transcribe/remote.py:RemoteTranscriber` | polling interval for post-restart health checks |
| `extract.asr.restart_grace_seconds` | `transcribe/remote.py:RemoteTranscriber` | fallback fixed wait when health endpoint is unavailable |
| `extract.asr.groq.api_key` | `transcribe/__init__.py:_create_groq_transcriber()` | Groq API key (or `GROQ_API_KEY` env override) |
| `extract.asr.groq.model` | `transcribe/groq.py:GroqTranscriber` | Groq transcription model name |
| `extract.asr.groq.max_upload_bytes` | `transcribe/groq.py:GroqTranscriber` + `pipeline.py` audio chunking helpers | max bytes per Groq upload; drives chunk/sub-chunk split behavior |
| `extract.asr.groq.endpoint` | `transcribe/groq.py:GroqTranscriber` | Groq OpenAI-compatible transcription endpoint |
| `extract.asr.groq.timeout_seconds` | `transcribe/groq.py:GroqTranscriber` | HTTP timeout for Groq transcription requests |
| `output.mode` | `pipeline.py:_resolve_output_mode()` | `summary` or `full` output behavior |
| `output.note_mode` | `pipeline.py:_resolve_note_mode()` | explicit override when set; otherwise defaults to `source_ab_bundle` for Obsidian and `single` for other backends |
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
- uses configured `output.note_mode`; because agent runtime forces Obsidian, its effective default is `source_ab_bundle`
- sets `model.summarize_model`, `model.translate_model`, `model.review_model` from `agent.yaml`
- sets `model.reasoning_effort` from `agent.yaml`
- sets optional `model._runtime.codex_profile` from `agent.yaml`
- sets `model._runtime.codex_workdir = <agent_home>`
- sets `storage.obsidian.*` from `agent.yaml`
- sets `workspace.base_dir` from `agent.yaml`
- preserves runtime `config.yaml` values outside that override set, especially `extract.asr.*` (including `backend`, `fallback_backend`, and `groq.*`)

This is how the agent reuses current ASR self-healing behavior without exposing those knobs in the minimal runtime config.

Config load path: `config.py:load_config()` → read YAML → deep-merge with defaults → validate backend values → return `AppConfig`.
ASR operations runbook: `docs/operations/asr-service.md`.

## Factory Functions

Backends are selected by explicit `if/elif` factories, not registries:

| Factory | Location | Config field | Current implementations |
|---|---|---|---|
| `create_summarizer(config)` | `models/__init__.py` | `model.backend` | `claude_code`, `anthropic_api`, `codex_cli`, `openai_api` alias |
| `create_storage(config)` | `storage/__init__.py` | `storage.backend` | `notion`, `obsidian` |
| `create_transcriber(config)` | `transcribe/__init__.py` | `extract.asr.backend` | `remote`, `groq` |
| `create_fallback_transcriber(config)` | `transcribe/__init__.py` | `extract.asr.fallback_backend` | optional `remote` / `groq` fallback transcriber |
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
| `summarize_reviewed.md` | summarizer | short ASR review+summary (chapters) | none |
| `summarize_reviewed_freeform.md` | summarizer | short ASR review+summary (freeform) | none |
| `summarize_chunk.md` | summarizer map phase | long-form chunk summary | `{segment_title}`, `{start_time}`, `{end_time}`, `{segment_index}`, `{total_segments}` |
| `chinese.md` | summarizer reduce phase | Chinese synthesis | none |
| `synthesize.md` | summarizer final synthesis | output polishing | `{title}`, `{channel}`, `{duration}`, `{url}` |
| `compose_guide.md` | `Summarizer.compose_guide_note()` | A note / 导读版 tagged output: `<note_json>` metadata + `<note_markdown>` body | user payload contains `source`, `transcript`, `target_chars` |
| `compose_longform.md` | `Summarizer.compose_longform_note()` | B note / 扩展成稿 tagged output: `<note_json>` metadata + `<note_markdown>` body | user payload contains `source`, `guide_note`, `transcript`, `target_chars` |
| `compose_note_metadata.md` | `Summarizer.compose_note_metadata()` | source-note metadata strict JSON output | user payload contains `source`, `guide_note`, `longform_note` |
| `synthesize_reading_guide.md` | `prompt_experiments.py` | experimental long-form reduce variant: reading guide | `{title}`, `{channel}`, `{duration}`, `{url}` |
| `synthesize_guided_notes.md` | `prompt_experiments.py` | experimental long-form reduce variant: guided notes | `{title}`, `{channel}`, `{duration}`, `{url}` |
| `summarize_long_direct_evidence.md` | `prompt_experiments.py` via `Summarizer.summarize_transcript_to_markdown()` | experimental long-form direct-from-transcript variant with evidence anchors | none |

Experimental helper:
- `src/yt2notion/prompt_experiments.py` supports two experimental paths on an existing long-form workspace:
  - reuse map-phase chunk summaries and run alternate reduce prompts for side-by-side comparison
  - bypass map-reduce and feed the transcript artifacts directly into an experimental final-markdown prompt with evidence anchors
- These experiments do not change the canonical pipeline default, which still binds long-form reduce to `synthesize.md`.

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
pipeline.py -> extract.py, process.py, workspace.py, note_bundle.py,
               chapter_extract.py, segment.py, topic_segment.py, review.py, entity_extract.py,
               models/__init__.py, storage/__init__.py, transcribe/__init__.py
note_bundle.py -> models/base.py, process.py
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
