# Decisions

## One batched call per strategy

Each strategy receives the full lesson in one call. This keeps call count equal,
reduces latency, and prevents call-count variance from contaminating the result.

## IDs are transport metadata

IDs exist only in structured prompts and artifacts. The blind review displays
normalized prose, so IDs do not appear in the translated text being judged.

## Formula enrichment is disabled

Spoken-formula reconstruction changes the task and could hide the effect of
semantic blocking. It should be evaluated later as an independent factor with
evidence and confidence fields.

## Human judgment is pairwise

The experiment does not use the producing model as the judge. The reviewer may
choose A, B, or tie and optionally score fidelity, fluency, terminology, and
learning value.
