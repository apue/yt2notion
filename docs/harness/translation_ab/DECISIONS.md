# Decisions

## One batched call per strategy

Each strategy receives the full lesson in one call. This keeps call count equal,
reduces latency, and prevents call-count variance from contaminating the result.

## IDs are transport metadata

IDs exist only in structured prompts and artifacts. The blind review displays
normalized prose, so IDs do not appear in the translated text being judged.

## Faithful notation is part of translation

Recovering a symbol explicitly named by the speaker is not speculative formula
enrichment. `big omega` and `little omega` must become `Ω` and `ω`. Formula
reconstruction and LaTeX enrichment remain outside this experiment; spoken
relationships stay verbal rather than being guessed or reformatted.

## Final text is the primary evaluation target

The human winner decision compares final Chinese prose. Intermediate artifacts
receive only deterministic coverage, ordering, traceability, and explicit
notation-evidence checks. Their metrics are diagnostic and are not added to the
human final-text score.

## Human judgment is pairwise

The experiment does not use the producing model as the judge. The reviewer may
choose A, B, or tie and optionally score fidelity, fluency, terminology, and
learning value.

## Human style feedback becomes shared policy

Strategy labels do not explain preferences that recur across both candidates.
Concise written Chinese, Arabic numerals for mathematical quantities, direct
symbol presentation, contextual H/T localization, and bilingual first-use
terminology therefore belong to the shared prompt. High-confidence patterns are
reported by a separate advisory evaluator; they are not auto-rewritten and do
not override fidelity or human judgment.
