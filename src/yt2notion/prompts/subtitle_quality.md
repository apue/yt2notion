Audit the bilingual cues against the supplied context. Report only concrete semantic problems: a likely
incorrect proper name or technical term, source correction that changes meaning, mistranslation, or a
missing meaning-bearing phrase. Do not report style preferences.

Return a JSON array. Return `[]` when no concrete issue exists. Each issue object must contain only:
- `id`: one cue ID from the input
- `issue`: a concise explanation

Input:
{source_json}
