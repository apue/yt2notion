# Project Map

`PROJECT_MAP.md` is the canonical source for pipeline order, branches,
artifacts, configuration bindings, and extension seams.

## Entry points

| Command | Use case |
|---|---|
| `yt2notion process URL` | prepare and publish an Obsidian bundle |
| `yt2notion prepare URL` | prepare a bundle and emit JSON without publishing |
| `yt2notion transcribe URL` | acquire preferred subtitles or media, transcribe, and stop |
| `yt2notion translation-experiment URL` | create a local blind whole-chapter vs semantic-block translation experiment |

All commands enter through `application.Yt2Notion`. There is no compatibility
pipeline or local queue runtime.

## Canonical pipeline

1. `DOWNLOAD`: `MediaSource.acquire()` probes once, selects the preferred
   available subtitle, and downloads media only when no transcript source is
   available. `keep_video=false` downloads audio directly on media fallback.
2. `SEGMENT`: author chapters, description timestamps, or no pre-segmentation.
3. `TRANSCRIBE`: subtitles are assigned locally; audio uses
   `TranscriptionEngine`.
4. `TOPIC SEGMENT`: ASR-like transcripts may be regrouped by topic.
5. `REVIEW`: manual subtitles skip cleanup; automatic/webpage/ASR sources are
   cleaned.
6. `SUMMARIZE`: `NoteComposer` builds guide, longform, and shared metadata,
   producing one `NoteBundle`.
7. `PUBLISH`: only explicit `process` writes the source/A/B bundle through
   `ObsidianStorage`.

`transcribe` stops after step 3. `prepare` stops after step 6.
`translation-experiment` reuses `transcribe`, then makes one batched translation
call per strategy and writes only local experiment artifacts. It never reaches
storage or `PUBLISH`.

## Transcription state

`TranscriptionEngine` owns audio planning, upload-size subdivision, checkpoint
reconciliation, hourly waiting, daily fallback, and backend attribution.

- Groq hourly quota: persist the retry time and retry the same chunk.
- Groq daily quota: switch the failed and remaining pending chunks to
  `extract.asr.fallback_backend`.
- A compatible resume reuses completed chunk payloads.
- A fresh run from an earlier step discards transcription checkpoints.
- Non-quota request errors fail without fallback.

## Workspace artifacts

| Artifact | Contract |
|---|---|
| `metadata.json` | serialized `VideoMeta`, including manual/automatic subtitle languages |
| `segments.json` | `list[{title,start_seconds,end_seconds,?parent_title}]` |
| `transcribe_plan.json` | chunk identity, time range, audio path, preferred backend |
| `transcribe_state.json` | job status, retry/fallback state, per-chunk status |
| `transcribe_chunks/<id>.json` | completed chunk transcript entries |
| `transcripts.json` | `list[{title,start_seconds,end_seconds,text,source}]` |
| `reviewed.json` | cleaned transcript shape, when review runs |
| `note_bundle.json` | source, guide, longform, stable tags, source topics |
| `failed.json` | failed step, error type/message, retry exhaustion, timestamp |
| `transcript.md` | readable output of standalone `transcribe` |

Optional side artifacts include `subtitles.srt|vtt`, `video.*`, `audio.mp3`,
`segments/*.mp3`, and `full_audio_chunks/*.mp3`.

`translation_experiment/` contains `source.json`, the two strategy candidates,
`manifest.json` diagnostics, `evaluation.json`, `blind_review.md`, and a separate
`answer_key.json`.
The response contract requires exact ordered chapter/block IDs. Translation
length ratios are diagnostic only. Explicitly named mathematical symbols are
normalized faithfully, while formula reconstruction and LaTeX enrichment remain
disabled so they do not confound the strategy comparison.
Each candidate is checkpointed immediately and is reused only when schema,
source fingerprint, strategy, model identity, prompt fingerprint, and ordered
IDs all match. Codex model identity includes reasoning effort. Final Chinese text
is the primary evaluation target: `evaluation.json` records deterministic
coverage, internal-ID leakage, and notation expectations supported by explicit
source cues. A separate non-blocking style diagnostic reports written-Chinese
editing, Arabic-number typography, direct symbol presentation, contextual
coin-outcome localization, and bilingual first-use terminology. Intermediate
artifacts are diagnostic and receive no subjective aggregate score; the blinded
human comparison decides the winner.

## Configuration bindings

| Field | Consumer |
|---|---|
| `model.backend` | `model_policy.resolve_model_config` → `models.llm.create_llm_caller`; default `codex_cli` |
| `model.translate_model` | guide/longform/metadata composition |
| `model.review_model` | transcript cleanup and topic segmentation |
| `model.reasoning_effort` | Codex CLI adapter |
| `model.timeout_seconds` | LLM provider request/subprocess timeout |
| `model.max_attempts` | bounded LLM provider attempt count |
| `storage.backend` | only `obsidian` is valid |
| `storage.obsidian.vault_path` | `ObsidianStorage` |
| `storage.obsidian.summaries_dir` | bundle destination |
| `extract.media_source.backend` | `create_media_source`; currently `yt_dlp` |
| `extract.asr.backend` | primary `Transcriber`: `groq` or `remote` |
| `extract.asr.fallback_backend` | optional different fallback transcriber |
| `extract.asr.groq.*` | Groq key, model, endpoint, timeout, upload budget |
| `extract.asr.endpoint` and restart fields | remote ASR adapter |
| `output.mode` | must be `summary` |
| `output.max_segment_seconds` | segmentation/topic threshold |
| `output.long_content_threshold_seconds` | long-content classification |
| `workspace.base_dir` | workspace root |

Standalone `transcribe` resolves explicit config, then
`~/.yt2notion-agent/config.yaml`, then local `config.yaml`.
Its JSON result includes per-stage `acquire`, `segment`, `transcribe`, and total
elapsed seconds. Captioned inputs do not initialize a `Transcriber` adapter.

## Interfaces and adapters

| Interface | Factory | Adapters |
|---|---|---|
| `MediaSource` | `create_media_source` | `YtDlpMediaSource` |
| `Transcriber` | `create_transcriber` | `GroqTranscriber`, `RemoteTranscriber` |
| `LLMCaller` | `create_llm_caller` | Claude CLI, Codex CLI, Anthropic API |
| `Storage` | `create_storage` | `ObsidianStorage` |

`NoteComposer` is provider-independent and owns prompt payloads and parsing.
`TranscriptionEngine` is provider-independent and owns ASR lifecycle.
`TranslationExperimentRunner` depends on `LLMCaller`, typed canonical transcripts,
and experiment artifact functions; `application.Yt2Notion` is its only CLI-facing
orchestrator. It has no dependency on `Storage`.

To add an adapter, implement the relevant Protocol, extend its explicit
factory and valid backend set, then add adapter contract tests. Do not add a
registry or expose provider details through `Yt2Notion`.

## Prompt bindings

| Template | Caller |
|---|---|
| `review.md` | `review.py` |
| `topic_segment.md` | `topic_segment.py` |
| `compose_guide.md` | `NoteComposer.compose_guide_note` |
| `compose_longform.md` | `NoteComposer.compose_longform_note` |
| `compose_note_metadata.md` | `NoteComposer.compose_note_metadata` |
| `translation_experiment_system.md` | shared translation A/B rules |
| `translation_experiment_whole.md` | whole-chapter experiment strategy |
| `translation_experiment_blocks.md` | semantic-block experiment strategy |

Prompt templates are structural inputs and must not be reformatted as ordinary
documentation.

## Dependency direction

```text
cli -> application
application -> media_source, TranscriptionEngine, ContentPreparation, Storage
ContentPreparation -> review, topic_segment, note_bundle
note_bundle -> Summarizer
Summarizer implementation -> NoteComposer -> LLMCaller adapters
TranscriptionEngine -> Transcriber adapters, Workspace
Storage -> ObsidianStorage
```
