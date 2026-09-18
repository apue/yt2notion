Analyze the supplied video metadata and transcript evidence for subtitle translation.

Return one compact JSON object with these fields:
- `domain`: short domain description
- `course_or_series`: course, lecture, or series identity when supported
- `people`: array of supported names and roles
- `topics`: array of central topics
- `terminology`: array of objects with `term`, `preferred_rendering`, and `reason`
- `notes`: array of other high-confidence context facts useful for correcting speech recognition

Use the model's domain knowledge, but distinguish source-supported identities from guesses. Preserve
technical terms that are conventionally left in English. Do not return prose outside the JSON object.

Source:
{source_json}
