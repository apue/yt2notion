---
name: youtube2notion
description: Prepare or publish a source/A/B media note bundle
---

Read `AGENTS.md` and `handoff.md`, then use the repository CLI:

```bash
# Default: inspect local JSON without publishing
uv run yt2notion prepare "$ARGUMENTS"

# Only after the user explicitly requests publishing
uv run yt2notion process "$ARGUMENTS"
```

Do not re-summarize the transcript or publish implicitly. The command output
and workspace artifacts are the source of truth.
