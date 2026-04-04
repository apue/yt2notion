# Entity Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an entity extraction pipeline step that identifies named entities and relationships from transcribed content, producing structured entity cards in the final Obsidian/Notion output.

**Architecture:** Sequential pipeline — EXTRACT runs between REVIEW and SUMMARIZE, reading reviewed data already in memory (no redundant file loads). Uses Haiku for all extraction calls. Adaptive single-pass vs map-reduce based on token count. COMPOSE logic lives inside the storage backends (ObsidianStorage, NotionStorage) — no separate COMPOSE step. Workspace persistence via `entities.json` enables resume.

**Tech Stack:** Python 3.11+, typer CLI, `LLMCaller` protocol (Haiku via `claude -p`), existing prompt template system.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/yt2notion/models/base.py` | Modify | Add `EntityResult` and `Entity` dataclasses |
| `src/yt2notion/entity_extract.py` | Create | Entity extraction logic: single-pass + map-reduce, JSON parsing |
| `src/yt2notion/prompts/extract_entities.md` | Create | Map-phase prompt template |
| `src/yt2notion/prompts/reduce_entities.md` | Create | Reduce-phase prompt template |
| `src/yt2notion/workspace.py` | Modify | Add `save_entities()` / `load_entities()` |
| `src/yt2notion/pipeline.py` | Modify | Insert EXTRACT step between REVIEW and SUMMARIZE |
| `src/yt2notion/storage/obsidian.py` | Modify | Render entity section in summary markdown |
| `src/yt2notion/storage/base.py` | Modify | Add `entities` parameter to `save()` |
| `src/yt2notion/storage/notion.py` | Modify | Accept `entities` parameter (pass-through for now) |
| `src/yt2notion/cli.py` | Modify | Add `extract` subcommand |
| `tests/test_entity_extract.py` | Create | Tests for extraction logic + JSON parsing |
| `tests/test_entity_obsidian.py` | Create | Tests for entity rendering in Obsidian output |
| `tests/test_workspace.py` | Modify | Test entities roundtrip |

---

### Task 1: Data Models

**Files:**
- Modify: `src/yt2notion/models/base.py:120-127`
- Test: `tests/test_entity_extract.py` (new)

- [ ] **Step 1: Write the test for data models**

Create `tests/test_entity_extract.py`:

```python
"""Tests for entity extraction."""

from __future__ import annotations

from yt2notion.models.base import Entity, EntityResult


class TestEntityDataModels:
    def test_entity_defaults(self):
        e = Entity(name="Gaggan", type="restaurant")
        assert e.name == "Gaggan"
        assert e.type == "restaurant"
        assert e.attributes == {}
        assert e.linkable is True

    def test_entity_with_attributes(self):
        e = Entity(
            name="Curry Crab",
            type="dish",
            attributes={"origin": "Sri Lanka"},
            linkable=False,
        )
        assert e.attributes == {"origin": "Sri Lanka"}
        assert e.linkable is False

    def test_entity_result_defaults(self):
        r = EntityResult(
            domain="food/dining",
            is_entity_centric=True,
            entity_types=["restaurant", "dish"],
            entities=[Entity(name="Gaggan", type="restaurant")],
            relations=[{"from": "Gaggan", "relation": "serves", "to": "Curry Crab"}],
        )
        assert r.domain == "food/dining"
        assert len(r.entities) == 1
        assert len(r.relations) == 1

    def test_entity_result_empty(self):
        r = EntityResult(
            domain="",
            is_entity_centric=False,
            entity_types=[],
            entities=[],
            relations=[],
        )
        assert r.entities == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_entity_extract.py::TestEntityDataModels -v`
Expected: FAIL with `ImportError: cannot import name 'Entity' from 'yt2notion.models.base'`

- [ ] **Step 3: Implement the data models**

Add to `src/yt2notion/models/base.py` after the `FUN_FACTS_CATEGORIES` dict (after line 127):

```python
@dataclass
class Entity:
    """A named entity extracted from content."""

    name: str
    type: str
    attributes: dict[str, str] = field(default_factory=dict)
    linkable: bool = True


@dataclass
class EntityResult:
    """Complete entity extraction output."""

    domain: str
    is_entity_centric: bool
    entity_types: list[str]
    entities: list[Entity]
    relations: list[dict]  # [{from, relation, to}]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_entity_extract.py::TestEntityDataModels -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/yt2notion/models/base.py tests/test_entity_extract.py
git commit -m "feat(entity): add Entity and EntityResult dataclasses"
```

---

### Task 2: JSON Parsing for Entity Extraction

**Files:**
- Create: `src/yt2notion/entity_extract.py`
- Test: `tests/test_entity_extract.py`

- [ ] **Step 1: Write tests for JSON parsing**

Append to `tests/test_entity_extract.py`:

```python
import json

from yt2notion.entity_extract import parse_segment_entities, parse_entity_result


class TestParseSegmentEntities:
    def test_valid_json(self):
        raw = json.dumps({
            "segment_id": 1,
            "entities": [
                {"name": "Gaggan", "type": "restaurant", "attributes": {"city": "Bangkok"}, "linkable": True},
                {"name": "Curry Crab", "type": "dish", "attributes": {}, "linkable": False},
            ],
            "relations": [
                {"from": "Gaggan", "relation": "serves", "to": "Curry Crab"},
            ],
        })
        entities, relations = parse_segment_entities(raw)
        assert len(entities) == 2
        assert entities[0].name == "Gaggan"
        assert entities[0].attributes == {"city": "Bangkok"}
        assert entities[1].linkable is False
        assert len(relations) == 1

    def test_json_in_code_block(self):
        raw = "```json\n" + json.dumps({
            "segment_id": 1,
            "entities": [{"name": "X", "type": "person", "attributes": {}, "linkable": True}],
            "relations": [],
        }) + "\n```"
        entities, relations = parse_segment_entities(raw)
        assert len(entities) == 1
        assert entities[0].name == "X"

    def test_empty_entities(self):
        raw = json.dumps({"segment_id": 1, "entities": [], "relations": []})
        entities, relations = parse_segment_entities(raw)
        assert entities == []
        assert relations == []

    def test_missing_optional_fields(self):
        raw = json.dumps({
            "segment_id": 1,
            "entities": [{"name": "Foo", "type": "tool"}],
            "relations": [],
        })
        entities, relations = parse_segment_entities(raw)
        assert entities[0].attributes == {}
        assert entities[0].linkable is True


class TestParseEntityResult:
    def test_valid_json(self):
        raw = json.dumps({
            "domain": "food/dining",
            "is_entity_centric": True,
            "entity_types": ["restaurant", "dish"],
            "entities": [
                {"name": "Gaggan", "type": "restaurant", "attributes": {"city": "Bangkok"}, "linkable": True},
            ],
            "relations": [
                {"from": "Gaggan", "relation": "located_in", "to": "Bangkok"},
            ],
        })
        result = parse_entity_result(raw)
        assert result.domain == "food/dining"
        assert result.is_entity_centric is True
        assert len(result.entities) == 1
        assert result.entities[0].name == "Gaggan"

    def test_empty_result(self):
        raw = json.dumps({
            "domain": "",
            "is_entity_centric": False,
            "entity_types": [],
            "entities": [],
            "relations": [],
        })
        result = parse_entity_result(raw)
        assert result.entities == []
        assert result.is_entity_centric is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_entity_extract.py::TestParseSegmentEntities tests/test_entity_extract.py::TestParseEntityResult -v`
Expected: FAIL with `ImportError: cannot import name 'parse_segment_entities'`

- [ ] **Step 3: Implement the parsing functions**

Create `src/yt2notion/entity_extract.py`:

```python
"""Entity extraction from reviewed transcripts using LLM."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from yt2notion.models.base import Entity, EntityResult

if TYPE_CHECKING:
    pass


def _strip_code_block(text: str) -> str:
    """Remove markdown code block wrapper if present."""
    text = text.strip()
    match = re.match(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _parse_entity(d: dict) -> Entity:
    """Parse a single entity dict into an Entity dataclass."""
    return Entity(
        name=d["name"],
        type=d["type"],
        attributes=d.get("attributes", {}),
        linkable=d.get("linkable", True),
    )


def parse_segment_entities(raw: str) -> tuple[list[Entity], list[dict]]:
    """Parse per-segment extraction output.

    Returns (entities, relations).
    """
    text = _strip_code_block(raw)
    data = json.loads(text)
    entities = [_parse_entity(e) for e in data.get("entities", [])]
    relations = data.get("relations", [])
    return entities, relations


def parse_entity_result(raw: str) -> EntityResult:
    """Parse final reduce-phase output into EntityResult."""
    text = _strip_code_block(raw)
    data = json.loads(text)
    entities = [_parse_entity(e) for e in data.get("entities", [])]
    return EntityResult(
        domain=data.get("domain", ""),
        is_entity_centric=data.get("is_entity_centric", False),
        entity_types=data.get("entity_types", []),
        entities=entities,
        relations=data.get("relations", []),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_entity_extract.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/yt2notion/entity_extract.py tests/test_entity_extract.py
git commit -m "feat(entity): add JSON parsing for entity extraction"
```

---

### Task 3: Prompt Templates

**Files:**
- Create: `src/yt2notion/prompts/extract_entities.md`
- Create: `src/yt2notion/prompts/reduce_entities.md`
- Test: `tests/test_prompts.py` (modify — add loading test)

- [ ] **Step 1: Write test for prompt loading**

Append to `tests/test_prompts.py` (check existing tests first — follow the same pattern):

```python
def test_load_extract_entities():
    from yt2notion.prompts import load_prompt
    text = load_prompt("extract_entities")
    assert "entities" in text
    assert "linkable" in text


def test_load_reduce_entities():
    from yt2notion.prompts import load_prompt
    text = load_prompt("reduce_entities")
    assert "deduplicate" in text.lower() or "merge" in text.lower() or "consolidat" in text.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_prompts.py::test_load_extract_entities tests/test_prompts.py::test_load_reduce_entities -v`
Expected: FAIL with `FileNotFoundError: Prompt template not found`

- [ ] **Step 3: Create the map-phase prompt**

Create `src/yt2notion/prompts/extract_entities.md`:

```markdown
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
```

- [ ] **Step 4: Create the reduce-phase prompt**

Create `src/yt2notion/prompts/reduce_entities.md`:

```markdown
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_prompts.py::test_load_extract_entities tests/test_prompts.py::test_load_reduce_entities -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/yt2notion/prompts/extract_entities.md src/yt2notion/prompts/reduce_entities.md tests/test_prompts.py
git commit -m "feat(entity): add extraction and reduce prompt templates"
```

---

### Task 4: Core Extraction Logic

**Files:**
- Modify: `src/yt2notion/entity_extract.py`
- Test: `tests/test_entity_extract.py`

- [ ] **Step 1: Write tests for extraction functions**

Append to `tests/test_entity_extract.py`:

```python
from unittest.mock import MagicMock

from yt2notion.models.base import EntityResult, Entity


class TestExtractEntities:
    """Test extract_entities() with mocked LLM caller."""

    def _make_caller(self, responses: list[str]) -> MagicMock:
        caller = MagicMock()
        caller.call = MagicMock(side_effect=responses)
        return caller

    def test_single_pass_short_content(self):
        from yt2notion.entity_extract import extract_entities

        response = json.dumps({
            "domain": "tech",
            "is_entity_centric": False,
            "entity_types": ["tool"],
            "entities": [{"name": "Python", "type": "tool", "attributes": {}, "linkable": True}],
            "relations": [],
        })
        caller = self._make_caller([response])

        segments = [{"text": "We use Python for everything.", "title": "Intro", "start_seconds": 0, "end_seconds": 300}]
        result = extract_entities(segments, caller)

        assert isinstance(result, EntityResult)
        assert result.domain == "tech"
        assert len(result.entities) == 1
        assert result.entities[0].name == "Python"
        # Single pass: one call to reduce prompt (full content fits)
        assert caller.call.call_count == 1

    def test_map_reduce_long_content(self):
        from yt2notion.entity_extract import extract_entities, SINGLE_PASS_THRESHOLD

        # Create segments with enough text to exceed threshold
        # Each segment has ~100 chars ≈ ~25 tokens; need > SINGLE_PASS_THRESHOLD tokens
        long_text = "word " * 200  # ~200 tokens per segment
        n_segments = (SINGLE_PASS_THRESHOLD // 200) + 5
        segments = [
            {"text": long_text, "title": f"Seg {i}", "start_seconds": i * 300, "end_seconds": (i + 1) * 300}
            for i in range(n_segments)
        ]

        map_response = json.dumps({
            "segment_id": 0,
            "entities": [{"name": "X", "type": "tool", "attributes": {}, "linkable": True}],
            "relations": [],
        })
        reduce_response = json.dumps({
            "domain": "tech",
            "is_entity_centric": True,
            "entity_types": ["tool"],
            "entities": [{"name": "X", "type": "tool", "attributes": {}, "linkable": True}],
            "relations": [],
        })
        # N map calls + 1 reduce call
        responses = [map_response] * n_segments + [reduce_response]
        caller = self._make_caller(responses)

        result = extract_entities(segments, caller)

        assert isinstance(result, EntityResult)
        assert caller.call.call_count == n_segments + 1

    def test_empty_segments(self):
        from yt2notion.entity_extract import extract_entities

        caller = self._make_caller([])
        result = extract_entities([], caller)

        assert isinstance(result, EntityResult)
        assert result.entities == []
        assert caller.call.call_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_entity_extract.py::TestExtractEntities -v`
Expected: FAIL with `ImportError: cannot import name 'extract_entities'`

- [ ] **Step 3: Implement the extraction logic**

Add to `src/yt2notion/entity_extract.py` (after the existing parsing functions):

```python
from yt2notion.models.llm import LLMCaller
from yt2notion.prompts import load_prompt

SINGLE_PASS_THRESHOLD = 30_000  # tokens (rough estimate: 1 token ≈ 4 chars)


def _estimate_tokens(segments: list[dict]) -> int:
    """Rough token estimate: ~4 chars per token."""
    total_chars = sum(len(seg.get("text", "")) for seg in segments)
    return total_chars // 4


def _concat_segments(segments: list[dict]) -> str:
    """Join segment texts with title headers."""
    parts: list[str] = []
    for seg in segments:
        title = seg.get("title", "")
        text = seg.get("text", "")
        if title:
            parts.append(f"[{title}]\n{text}")
        else:
            parts.append(text)
    return "\n\n".join(parts)


def extract_entities(segments: list[dict], caller: LLMCaller) -> EntityResult:
    """Extract entities from reviewed segments.

    Uses single-pass for short content, map-reduce for long content.
    """
    if not segments:
        return EntityResult(
            domain="",
            is_entity_centric=False,
            entity_types=[],
            entities=[],
            relations=[],
        )

    total_tokens = _estimate_tokens(segments)

    if total_tokens < SINGLE_PASS_THRESHOLD:
        return _extract_single_pass(segments, caller)
    else:
        return _extract_map_reduce(segments, caller)


def _extract_single_pass(segments: list[dict], caller: LLMCaller) -> EntityResult:
    """Single Haiku call with all segments concatenated."""
    system_prompt = load_prompt("reduce_entities")
    user_prompt = _concat_segments(segments)
    raw = caller.call(system_prompt, user_prompt, max_tokens=4000)
    return parse_entity_result(raw)


def _extract_map_reduce(segments: list[dict], caller: LLMCaller) -> EntityResult:
    """Map phase: one Haiku call per segment. Reduce phase: one merge call."""
    map_prompt = load_prompt("extract_entities")
    all_entities: list[dict] = []

    for i, seg in enumerate(segments):
        text = seg.get("text", "")
        if not text.strip():
            continue
        raw = caller.call(map_prompt, text, max_tokens=4000)
        try:
            entities, relations = parse_segment_entities(raw)
            all_entities.append({
                "segment_id": i,
                "entities": [
                    {"name": e.name, "type": e.type, "attributes": e.attributes, "linkable": e.linkable}
                    for e in entities
                ],
                "relations": relations,
            })
        except (json.JSONDecodeError, KeyError):
            continue  # Skip segments with unparseable output

    if not all_entities:
        return EntityResult(
            domain="",
            is_entity_centric=False,
            entity_types=[],
            entities=[],
            relations=[],
        )

    # Reduce phase
    reduce_prompt = load_prompt("reduce_entities")
    user_prompt = json.dumps(all_entities, ensure_ascii=False, indent=2)
    raw = caller.call(reduce_prompt, user_prompt, max_tokens=4000)
    return parse_entity_result(raw)
```

Update the imports at the top of the file — the final import block should be:

```python
from yt2notion.models.base import Entity, EntityResult
from yt2notion.models.llm import LLMCaller
from yt2notion.prompts import load_prompt
```

(Move `LLMCaller` and `load_prompt` out of `TYPE_CHECKING` since they're used at runtime.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_entity_extract.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run ruff**

Run: `uv run ruff check src/yt2notion/entity_extract.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/yt2notion/entity_extract.py tests/test_entity_extract.py
git commit -m "feat(entity): implement extract_entities with single-pass and map-reduce"
```

---

### Task 5: Workspace Persistence

**Files:**
- Modify: `src/yt2notion/workspace.py:14-23` (step artifacts) and add methods
- Modify: `tests/test_workspace.py`

- [ ] **Step 1: Write test for entities roundtrip**

Append to `tests/test_workspace.py`:

```python
from yt2notion.models.base import Entity, EntityResult


def test_entities_roundtrip(tmp_path):
    ws = Workspace(tmp_path, "test123")
    result = EntityResult(
        domain="food/dining",
        is_entity_centric=True,
        entity_types=["restaurant", "dish"],
        entities=[
            Entity(name="Gaggan", type="restaurant", attributes={"city": "Bangkok"}, linkable=True),
            Entity(name="Curry Crab", type="dish", attributes={}, linkable=False),
        ],
        relations=[{"from": "Gaggan", "relation": "serves", "to": "Curry Crab"}],
    )
    ws.save_entities(result)
    loaded = ws.load_entities()
    assert loaded is not None
    assert loaded.domain == "food/dining"
    assert loaded.is_entity_centric is True
    assert len(loaded.entities) == 2
    assert loaded.entities[0].name == "Gaggan"
    assert loaded.entities[0].attributes == {"city": "Bangkok"}
    assert loaded.entities[1].linkable is False
    assert len(loaded.relations) == 1


def test_load_entities_missing(tmp_path):
    ws = Workspace(tmp_path, "test123")
    assert ws.load_entities() is None


def test_step_done_extract(tmp_path):
    ws = Workspace(tmp_path, "test123")
    assert not ws.step_done("extract")
    result = EntityResult(
        domain="", is_entity_centric=False, entity_types=[], entities=[], relations=[],
    )
    ws.save_entities(result)
    assert ws.step_done("extract")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_workspace.py::test_entities_roundtrip tests/test_workspace.py::test_load_entities_missing tests/test_workspace.py::test_step_done_extract -v`
Expected: FAIL with `AttributeError: 'Workspace' object has no attribute 'save_entities'`

- [ ] **Step 3: Implement workspace methods**

In `src/yt2notion/workspace.py`:

Add `"extract": "entities.json"` to `_STEP_ARTIFACTS` (line 15-21):

```python
_STEP_ARTIFACTS: dict[str, str] = {
    "download": "metadata.json",
    "segment": "segments.json",
    "transcribe": "transcripts.json",
    "review": "reviewed.json",
    "extract": "entities.json",
    "summarize": "summary.json",
}
```

Update `STEPS` (line 23):

```python
STEPS = ("download", "segment", "transcribe", "review", "extract", "summarize")
```

Add save/load methods after `save_reviewed` / `load_reviewed` (after line 134):

```python
    # --- Entities ---

    def save_entities(self, result: EntityResult) -> None:
        from dataclasses import asdict

        self._write_json("entities.json", asdict(result))

    def load_entities(self) -> EntityResult | None:
        d = self._read_json("entities.json")
        if d is None:
            return None
        from yt2notion.models.base import Entity, EntityResult

        entities = [
            Entity(
                name=e["name"],
                type=e["type"],
                attributes=e.get("attributes", {}),
                linkable=e.get("linkable", True),
            )
            for e in d.get("entities", [])
        ]
        return EntityResult(
            domain=d.get("domain", ""),
            is_entity_centric=d.get("is_entity_centric", False),
            entity_types=d.get("entity_types", []),
            entities=entities,
            relations=d.get("relations", []),
        )
```

Add `EntityResult` to the `TYPE_CHECKING` block (line 12):

```python
if TYPE_CHECKING:
    from yt2notion.models.base import ChineseContent, EntityResult, VideoMeta
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_workspace.py -v`
Expected: PASS (all tests including the new 3)

- [ ] **Step 5: Fix the existing STEPS test**

The existing test `test_steps_constant` (line 77) asserts the old tuple. Update it:

```python
def test_steps_constant():
    assert STEPS == ("download", "segment", "transcribe", "review", "extract", "summarize")
```

- [ ] **Step 6: Run all workspace tests again**

Run: `uv run pytest tests/test_workspace.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/yt2notion/workspace.py tests/test_workspace.py
git commit -m "feat(entity): add entities persistence to workspace"
```

---

### Task 6: Pipeline Integration

**Files:**
- Modify: `src/yt2notion/pipeline.py:134-151`
- Modify: `src/yt2notion/storage/base.py:12-22`

- [ ] **Step 1: Update the Storage protocol to accept entities**

In `src/yt2notion/storage/base.py`, update the `save()` signature (line 12-22):

```python
    def save(
        self,
        content: ChineseContent,
        metadata: VideoMeta,
        *,
        transcript_segments: list[dict] | None = None,
        entities: EntityResult | None = None,
    ) -> str:
        """Save content and return a URL or path to the created resource."""
        ...
```

Add `EntityResult` to `TYPE_CHECKING` imports:

```python
if TYPE_CHECKING:
    from yt2notion.models.base import ChineseContent, EntityResult, VideoMeta
```

- [ ] **Step 2: Update NotionStorage.save() to accept entities (pass-through)**

In `src/yt2notion/storage/notion.py`, update the `save()` signature (line 44-50):

```python
    def save(
        self,
        content: ChineseContent,
        metadata: VideoMeta,
        *,
        transcript_segments: list[dict] | None = None,
        entities: EntityResult | None = None,
    ) -> str:
```

Add to `TYPE_CHECKING` imports at the top:

```python
if TYPE_CHECKING:
    from yt2notion.models.base import ChineseContent, EntityResult, VideoMeta
```

No other changes to NotionStorage — entities are accepted but not rendered yet.

- [ ] **Step 3: Insert EXTRACT step into pipeline**

In `src/yt2notion/pipeline.py`, add the EXTRACT step between REVIEW and SUMMARIZE.

Add import at the top (after line 21):

```python
from yt2notion.models.llm import create_llm_caller
```

After the REVIEW block (after line 147) and before the SUMMARIZE block (line 149), insert:

```python
    # --- Step 5: EXTRACT ENTITIES ---
    if start_idx <= 4:
        entities = _step_extract(reviewed, raw_config, verbose)
        ws.save_entities(entities)
    else:
        entities = ws.load_entities()

    # --- Step 6: SUMMARIZE ---
```

Also update the existing step comments to match new numbering:
- Step 4: REVIEW (unchanged)
- Step 5: EXTRACT (new)
- Step 6: SUMMARIZE (was step 5)

Update the `start_idx` comparisons for SUMMARIZE from `<= 4` (implicit, it was the last step) to remain correct. Since EXTRACT is now step index 4 and SUMMARIZE is step index 5, the existing code already works because SUMMARIZE always runs (it has no `start_idx` guard — it runs unconditionally at line 150).

Update the `storage.save()` call (line 177-181) to pass entities:

```python
    result_url = storage.save(
        chinese_content,
        metadata,
        transcript_segments=None if is_long else reviewed,
        entities=entities,
    )
```

- [ ] **Step 4: Implement `_step_extract` function**

Add after `_step_review` (after line 512):

```python
def _step_extract(
    reviewed: list[dict],
    config: dict,
    verbose: bool,
) -> EntityResult:
    """Step 5: Extract entities from reviewed transcripts."""
    if verbose:
        typer.echo("Extracting entities...")

    from yt2notion.entity_extract import extract_entities

    caller = create_llm_caller(config, model_key="review_model")
    result = extract_entities(reviewed, caller)

    if verbose:
        typer.echo(f"  Found {len(result.entities)} entities ({result.domain})")

    return result
```

Add `EntityResult` to the `TYPE_CHECKING` imports (line 26):

```python
    from yt2notion.models.base import ChineseContent, EntityResult, Summarizer, VideoMeta
```

- [ ] **Step 5: Run existing tests to verify nothing is broken**

Run: `uv run pytest tests/ -v --ignore=tests/test_integration.py`
Expected: PASS (all existing tests)

- [ ] **Step 6: Commit**

```bash
git add src/yt2notion/pipeline.py src/yt2notion/storage/base.py src/yt2notion/storage/notion.py
git commit -m "feat(entity): wire EXTRACT step into pipeline between REVIEW and SUMMARIZE"
```

---

### Task 7: Obsidian Entity Rendering

**Files:**
- Modify: `src/yt2notion/storage/obsidian.py:147-225`
- Create: `tests/test_entity_obsidian.py`

- [ ] **Step 1: Write tests for entity rendering**

Create `tests/test_entity_obsidian.py`:

```python
"""Tests for entity rendering in Obsidian output."""

from __future__ import annotations

from pathlib import Path

import pytest

from yt2notion.models.base import ChineseContent, Entity, EntityResult, VideoMeta
from yt2notion.storage.obsidian import ObsidianStorage


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def meta() -> VideoMeta:
    return VideoMeta(
        video_id="abc123",
        title="Bangkok Food Tour",
        channel="Mark Wiens",
        upload_date="20240315",
        url="https://www.youtube.com/watch?v=abc123",
        duration_seconds=1574,
        subtitles_available=True,
    )


@pytest.fixture
def content() -> ChineseContent:
    return ChineseContent(
        overview="曼谷美食之旅。",
        key_points=[
            {"timestamp": "5:30", "title": "Gaggan 餐厅", "summary": "创新印度菜"},
        ],
        tags=["美食", "曼谷"],
        raw_markdown="raw md",
    )


@pytest.fixture
def entities() -> EntityResult:
    return EntityResult(
        domain="food/dining",
        is_entity_centric=True,
        entity_types=["restaurant", "dish", "person", "city"],
        entities=[
            Entity(name="Gaggan", type="restaurant", attributes={"city": "Bangkok", "cuisine": "Progressive Indian"}, linkable=True),
            Entity(name="Gaggan Anand", type="person", attributes={"role": "chef"}, linkable=True),
            Entity(name="Curry Crab", type="dish", attributes={}, linkable=False),
            Entity(name="Bangkok", type="city", attributes={}, linkable=True),
        ],
        relations=[
            {"from": "Gaggan Anand", "relation": "runs", "to": "Gaggan"},
            {"from": "Gaggan", "relation": "serves", "to": "Curry Crab"},
            {"from": "Gaggan", "relation": "located_in", "to": "Bangkok"},
        ],
    )


class TestEntityRendering:
    def test_entities_section_in_output(
        self, vault: Path, meta: VideoMeta, content: ChineseContent, entities: EntityResult
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, entities=entities)
        text = Path(result).read_text(encoding="utf-8")

        assert "## Entities" in text

    def test_entities_grouped_by_type(
        self, vault: Path, meta: VideoMeta, content: ChineseContent, entities: EntityResult
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, entities=entities)
        text = Path(result).read_text(encoding="utf-8")

        assert "**Restaurant**" in text
        assert "**Person**" in text
        assert "**City**" in text

    def test_linkable_entities_get_wikilinks(
        self, vault: Path, meta: VideoMeta, content: ChineseContent, entities: EntityResult
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, entities=entities)
        text = Path(result).read_text(encoding="utf-8")

        assert "[[Gaggan]]" in text
        assert "[[Gaggan Anand]]" in text
        assert "[[Bangkok]]" in text
        # Non-linkable should NOT have wiki-links
        assert "[[Curry Crab]]" not in text
        assert "Curry Crab" in text  # but still mentioned

    def test_entity_attributes_shown(
        self, vault: Path, meta: VideoMeta, content: ChineseContent, entities: EntityResult
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, entities=entities)
        text = Path(result).read_text(encoding="utf-8")

        # Key attribute shown in parentheses
        assert "Bangkok" in text  # Gaggan's city attribute

    def test_no_entities_section_when_none(
        self, vault: Path, meta: VideoMeta, content: ChineseContent
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, entities=None)
        text = Path(result).read_text(encoding="utf-8")

        assert "## Entities" not in text

    def test_non_entity_centric_shows_minimal(
        self, vault: Path, meta: VideoMeta, content: ChineseContent
    ):
        entities = EntityResult(
            domain="tech",
            is_entity_centric=False,
            entity_types=["tool"],
            entities=[
                Entity(name="Python", type="tool", linkable=True),
                Entity(name="Rust", type="tool", linkable=True),
            ],
            relations=[],
        )
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, entities=entities)
        text = Path(result).read_text(encoding="utf-8")

        # Non-entity-centric: one-liner "Mentioned: ..." instead of full section
        assert "Mentioned:" in text
        assert "[[Python]]" in text
        assert "[[Rust]]" in text

    def test_entities_before_tags(
        self, vault: Path, meta: VideoMeta, content: ChineseContent, entities: EntityResult
    ):
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, entities=entities)
        text = Path(result).read_text(encoding="utf-8")

        entities_pos = text.index("## Entities")
        tags_pos = text.index("## 标签")
        assert entities_pos < tags_pos

    def test_empty_entities_no_section(
        self, vault: Path, meta: VideoMeta, content: ChineseContent
    ):
        entities = EntityResult(
            domain="", is_entity_centric=False, entity_types=[], entities=[], relations=[],
        )
        storage = ObsidianStorage(vault_path=str(vault))
        result = storage.save(content, meta, entities=entities)
        text = Path(result).read_text(encoding="utf-8")

        assert "## Entities" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_entity_obsidian.py -v`
Expected: FAIL — `ObsidianStorage.save()` doesn't accept `entities` parameter

- [ ] **Step 3: Update ObsidianStorage.save() signature**

In `src/yt2notion/storage/obsidian.py`, update the `save()` method (line 102-129):

```python
    def save(
        self,
        content: ChineseContent,
        metadata: VideoMeta,
        *,
        transcript_segments: list[dict] | None = None,
        entities: EntityResult | None = None,
    ) -> str:
        """Write summary + transcript files to vault. Return summary path."""
        today = date.today().isoformat()
        sanitized = _sanitize_title(metadata.title)

        summaries_path = self.vault_path / self.summaries_dir
        summaries_path.mkdir(parents=True, exist_ok=True)
        summary_file = _resolve_unique_path(summaries_path / f"{today} {sanitized}.md")

        transcript_file = self._resolve_transcript_path(metadata)
        transcript_stem = transcript_file.stem

        summary_md = self._render_summary(content, metadata, transcript_stem, today, entities)
        summary_file.write_text(summary_md, encoding="utf-8")

        if transcript_segments:
            transcript_md = self._render_transcript(
                metadata, transcript_segments, summary_file.stem
            )
            transcript_file.write_text(transcript_md, encoding="utf-8")

        return str(summary_file)
```

Add `EntityResult` to `TYPE_CHECKING` imports:

```python
if TYPE_CHECKING:
    from yt2notion.models.base import ChineseContent, EntityResult, VideoMeta
```

- [ ] **Step 4: Update `_render_summary()` to accept and render entities**

Update the signature and add entity rendering before the tags section. In `src/yt2notion/storage/obsidian.py`, update `_render_summary()` (line 147-225):

```python
    def _render_summary(
        self,
        content: ChineseContent,
        metadata: VideoMeta,
        transcript_stem: str,
        today: str,
        entities: EntityResult | None = None,
    ) -> str:
```

Add entity rendering before the `## 标签` section (before line 219). Replace the block from `lines.append("")` / `lines.append("## 标签")` (lines 219-223) with:

```python
        # Entities
        if entities and entities.entities:
            lines.append("")
            if entities.is_entity_centric:
                lines.append("## Entities")
                lines.append("")
                # Group by type
                types_seen: list[str] = []
                for et in entities.entity_types:
                    if et not in types_seen:
                        types_seen.append(et)
                for et in types_seen:
                    type_entities = [e for e in entities.entities if e.type == et]
                    if not type_entities:
                        continue
                    lines.append(f"**{et.capitalize()}**")
                    for e in type_entities:
                        name_display = f"[[{e.name}]]" if e.linkable else e.name
                        # Find relations where this entity is the subject
                        related = [
                            r for r in entities.relations if r.get("from") == e.name
                        ]
                        parts: list[str] = []
                        # Key attribute in parentheses
                        attr_str = ""
                        if e.attributes:
                            first_val = next(iter(e.attributes.values()))
                            attr_str = f" ({first_val})"
                        # Related entities
                        for r in related:
                            target = r.get("to", "")
                            # Check if target is linkable
                            target_entity = next(
                                (te for te in entities.entities if te.name == target), None
                            )
                            if target_entity and target_entity.linkable:
                                parts.append(f"[[{target}]]")
                            else:
                                parts.append(target)
                        suffix = f" — {', '.join(parts)}" if parts else ""
                        lines.append(f"- {name_display}{attr_str}{suffix}")
                    lines.append("")
            else:
                # Non-entity-centric: one-liner
                linkable = [e for e in entities.entities if e.linkable]
                if linkable:
                    names = ", ".join(f"[[{e.name}]]" for e in linkable)
                    lines.append(f"Mentioned: {names}")
                    lines.append("")

        lines.append("")
        lines.append("## 标签")
        lines.append("")
        lines.append(" ".join(f"#{tag}" for tag in content.tags))
        lines.append("")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_entity_obsidian.py -v`
Expected: PASS (all 8 tests)

- [ ] **Step 6: Run existing obsidian tests to verify no regression**

Run: `uv run pytest tests/test_obsidian_storage.py -v`
Expected: PASS (all existing tests — they pass `entities=None` implicitly via the default)

- [ ] **Step 7: Run ruff**

Run: `uv run ruff check src/yt2notion/storage/obsidian.py`
Expected: No errors

- [ ] **Step 8: Commit**

```bash
git add src/yt2notion/storage/obsidian.py tests/test_entity_obsidian.py
git commit -m "feat(entity): render entity cards in Obsidian output with wiki-links"
```

---

### Task 8: CLI `extract` Subcommand

**Files:**
- Modify: `src/yt2notion/cli.py`

- [ ] **Step 1: Write a manual test plan**

The `extract` subcommand reads `reviewed.json` from a workspace directory and writes `entities.json`. Since this requires LLM calls, we'll test it manually rather than in unit tests.

Manual test:
```bash
# After running a full pipeline once:
uv run yt2notion extract workspace/<video_id>/ --verbose
# Should print entity count and write entities.json
```

- [ ] **Step 2: Add the `extract` subcommand**

In `src/yt2notion/cli.py`, add after the `process` command (before `if __name__`):

```python
@app.command()
def extract(
    content_dir: str = typer.Argument(help="Workspace directory containing reviewed.json"),
    config_path: str = typer.Option("config.yaml", "--config", "-c", help="Config file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Extract entities from reviewed transcript in a workspace directory."""
    from pathlib import Path

    try:
        config = load_config(config_path)
    except ConfigError as e:
        typer.echo(f"Configuration error: {e}", err=True)
        raise typer.Exit(1) from None

    from yt2notion.entity_extract import extract_entities
    from yt2notion.models.base import EntityResult
    from yt2notion.models.llm import create_llm_caller

    ws_dir = Path(content_dir)
    reviewed_path = ws_dir / "reviewed.json"
    if not reviewed_path.exists():
        typer.echo(f"No reviewed.json found in {content_dir}", err=True)
        raise typer.Exit(1) from None

    import json

    reviewed = json.loads(reviewed_path.read_text(encoding="utf-8"))

    raw_config = {
        "model": config.model,
    }
    caller = create_llm_caller(raw_config, model_key="review_model")

    if verbose:
        typer.echo(f"Extracting entities from {len(reviewed)} segments...")

    result = extract_entities(reviewed, caller)

    # Save to workspace
    from dataclasses import asdict

    output_path = ws_dir / "entities.json"
    output_path.write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if verbose:
        typer.echo(f"  Domain: {result.domain}")
        typer.echo(f"  Entity-centric: {result.is_entity_centric}")
        typer.echo(f"  Entities: {len(result.entities)}")
        typer.echo(f"  Relations: {len(result.relations)}")
    typer.echo(f"Saved to {output_path}")
```

- [ ] **Step 3: Run ruff**

Run: `uv run ruff check src/yt2notion/cli.py`
Expected: No errors

- [ ] **Step 4: Verify help text**

Run: `uv run yt2notion --help`
Expected: Shows both `process` and `extract` commands

Run: `uv run yt2notion extract --help`
Expected: Shows `CONTENT_DIR` argument and `--config`, `--verbose` options

- [ ] **Step 5: Commit**

```bash
git add src/yt2notion/cli.py
git commit -m "feat(entity): add 'extract' CLI subcommand for standalone entity extraction"
```

---

### Task 9: Full Test Suite and Lint

**Files:**
- All test files

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v --ignore=tests/test_integration.py`
Expected: PASS

- [ ] **Step 2: Run ruff on all source files**

Run: `uv run ruff check src/`
Expected: No errors

Run: `uv run ruff format --check src/`
Expected: No formatting issues (or run `uv run ruff format src/` to fix)

- [ ] **Step 3: Commit any lint fixes**

```bash
git add -u
git commit -m "style: fix lint issues"
```

---

### Task 10: Update Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `PROJECT_MAP.md`
- Modify: `README.md`

- [ ] **Step 1: Update CLAUDE.md pipeline diagram**

In the "管道流程" section, update the diagram to include EXTRACT:

```
URL
 ↓
1. DOWNLOAD     → metadata.json + (subtitles.srt | audio.mp3)
 ↓
2. SEGMENT      → segments.json  (chapters > LLM提取 > N/A)
 ↓
3. TRANSCRIBE   → transcripts.json  (字幕分配 | 逐段ASR | 全量ASR+句分)
 ↓                    ↓
 │              3.5 TOPIC SEGMENT  (超长段落 → Haiku 按话题拆分)
 ↓
4. REVIEW       → reviewed.json  (Haiku 校对 ASR 错误)
 ↓
5. EXTRACT      → entities.json  (Haiku 实体提取 + 关系识别)
 ↓
6. SUMMARIZE    → summary.json   (Sonnet map × N + Opus reduce → Storage)
 ↓                    ↓
 │              6.5 DEFERRED REVIEW  (长内容：总结后再校对 + 写入 transcript)
 ↓
7. PUBLISH      → Notion page / Obsidian note + transcript sub-page/文件
```

Also update the model table to add entity extraction:

| 步骤 | 模型 | 用途 |
|------|------|------|
| 章节提取 / 话题分段 / 转录校对 | Haiku | 轻量结构化任务 |
| **实体提取 / 关系识别** | **Haiku** | **结构化实体抽取** |
| 逐段摘要（Map） | Sonnet | 英文结构提取 |
| 全局综合（Reduce） | Opus | 中文润色 + 全局连贯 |
| ASR 转写 | Qwen3-ASR 1.7B 4-bit | 本地 Mac Mini |

Update the data contract for Step 5:

```
Step 5 → entities.json    : EntityResult {domain, is_entity_centric, entity_types, entities[{name, type, attributes, linkable}], relations}
Step 6 → summary.json     : ChineseContent {overview, key_points[{timestamp, title, summary}], tags, fun_facts, raw_markdown, ?mindmap}
```

- [ ] **Step 2: Update PROJECT_MAP.md**

Add to the data contract section:

```
Step 5 → entities.json    : EntityResult {domain, is_entity_centric, entity_types, entities[{name, type, attributes, linkable}], relations}
```

Add to prompt template table:

```
| `extract_entities.md` | `entity_extract.py` map 阶段 | Haiku | (无变量) |
| `reduce_entities.md` | `entity_extract.py` reduce 阶段 | Haiku | (无变量) |
```

Update dependency graph:

```
entity_extract.py → models/llm.py (LLMCaller), prompts/
storage/obsidian.py → models/base.py (FUN_FACTS_CATEGORIES, Entity, EntityResult)
```

Add to the data models line:

```
所有数据模型定义在 `models/base.py`：VideoMeta, Chapter, Summary, ChunkSummary, ChineseContent, FUN_FACTS_CATEGORIES, Entity, EntityResult 等。
```

Update the Config ↔ Code table — no new config fields needed (EXTRACT uses existing `model.review_model`).

Update workspace step artifacts:

```
_STEP_ARTIFACTS includes "extract": "entities.json"
STEPS = ("download", "segment", "transcribe", "review", "extract", "summarize")
```

- [ ] **Step 3: Update README.md features list**

Add after "Fun facts extraction" bullet:

```markdown
- **Entity extraction**: identifies people, places, tools, and their relationships — builds a knowledge graph via `[[wiki-links]]`
```

Update pipeline diagram to show EXTRACT step.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md PROJECT_MAP.md README.md
git commit -m "docs: update documentation for entity extraction feature"
```
