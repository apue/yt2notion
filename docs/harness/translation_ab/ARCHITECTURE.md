# Architecture

`Yt2Notion.translation_experiment()` reuses the existing subtitle-first
`transcribe()` use case, then delegates to `TranslationExperimentRunner`.

The experiment package has four seams:

- `source.py`: typed source contract and deterministic semantic grouping;
- `generator.py`: two prompt strategies and strict ID-based response parsing;
- `artifacts.py`: deterministic metrics, balanced blinding, and file rendering;
- `quality.py`: objective gates over final chapter-level text using only explicit
  source evidence and artifact contracts;
- `service.py`: orchestration and timing.

The existing `LLMCaller` Protocol and `model.translate_model` factory binding are
reused. The command has no storage dependency and therefore cannot publish.
Each successful strategy is persisted immediately with its source SHA-256,
strategy, model identity (backend, model, and reasoning effort), prompt SHA-256,
and exact ordered IDs. A later run reuses it only when every identity field and
the output contract match.

`evaluation.json` makes final text the primary target. Human pairwise review
decides the winner. Intermediate source/block artifacts are retained for
deterministic coverage and diagnosis but do not contribute a subjective score.
