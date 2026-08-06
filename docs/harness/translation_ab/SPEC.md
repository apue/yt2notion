# Translation A/B Experiment

## Goal

Compare two Chinese translation strategies on the same lesson source:

- whole-chapter translation;
- semantic-block translation with stable IDs.

The experiment must isolate that single variable, use the configured translation
model for both candidates, and produce a blind human-review document without
publishing anything.

## Non-goals

- Formula reconstruction or LaTeX enrichment.
- Automated winner selection.
- Obsidian publication.
- Compatibility with earlier ad-hoc translation artifacts.

## Acceptance criteria

1. One CLI command acquires/transcribes a URL and writes experiment artifacts to
   its workspace.
2. Both candidates use the same source, model role, core translation rules, and
   number of model calls.
3. Structured output is rejected unless chapter IDs or block IDs are complete,
   unique, and ordered exactly like the source contract.
4. The blind review alternates candidate positions with a deterministic balanced
   assignment and does not disclose strategy labels.
5. Length ratios are reported as diagnostics, not used as a quality threshold.
6. Unit tests use a fake LLM; a live fourth-lesson run is recorded separately.
7. A successful strategy is checkpointed against the source fingerprint, so a
   retry only regenerates a missing or invalid candidate.
