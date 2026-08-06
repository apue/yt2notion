# PROBLEM_REVIEW

## 2026-08-06 Subtitle-first latency repair

Symptom: a captioned YouTube lesson requested for summary/translation took more
than 14 minutes and entered video download, remote ASR restart, and repeated
LLM timeouts.

Evidence:

- playlist-bearing metadata output caused `json.loads` to fail with `Extra data`;
- direct subtitle probing found a manual English track in seconds;
- transcript acquisition always called `extract_video`, even with `--no-video`;
- content acquisition already had a separate subtitle-first path;
- Claude CLI used a fixed 120-second timeout and retried timeouts three times.

Root cause: supported entry points use divergent acquisition pipelines and
their tool contracts do not encode single-video or bounded-latency behavior.

Repair depth: contract refactor plus regression tests. Delete the divergent
result/method hierarchy, reuse `transcribe_workspace`, select captions from the
metadata probe, and bound provider retries.

Validation: strict regression tests, full local checks, merge-base review, and
a live next-lesson trace with no publication.
