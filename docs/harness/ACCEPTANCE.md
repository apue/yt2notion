# ACCEPTANCE

Status: accepted

## Done Definition

- `yt2notion --help` exposes only `process`, `prepare`, and `transcribe`.
- No production or test import references `pipeline`, `agent_runtime`,
  `agent_worker`, `extract_cmd`, `NotionStorage`, or `ChineseContent`.
- Storage exposes only `save_note_bundle`.
- Note composition is tested once through its public interface; provider tests
  cover only invocation, retry, configuration, and error translation.
- Workspace and ASR checkpoint/quota regression tests remain.
- `PROJECT_MAP.md`, README, configuration examples, and `handoff.md` describe
  the reduced surface.
- Full local pytest and Ruff validation pass without remote calls.
