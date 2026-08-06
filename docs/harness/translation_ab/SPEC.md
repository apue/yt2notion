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
4. Final Chinese text is the primary evaluation target. Intermediate artifacts
   receive deterministic contract diagnostics, not subjective aggregate scores.
5. Explicit source evidence for mathematical notation must survive into final
   text; for example, `big omega` and `little omega` require `Ω` and `ω`.
6. The blind review alternates candidate positions with a deterministic balanced
   assignment and does not disclose strategy labels.
7. Length ratios are reported as diagnostics, not used as a quality threshold.
8. Unit tests use a fake LLM; a live fourth-lesson run is recorded separately.
9. A successful strategy is checkpointed against the source, strategy, model,
   prompt fingerprint, and ordered IDs, so a retry only regenerates a missing
   or genuinely stale candidate.
