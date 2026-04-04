# Entity Extraction Feature Design

## Overview

Add an entity extraction pipeline step that identifies named entities (people, books, restaurants, tools, etc.) and their relationships from transcribed content. The output is a structured "entity card" section appended to the final Obsidian note, enabling long-term knowledge graph accumulation via `[[wiki-links]]`.

## Pipeline Position

EXTRACT runs **in parallel** with SUMMARIZE. Both read from `reviewed.json` independently.

```
1-4: DOWNLOAD → SEGMENT → TRANSCRIBE → REVIEW  (unchanged)
              ↓
         reviewed.json
              ↓
    ┌─────────┴─────────┐
    ↓                   ↓
5a. SUMMARIZE       5b. EXTRACT
    ↓                   ↓
summary.json      entities.json
    └─────────┬─────────┘
              ↓
        6. COMPOSE → output.md
```

EXTRACT has **no dependency** on SUMMARIZE and vice versa. Both can run concurrently via `asyncio.gather()`.

## CLI Interface

EXTRACT must be independently runnable for prompt iteration and debugging:

```bash
# Run full pipeline
yt2notion process <url>

# Run only entity extraction on existing reviewed data
yt2notion extract <content_dir>

# Re-compose output from existing summary + entities
yt2notion compose <content_dir>
```

`<content_dir>` contains `reviewed.json` (input) and produces `entities.json` (output). No other files are required.

## EXTRACT Internal Design

### Adaptive Strategy

Use token count of `reviewed.json` to decide the execution path:

```python
SINGLE_PASS_THRESHOLD = 30_000  # tokens, roughly ≤1hr content

async def extract(reviewed_segments: list[Segment]) -> EntityResult:
    total_tokens = estimate_tokens(reviewed_segments)

    if total_tokens < SINGLE_PASS_THRESHOLD:
        return await extract_single(reviewed_segments)
    else:
        return await extract_map_reduce(reviewed_segments)
```

### Single-Pass Path (short content)

One Haiku call with all segments concatenated. Suitable for content under ~1 hour.

### Map-Reduce Path (long content)

**Map phase:** Each segment gets an independent Haiku call, all running in parallel. Input is one segment's reviewed text; output is that segment's extracted entities and relations.

```
reviewed.json segments
    ↓
┌───┬───┬───┬───┐
s1  s2  s3  s4 ...   ← Haiku × N (asyncio parallel)
└───┴───┴───┴───┘
    ↓
raw_entities (list of per-segment results)
```

**Reduce phase:** One Haiku call that takes all per-segment results and performs:

1. **Entity deduplication** — merge different surface forms referring to the same entity (e.g. "Gaggan", "Gaggan Anand's restaurant", "the progressive Indian place in Bangkok" → single entity `Gaggan`)
2. **Relation deduplication** — remove duplicate relations, keep the most informative version
3. **Attribute consolidation** — merge attributes discovered in different segments into one record
4. **Domain classification** — label the content's domain (e.g. "food/dining", "tech", "literature") and whether it is entity-centric (`is_entity_centric: true/false`)

### Model

Use **Haiku** for all EXTRACT calls (both map and reduce). Entity extraction is a structured extraction task that does not require Sonnet/Opus-level reasoning.

## Entity Schema

### Per-Segment Output (Map Phase)

```json
{
  "segment_id": 3,
  "entities": [
    {
      "name": "Gaggan",
      "type": "restaurant",
      "attributes": {"city": "Bangkok", "cuisine": "Progressive Indian"},
      "linkable": true
    },
    {
      "name": "Curry Crab",
      "type": "dish",
      "attributes": {},
      "linkable": false
    }
  ],
  "relations": [
    {"from": "Gaggan", "relation": "serves", "to": "Curry Crab"}
  ]
}
```

### Final Output (entities.json)

```json
{
  "domain": "food/dining",
  "is_entity_centric": true,
  "entity_types": ["restaurant", "dish", "chef", "city"],
  "entities": [
    {
      "name": "Gaggan",
      "type": "restaurant",
      "attributes": {"city": "Bangkok", "cuisine": "Progressive Indian"},
      "linkable": true
    },
    {
      "name": "Gaggan Anand",
      "type": "person",
      "attributes": {"role": "chef"},
      "linkable": true
    },
    {
      "name": "Curry Crab",
      "type": "dish",
      "attributes": {},
      "linkable": false
    }
  ],
  "relations": [
    {"from": "Gaggan", "relation": "serves", "to": "Curry Crab"},
    {"from": "Gaggan Anand", "relation": "runs", "to": "Gaggan"},
    {"from": "Gaggan", "relation": "located_in", "to": "Bangkok"}
  ]
}
```

### The `linkable` Field

Determines whether the entity name becomes a `[[wiki-link]]` in the final markdown output.

- `true` — entities that are independently notable and likely to recur across different content: people, books, restaurants, companies, cities, tools/frameworks, organizations
- `false` — entities that are subordinate/ephemeral and unlikely to recur: dish names, chapter titles, specific arguments, episode numbers

This judgment is made by the LLM during extraction. The COMPOSE step uses this field mechanically — it does not make its own linking decisions.

## Prompt Design Guidelines

### Entity Type Discovery

Do NOT hardcode entity types. The prompt should instruct the LLM to:

1. First identify what types of entities are prominent in this content
2. Then extract entities of those discovered types

This allows the system to adapt to any domain: books/authors for a literature podcast, restaurants/dishes/chefs for a food podcast, tools/frameworks/companies for a tech podcast.

### Prompt Template Structure (Map Phase)

```
You are extracting named entities and their relationships from a transcript segment.

First, identify what types of entities are prominent in this content (e.g., people, books, restaurants, tools, cities, companies, etc.)

Then extract all notable entities with:
- name: the canonical name
- type: the entity type you identified
- attributes: key properties mentioned (keep concise)
- linkable: true if this entity is independently notable and likely to appear in other content; false if it is subordinate or ephemeral

Also extract relationships between entities as (from, relation, to) triples.

Respond in JSON only.

<segment>
{segment_text}
</segment>
```

### Prompt Template Structure (Reduce Phase)

```
You are consolidating entity extraction results from multiple transcript segments of the same content.

Your tasks:
1. Merge entities that refer to the same real-world thing (different surface forms → one canonical entry). Combine their attributes.
2. Deduplicate relations.
3. Classify the content domain (e.g. "food/dining", "technology", "literature").
4. Judge whether this content is entity-centric (true if entities form the structural backbone of the content).

Respond in JSON matching this schema: { domain, is_entity_centric, entity_types, entities, relations }

<segment_extractions>
{json_array_of_map_results}
</segment_extractions>
```

These prompts are starting points. Expect iteration — this is why EXTRACT is independently runnable.

## COMPOSE Step

COMPOSE merges `summary.json` and `entities.json` into the final `output.md`. It is **pure Python template logic** — no LLM call needed.

### Output Format

The entity section is appended after the summary section in the Obsidian note:

```markdown
... (summary content from existing pipeline) ...

---

## Entities

**Restaurants**
- [[Gaggan]] (Bangkok) — Curry Crab, Yogurt Explosion, Lamb Tikka
- [[L'Atelier de Joël Robuchon]] (Paris) — Lamb Steak, Le Caviar

**People**
- [[Gaggan Anand]] — chef at [[Gaggan]], trained at [[El Bulli]]

**Cities**
- [[Bangkok]] — [[Gaggan]], [[Nahm]], [[Bo.Lan]]
- [[Paris]] — [[L'Atelier de Joël Robuchon]], [[Le Cinq]]
```

### Formatting Rules

1. Group entities by `type`, using type name (capitalized) as section header
2. One entity per line: `- {name} ({key_attribute}) — {related entities or brief description}`
3. Apply `[[wiki-links]]` only to entities where `linkable: true`
4. If `is_entity_centric: false`, either omit the Entities section entirely or collapse it to a minimal "Mentioned: [[X]], [[Y]], [[Z]]" one-liner
5. Keep flat — no nested lists, no tables, no multi-line entries. This will be read on mobile.

## Implementation Checklist

- [ ] Add `ExtractProtocol` interface following project conventions
- [ ] Implement `extract_single()` for short content
- [ ] Implement `extract_map()` with async parallel Haiku calls
- [ ] Implement `extract_reduce()` for dedup/merge
- [ ] Add adaptive routing based on token count threshold
- [ ] Add `yt2notion extract <content_dir>` CLI command
- [ ] Implement COMPOSE step merging summary.json + entities.json → output.md
- [ ] Add `yt2notion compose <content_dir>` CLI command
- [ ] Refactor existing SUMMARIZE output to go through COMPOSE
- [ ] Wire EXTRACT ∥ SUMMARIZE parallel execution in `yt2notion process`
