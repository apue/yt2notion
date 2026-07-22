# CODEBASE_MAP

Status: accepted

## Overview

`yt2notion` is a Python CLI application. `src/yt2notion` contains explicit
pipeline/use-case code, provider adapters, filesystem artifacts, and CLI/agent
entry points. `PROJECT_MAP.md` is the canonical map for pipeline ordering,
artifact contracts, configuration, and extension points.

## Key Directories

- `src/yt2notion/`: production package.
- `src/yt2notion/transcribe/`: ASR provider adapters and normalized errors.
- `src/yt2notion/models/`: LLM/model provider adapters.
- `src/yt2notion/storage/`: publisher/storage provider adapters.
- `tests/`: unit, contract, and pipeline regression tests.
- `docs/`: operations, architecture, and task-specific design documents.
- `workspace/`: generated local artifacts and samples; not production code.

## Entry Points

- `src/yt2notion/cli.py`: Typer CLI for `prepare`, `process`, `transcribe`, and agent operations.
- `src/yt2notion/pipeline.py`: current preparation/process implementation and future compatibility facade.
- `src/yt2notion/media_transcribe.py`: current transcript-only implementation and future rendering facade.
- `src/yt2notion/agent_worker.py`: queued-job caller.
- `src/yt2notion/config.py`: validated application configuration.

## Tests

- `tests/test_pipeline.py`: preparation/process orchestration and ASR regression coverage.
- `tests/test_media_transcribe.py`: transcript-only behavior and artifact rendering.
- `tests/test_transcribe_*.py`: provider behavior and quota normalization.
- `tests/test_cli.py`: CLI routing and result compatibility.
- `tests/test_workspace.py`: artifact/checkpoint persistence contracts.

## Generated Section

The `refresh_reuse_index.py` script may append or update summary content below.

<!-- generated-codebase-map:start -->
## Generated Codebase Summary

- File count: 191

### Top Directories
- `workspace`: 47 files
- `src`: 39 files
- `tests`: 32 files
- `docs`: 28 files
- `.`: 16 files
- `.ruff_cache`: 10 files
- `.claude`: 6 files
- `.pytest_cache`: 5 files
- `.agents`: 3 files
- `.codex`: 2 files
- `.gemini`: 1 files
- `.github`: 1 files
- `scripts`: 1 files

### File Types
- `.py`: 64
- `.md`: 52
- `.json`: 26
- `.mp3`: 18
- `<none>`: 17
- `.toml`: 3
- `.yaml`: 2
- `.TAG`: 2
- `.part`: 2
- `.lock`: 1
- `.m4a`: 1
- `.mp4`: 1
- `.ytdl`: 1
- `.sh`: 1
<!-- generated-codebase-map:end -->
