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

The repair now defaults CLI LLM execution to one `120s` attempt and preserves
the provider error detail. Unit tests verify this bound. The remote provider was
not available for a successful end-to-end summary benchmark, so no summary
latency improvement is claimed.
