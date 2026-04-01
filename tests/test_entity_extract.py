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


import json

from yt2notion.entity_extract import parse_entity_result, parse_segment_entities


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
