# LIVE VALIDATION

## 2026-08-06: Probability Bootcamp lesson 3

Input:

- Video: `5mDYZMwTAF8`
- Title: `Counting Probabilities with Combinatorics and the Factorial`
- Duration: `17:49`
- URL included the playlist `list` and `index=3` query parameters.

Command:

```bash
/usr/bin/time -p uv run yt2notion transcribe \
  "https://www.youtube.com/watch?v=5mDYZMwTAF8&list=PLMrJAkhIeNNR3sNYvfgiKgcStwuPSts9V&index=3" \
  --no-video --json --verbose
```

Observed result:

- exit code: `0`;
- wall time: `5.66s`;
- application timing: acquire `5.485s`, segment `0.000s`, transcribe
  `0.008s`, total `5.494s`;
- manual English subtitle entries: `343`;
- author-derived transcript segments: `8`;
- audio artifact: absent;
- video artifact: absent;
- transcript source: `manual_subtitle`;
- ASR/restart: not invoked.

Comparable baseline from lesson 2 trace:

- playlist metadata attempt: about `70s`, failed with multi-document JSON;
- normalized standalone transcription attempt: about `108s`, downloaded media
  and failed during remote ASR restart;
- comparable acquisition/transcription attempts: about `178s` and no result.

The repaired path is about `32.4x` faster for the comparable media/transcript
stage, a `96.9%` elapsed-time reduction, and changes the outcome from failure to
success.

An intermediate run that still loaded Chrome cookies took `12.351s`. Trying
public subtitle download first and using browser cookies only as an auth
fallback reduced the final run to `5.494s`.

## LLM smoke-test delta

The source/A/B `prepare` smoke test stopped after `180.91s` because the local
Claude CLI returned `API Error: Unable to connect to API (ConnectionRefused)`.
A minimal `Return exactly: ok` call reproduced the same provider failure after
about `175s`, proving it is not caused by transcript length.

The initial repair bounded every supported LLM backend to one `120s` attempt and
preserved CLI provider error detail. Unit tests verify the execution policy for
Claude CLI, Codex CLI, and Anthropic API construction. The remote Claude provider
was not available for a successful end-to-end summary benchmark.

## Codex-first summary validation

The repository default and active configuration now select `codex_cli` with
`gpt-5.4` for both review and note composition. Legacy Claude-model alias mapping
was removed instead of retained as a compatibility layer.

The first resumed `summarize` attempt proved that Codex routing worked, but the
second of three note-composition calls exceeded the initial per-call `120s`
bound. The command stopped after `234.55s` with one attempt and did not publish.

Based on that trace, the Codex-first default timeout was raised to `240s` while
keeping `max_attempts: 1`. Repeating the same resumed validation succeeded:

- command: `yt2notion prepare ... --resume workspace/5mDYZMwTAF8 --from summarize --verbose`;
- exit code: `0`;
- wall time: `135.65s`;
- generated artifacts: source note, Chinese guide, Chinese longform, stable tags,
  and source topics in `note_bundle.json`;
- bundle size: `20,123` bytes;
- Obsidian publication: not invoked.

The successful Codex summary run was `45.26s` shorter than the earlier Claude
connection failure (`180.91s`) while changing the result from failure to a full
bundle. Combining independently measured transcript (`5.494s`) and resumed
summary (`135.65s`) stages gives an indicative `141.14s` processing time, not a
single-command end-to-end benchmark.
