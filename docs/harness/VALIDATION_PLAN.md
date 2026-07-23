# VALIDATION_PLAN

Status: accepted

## Validation Mode

Selected modes: regression-test + contract-test + review.

Commands:

```bash
env -u ANTHROPIC_API_KEY uv run --extra dev pytest tests/ -q
uv run --extra dev ruff check src/yt2notion tests
uv run --extra dev ruff format --check src/yt2notion tests
uv run yt2notion --help
```

Pass criteria:

- zero test or lint failures;
- help exposes only the three supported commands;
- repository search finds none of the deleted surfaces;
- no remote ASR, LLM, or storage calls.
