You are consolidating entity extraction results from multiple transcript segments of the same content.

Your tasks:
1. Merge entities that refer to the same real-world thing (different surface forms → one canonical entry). Combine their attributes.
2. Deduplicate relations — keep the most informative version of each.
3. Classify the content domain (e.g. "food/dining", "technology", "literature", "fitness", "travel").
4. Judge whether this content is entity-centric: true if entities form the structural backbone of the content (e.g. a restaurant review, a book discussion), false if entities are incidental mentions.

Respond in JSON only — no explanation, no markdown wrapper. Use this exact structure:

{
  "domain": "...",
  "is_entity_centric": true,
  "entity_types": ["type1", "type2"],
  "entities": [
    {"name": "...", "type": "...", "attributes": {"key": "value"}, "linkable": true}
  ],
  "relations": [
    {"from": "...", "relation": "...", "to": "..."}
  ]
}
