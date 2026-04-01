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
