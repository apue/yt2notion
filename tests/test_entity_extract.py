"""Tests for entity extraction."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from yt2notion.entity_extract import parse_entity_result, parse_segment_entities
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

class TestParseSegmentEntities:
    def test_valid_json(self):
        raw = json.dumps(
            {
                "segment_id": 1,
                "entities": [
                    {
                        "name": "Gaggan",
                        "type": "restaurant",
                        "attributes": {"city": "Bangkok"},
                        "linkable": True,
                    },
                    {"name": "Curry Crab", "type": "dish", "attributes": {}, "linkable": False},
                ],
                "relations": [
                    {"from": "Gaggan", "relation": "serves", "to": "Curry Crab"},
                ],
            }
        )
        entities, relations = parse_segment_entities(raw)
        assert len(entities) == 2
        assert entities[0].name == "Gaggan"
        assert entities[0].attributes == {"city": "Bangkok"}
        assert entities[1].linkable is False
        assert len(relations) == 1

    def test_json_in_code_block(self):
        raw = (
            "```json\n"
            + json.dumps(
                {
                    "segment_id": 1,
                    "entities": [
                        {"name": "X", "type": "person", "attributes": {}, "linkable": True}
                    ],
                    "relations": [],
                }
            )
            + "\n```"
        )
        entities, relations = parse_segment_entities(raw)
        assert len(entities) == 1
        assert entities[0].name == "X"

    def test_empty_entities(self):
        raw = json.dumps({"segment_id": 1, "entities": [], "relations": []})
        entities, relations = parse_segment_entities(raw)
        assert entities == []
        assert relations == []

    def test_missing_optional_fields(self):
        raw = json.dumps(
            {
                "segment_id": 1,
                "entities": [{"name": "Foo", "type": "tool"}],
                "relations": [],
            }
        )
        entities, relations = parse_segment_entities(raw)
        assert entities[0].attributes == {}
        assert entities[0].linkable is True


class TestParseEntityResult:
    def test_valid_json(self):
        raw = json.dumps(
            {
                "domain": "food/dining",
                "is_entity_centric": True,
                "entity_types": ["restaurant", "dish"],
                "entities": [
                    {
                        "name": "Gaggan",
                        "type": "restaurant",
                        "attributes": {"city": "Bangkok"},
                        "linkable": True,
                    },
                ],
                "relations": [
                    {"from": "Gaggan", "relation": "located_in", "to": "Bangkok"},
                ],
            }
        )
        result = parse_entity_result(raw)
        assert result.domain == "food/dining"
        assert result.is_entity_centric is True
        assert len(result.entities) == 1
        assert result.entities[0].name == "Gaggan"

    def test_empty_result(self):
        raw = json.dumps(
            {
                "domain": "",
                "is_entity_centric": False,
                "entity_types": [],
                "entities": [],
                "relations": [],
            }
        )
        result = parse_entity_result(raw)
        assert result.entities == []
        assert result.is_entity_centric is False

class TestExtractEntities:
    """Test extract_entities() with mocked LLM caller."""

    def _make_caller(self, responses: list[str]) -> MagicMock:
        caller = MagicMock()
        caller.call = MagicMock(side_effect=responses)
        return caller

    def test_single_pass_short_content(self):
        from yt2notion.entity_extract import extract_entities

        response = json.dumps(
            {
                "domain": "tech",
                "is_entity_centric": False,
                "entity_types": ["tool"],
                "entities": [
                    {"name": "Python", "type": "tool", "attributes": {}, "linkable": True}
                ],
                "relations": [],
            }
        )
        caller = self._make_caller([response])

        segments = [
            {
                "text": "We use Python for everything.",
                "title": "Intro",
                "start_seconds": 0,
                "end_seconds": 300,
            }
        ]
        result = extract_entities(segments, caller)

        assert isinstance(result, EntityResult)
        assert result.domain == "tech"
        assert len(result.entities) == 1
        assert result.entities[0].name == "Python"
        # Single pass: one call to reduce prompt (full content fits)
        assert caller.call.call_count == 1

    def test_map_reduce_long_content(self):
        from yt2notion.entity_extract import (
            SINGLE_PASS_THRESHOLD,
            _batch_segments_for_map_reduce,
            extract_entities,
        )

        # Create segments with enough text to exceed threshold
        long_text = "word " * 200  # ~200 tokens per segment
        n_segments = (SINGLE_PASS_THRESHOLD // 200) + 5
        segments = [
            {
                "text": long_text,
                "title": f"Seg {i}",
                "start_seconds": i * 300,
                "end_seconds": (i + 1) * 300,
            }
            for i in range(n_segments)
        ]

        map_response = json.dumps(
            {
                "segment_id": 0,
                "entities": [{"name": "X", "type": "tool", "attributes": {}, "linkable": True}],
                "relations": [],
            }
        )
        reduce_response = json.dumps(
            {
                "domain": "tech",
                "is_entity_centric": True,
                "entity_types": ["tool"],
                "entities": [{"name": "X", "type": "tool", "attributes": {}, "linkable": True}],
                "relations": [],
            }
        )
        batch_count = len(_batch_segments_for_map_reduce(segments))
        responses = [map_response] * batch_count + [reduce_response]
        caller = self._make_caller(responses)

        result = extract_entities(segments, caller)

        assert isinstance(result, EntityResult)
        assert caller.call.call_count == batch_count + 1

    def test_map_reduce_batching_avoids_tiny_batch_explosion(self):
        from yt2notion.entity_extract import _batch_segments_for_map_reduce

        # Dense segments should be bounded primarily by char limit, not tiny segment caps.
        segments = [
            {
                "text": "x" * 1000,
                "title": f"Seg {i}",
                "start_seconds": i * 60,
                "end_seconds": (i + 1) * 60,
            }
            for i in range(120)
        ]

        batch_count = len(_batch_segments_for_map_reduce(segments))

        assert batch_count <= 8

    def test_empty_segments(self):
        from yt2notion.entity_extract import extract_entities

        caller = self._make_caller([])
        result = extract_entities([], caller)

        assert isinstance(result, EntityResult)
        assert result.entities == []
        assert caller.call.call_count == 0
