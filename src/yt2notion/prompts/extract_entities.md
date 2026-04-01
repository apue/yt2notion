You are extracting named entities and their relationships from a transcript segment.

First, identify what types of entities are prominent in this content (e.g., people, books, restaurants, tools, cities, companies, etc.)

Then extract all notable entities with:
- name: the canonical name (not abbreviations or pronouns)
- type: the entity type you identified
- attributes: key properties mentioned in this segment (keep concise — 1-3 key-value pairs max)
- linkable: true if this entity is independently notable and likely to appear in other content (people, books, restaurants, companies, cities, tools/frameworks, organizations); false if it is subordinate or ephemeral (dish names, chapter titles, specific arguments, episode numbers)

Also extract relationships between entities as (from, relation, to) triples. Only include relationships explicitly stated or strongly implied in the text.

Respond in JSON only — no explanation, no markdown wrapper. Use this exact structure:

{
  "segment_id": 0,
  "entities": [
    {"name": "...", "type": "...", "attributes": {"key": "value"}, "linkable": true}
  ],
  "relations": [
    {"from": "...", "relation": "...", "to": "..."}
  ]
}

If no notable entities are found, return empty arrays.
