Process only the IDs listed in `owned_ids`. `visible_cues` includes read-only neighboring context.

For `translate_only`, copy each owned cue's `original_text` exactly into `source_text`; only translate.
For `correct_then_translate`, correct likely recognition errors using the global and local context, while
preserving meaning and spoken style, then put the correction in `source_text`.
For `repair_semantic_issues`, fix only the supplied concrete issues. Preserve an authoritative source cue
exactly when `source_kind` is `manual_subtitle`; otherwise keep corrections narrowly evidence-based.

Return a JSON array in exact `owned_ids` order. Each object must contain only:
- `id`
- `source_text`
- `translated_text`

Use natural, concise subtitles in the requested target language. Keep domain-specific English terms when
that is standard; never translate “Transformer” as an electrical transformer or fictional robot.

Input:
{source_json}
