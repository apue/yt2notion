# REUSE_INDEX

Status: accepted

## Reusable Capabilities

- Capability: ASR provider adapters and normalized quota errors
  - Path: `src/yt2notion/transcribe/`
  - How to reuse: inject adapters through the existing `Transcriber` Protocol and typed factories.
  - Tests: `tests/test_transcribe_groq.py`, `tests/test_transcribe_remote.py`
- Capability: Workspace artifacts and transcription checkpoint persistence
  - Path: `src/yt2notion/workspace.py`
  - How to reuse: pass the current Workspace into `TranscriptionEngine`; keep existing filenames and JSON shapes.
  - Tests: `tests/test_workspace.py`
- Capability: yt-dlp metadata/subtitle/media extraction
  - Path: `src/yt2notion/extract.py`
  - How to reuse: compose the functions behind the initial high-level MediaSource adapter.
  - Tests: `tests/test_extract.py`
- Capability: content preparation
  - Path: `src/yt2notion/segment.py`, `topic_segment.py`, `review.py`, `note_bundle.py`
  - How to reuse: call existing cohesive functions from explicit application use cases.
  - Tests: corresponding `tests/test_*.py` modules and `tests/test_pipeline.py`

## Extension Points

- Extension point: transcription providers
  - Path: `src/yt2notion/transcribe/base.py`, `src/yt2notion/transcribe/__init__.py`
  - Contract: `Transcriber` Protocol plus explicit config-selected factory.
- Extension point: media acquisition providers
  - Path: new `src/yt2notion/media_source/`
  - Contract: one high-level `MediaSource.acquire` Protocol operation plus explicit factory.
- Extension point: application use cases
  - Path: new `src/yt2notion/application.py`
  - Contract: typed `Yt2Notion.prepare`, `process`, and `transcribe` methods.

## Avoid Parallel Implementations

- Existing capability: audio chunk/checkpoint/quota lifecycle
  - Prefer: move the tested behavior into one `TranscriptionEngine` deep Module.
  - Avoid: a second standalone implementation or generic workflow nodes.
- Existing capability: artifact persistence
  - Prefer: the existing Workspace methods and contracts.
  - Avoid: a parallel repository/state-store abstraction in this refactor.
- Existing capability: provider construction
  - Prefer: explicit typed factories at the composition root.
  - Avoid: registries, string imports, or URL-based auto-routing.

## Generated Candidates

The `refresh_reuse_index.py` script may append candidate files below.

<!-- generated-reuse-index:start -->
## Generated Reuse Candidates

- `docs/operations/asr-service.md`
- `src/yt2notion/models/_parsers.py`
<!-- generated-reuse-index:end -->
