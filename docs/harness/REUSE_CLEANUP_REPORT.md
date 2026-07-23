# REUSE_CLEANUP_REPORT

Status: accepted

## Existing Capabilities

- `transcribe/base.py`: retain and strengthen the existing `Transcriber` Protocol.
- `transcribe/groq.py`, `transcribe/remote.py`: reuse as provider Adapters.
- `transcribe/__init__.py`: extend factories and return Protocol types instead of `Any`.
- `pipeline.py` ASR cluster: refactor/move into `TranscriptionEngine`; preserve tested semantics.
- `workspace.py`: reuse artifact persistence and checkpoint contract; do not create a parallel store.
- `extract.py`: reuse provider implementation under the initial MediaSource Adapter.
- `segment.py`, `topic_segment.py`, `review.py`, `note_bundle.py`: retain cohesive behavior and call from application use cases.

## Extension Points

- `config.yaml` backend fields and explicit factories remain the composition mechanism.
- `Transcriber` is the provider Seam for Groq/remote/future ElevenLabs.
- New `MediaSource` is the provider Seam for yt-dlp/future acquisition modes.

## Deprecated or Removable Logic

- `media_transcribe.py` direct imports of pipeline private functions: remove once application/engine are wired.
- `pipeline.py` ASR private-function cluster: move, then delete from pipeline.
- Repeated raw-config assembly and primary/fallback Adapter construction: centralize in composition root/engine.
- `extract_cmd.py`: retain as legacy compatibility until callers are verified; do not expand it.
- Private-helper tests that duplicate new Interface contracts: delete only after equivalent contract coverage exists.

## Search Evidence

- `rg`/`sg` searches for extract functions, `_transcribe_from_audio`, factories, and use-case callers.
- `PROJECT_MAP.md` pipeline, artifact, factory, and dependency maps.
- Recent history showing pipeline/workspace/config as active hot spots.

## Decision

- Reuse: Workspace artifacts, provider Adapters, segment/review/note composition.
- Extend: typed provider factories and Transcriber result/outcome contract.
- New code: application Interface, MediaSource Protocol/Adapter, TranscriptionEngine.
- Refactor: pipeline and standalone orchestration into application use cases.
- Deprecate/delete: private cross-module calls and moved ASR cluster after coverage exists.

## Risks

- Avoid duplicating ASR logic during migration.
- Avoid adding provider options to the public use-case Interface.
- Preserve lazy fallback construction and existing quota semantics.
