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
| `yt2notion subtitle-pack URL` | create a local, cue-timed bilingual subtitle package for browser playback |

All commands enter through `application.Yt2Notion`, which assembles dependencies
and invokes ordinary typed functions exported by the `pipelines` package. Product
ownership is explicit: `contracts.py` owns results/progress,
`transcribe.py` owns transcription, `notes.py` owns prepare/process,
`translation_experiment.py` and `subtitle_pack.py` own their complete specialized
flows, and `shared.py` contains only workspace-root resolution. There is no
compatibility pipeline, DAG engine, workflow registry, or local queue runtime.
Pipeline functions expose explicit typed Python parameters rather than request
wrapper objects.

## Canonical pipeline

1. `DOWNLOAD`: the composition root supplies the single configured source
   provider; `SourceProvider.probe(locator)` observes metadata/capabilities once;
   `plan_acquisition()` creates a deterministic subtitle/webpage/audio/video
   operation tuple; acquisition executes that policy in a concrete `Workspace`.
   `keep_video=false` plans direct audio fallback. Authentication and
   local-resource errors stop the plan instead of being treated as missing
   subtitles.
2. `SEGMENT`: author chapters, description timestamps, or no pre-segmentation,
   represented as `SegmentSpec` values.
3. `TRANSCRIBE`: subtitles are assigned locally; audio uses
   `TranscriptionEngine`; both return validated `TranscriptSegment` values.
4. `TOPIC SEGMENT`: ASR-like transcripts may be regrouped by topic.
5. `REVIEW`: manual subtitles skip cleanup; automatic/webpage/ASR sources are
   cleaned.
6. `SUMMARIZE`: `NoteComposer` builds guide, longform, and shared metadata,
   producing one `NoteBundle`.
7. `PUBLISH`: only explicit `process` writes the source/A/B bundle through
   `ObsidianStorage`.

`run_transcribe_pipeline()` stops after step 3. `run_note_pipeline()` stops after
step 6. `run_process_pipeline()` reuses the note pipeline under the same run
profile and is the only pipeline that receives a storage factory. The
translation-experiment and subtitle-pack pipelines each own their complete
transcribe-then-specialized-stage composition and cannot reach storage.
`translation-experiment` reuses `transcribe`, then makes one batched translation
call per strategy and writes only local experiment artifacts. It never reaches
storage or `PUBLISH`.

`subtitle-pack` reuses subtitle-first acquisition and transcription, but reads
`subtitles.srt|vtt` directly when available so cue timing is not collapsed into
chapter transcripts. Manual subtitles are translated without rewriting the
source text. Automatic captions and ASR-derived cues are contextually corrected
before translation. The use case builds context from source metadata and the
complete transcript, processes long inputs in bounded batches with read-only
overlap, validates exact ordered cue coverage, and writes only local artifacts.
It never reaches storage or `PUBLISH`.

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
| `segments.json` | `list[{title,start_seconds,end_seconds,?parent_title}]`, encoded from ordered `SegmentSpec` values |
| `transcribe_plan.json` | chunk identity, time range, audio path, preferred backend |
| `transcribe_state.json` | job status, retry/fallback state, per-chunk status |
| `transcribe_chunks/<id>.json` | completed chunk transcript entries |
| `transcripts.json` | `list[{title,start_seconds,end_seconds,text,source}]`, encoded from ordered `TranscriptSegment` values |
| `reviewed.json` | the same transcript-segment schema after cleanup |
| `note_bundle.json` | source, guide, longform, stable tags, source topics |
| `failed.json` | failed step, error type/message, retry exhaustion, timestamp |
| `transcript.md` | readable output of standalone `transcribe` |
| `subtitle_context.json` | bounded global context plus per-section evidence used by subtitle calls |
| `source_cues.json` | canonical ordered cue timeline before LLM processing |
| `reviewed_cues.json` | corrected source cues for automatic-caption or ASR inputs |
| `bilingual_subtitles.json` | stable schema-v1 browser-extension input with original, source, and translated text |
| `bilingual_subtitles.srt` | readable bilingual export generated from the stable JSON package |
| `subtitle_quality_report.json` | deterministic coverage/timeline validation and semantic QA findings |
| `profiles/<run-id>.json` | schema-v2 product-run node/provider/attempt/checkpoint timing and status without content or secrets |

Optional side artifacts include `subtitles.srt|vtt`, `video.*`, `audio.mp3`,
`segments/*.mp3`, and `full_audio_chunks/*.mp3`.

`domain.py` owns the two shared domain values actually passed by the core flows:
`SegmentSpec` and immutable `TranscriptSegment`. `artifact_codecs.py` is the only
JSON boundary for segment/transcript artifacts and rejects invalid ingress before
domain objects enter a pipeline. Cue-level playback evidence is owned by the
subtitle-package contract (`SourceCue`) rather than a speculative shared type.
`transcribe/contracts.py` similarly owns typed resumable-ASR plans, state, and
chunk entries plus their unchanged JSON codecs; `Workspace` exposes only these
typed values to the core pipeline.

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
| `extract.media_source.backend` | `create_source_provider`; currently `yt_dlp` |
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

`subtitle-pack` uses `output.target_language` and the existing translation model
role. Its generation batch character budget is an internal 8,000-character
default, kept below the larger quality-check budget to fit the existing provider
timeout without raising the timeout globally. Generation checkpoint identity
includes the batch budget and overlap policy; context and generation checkpoints
are reusable only when their schema, source/context fingerprint, model identity,
prompt fingerprint, operation, ordered cue IDs, and relevant batching policy all
match.

## Interfaces and adapters

| Interface | Factory | Adapters |
|---|---|---|
| `SourceProvider` | `create_source_provider` | `YtDlpSourceProvider` |
| `Transcriber` | `create_transcriber` | `GroqTranscriber`, `RemoteTranscriber` |
| `LLMCaller` | `create_llm_caller` | Claude CLI, Codex CLI, Anthropic API |
| `Storage` | `create_storage` | `ObsidianStorage` |

`SourceProbe` and `OperationResult` are the provider-neutral typed acquisition
contracts. The pure planner returns an ordered tuple of `SourceOperation` values
from the probe and `keep_video`; acquisition owns routing/configuration,
deterministic fallback, and the concrete `Workspace` lifecycle.
`YtDlpSourceProvider` owns yt-dlp operations, cookies, normalized operation
failures, and materializing exactly one requested operation into the supplied
workspace. This concrete workspace boundary is intentional for this repository,
not a temporary storage abstraction.

`NoteComposer` is provider-independent and owns prompt payloads and parsing.
`TranscriptionEngine` is provider-independent and owns ASR lifecycle.
`TranslationExperimentRunner` depends on `LLMCaller`, typed canonical transcripts,
and experiment artifact functions; `run_translation_experiment_pipeline()` is its
CLI-facing orchestrator. It has no dependency on `Storage`.
`SubtitlePackService` delegates cue recovery
to `subtitle_pack.source`, bounded context/generation/QA calls to
`SubtitleLLMWorkflow`, deterministic model-output checks to
`subtitle_pack.validation`, shared checkpoint serialization to
`runtime.checkpoint`, and
package serialization to `subtitle_pack.artifacts`. The workflow depends on
`LLMCaller` and `RuntimeObserver`. `run_subtitle_pack_pipeline()` owns acquisition,
transcription, and service invocation as one profiled product run. The browser extension consumes only
`bilingual_subtitles.json`; it does not call an LLM or local companion service.

To add an adapter, implement the relevant Protocol, extend its explicit
factory and valid backend set, then add adapter contract tests. Do not add a
registry or expose provider details through `Yt2Notion`.

The `runtime` package keeps observation/context/provider calls in `observer.py`;
pipelines create node spans directly and `checkpoint.py` owns identity-bound JSON
checkpoint persistence. Typed retry policy remains operation-local in `retry.py`.
The observer models nested run/node/batch/provider-call/attempt/checkpoint
observations and stores only redacted labels, counts, status, timing, and
normalized failure categories. Whole-node retry is disabled by default;
provider retry remains operation-local, and business fallback remains in the
pipeline/acquisition plan. Every product pipeline writes schema version 2's flat
nested observation stream and finishes it on success, failure, or interruption;
subtitle checkpoint envelopes and translation candidate checkpoint schemas remain
unchanged while using the shared store.

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
| `subtitle_context.md` | derive bounded domain, course, people, topic, and terminology context |
| `subtitle_generate.md` | manual-source translation or automatic/ASR correction plus translation |
| `subtitle_quality.md` | compact semantic QA over generated bilingual cues |

Prompt templates are structural inputs and must not be reformatted as ordinary
documentation.

## Dependency direction

```text
cli -> application
application -> complete product pipelines and dependency factories
pipelines package -> acquisition planner/provider, TranscriptionEngine, ContentPreparation
run_process_pipeline -> run_note_pipeline result, then Storage
ContentPreparation -> review, topic_segment, note_bundle
note_bundle -> Summarizer
Summarizer implementation -> NoteComposer -> LLMCaller adapters
transcribe composition factory -> TranscriptionEngine + lazy Transcriber adapter factories
TranscriptionEngine -> Transcriber Protocol, Workspace
Storage -> ObsidianStorage
subtitle-pack pipeline -> run-owned RuntimeObserver -> SubtitlePackService
SubtitlePackService -> subtitle source, SubtitleLLMWorkflow, validation, artifacts
SubtitleLLMWorkflow -> LLMCaller, RuntimeObserver, CheckpointStore
browser-extension -> bilingual_subtitles.json
```
