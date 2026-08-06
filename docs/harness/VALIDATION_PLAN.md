# VALIDATION_PLAN

Status: accepted

## Validation Mode

Selected modes: strict-tdd + contract-test + trace-review + live smoke-test.

Reason: this change repairs deterministic routing bugs, removes public result
types, and must prove a real latency improvement without relying only on mocks.

Commands:

```bash
env -u ANTHROPIC_API_KEY uv run --extra dev pytest tests/ -q
uv run --extra dev ruff check src/yt2notion tests
uv run --extra dev ruff format --check src/yt2notion tests
git diff --check
uv run yt2notion --help
uv run yt2notion transcribe "<playlist lesson 3 URL>" --no-video --json --verbose
```

Pass criteria:

- zero test, lint, format, or diff-check failures;
- targeted tests fail before the repair and pass afterward;
- lesson 3 completes without video/audio download, ASR, or ASR restart when
  manual captions are available;
- live-run stage timings and artifact counts are recorded;
- no Obsidian publication occurs.

Known gap: live YouTube latency varies and is reported as observed evidence,
not a deterministic unit-test threshold.
