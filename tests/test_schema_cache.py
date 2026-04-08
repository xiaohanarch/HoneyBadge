import pytest
from honeybadge.gateway.schema_cache import SchemaCache, SchemaTag, SchemaEdge, SchemaProperty


def test_schema_cache_starts_empty():
    cache = SchemaCache()
    assert cache.get_tags() == {}
    assert cache.get_edges() == {}


def test_schema_cache_load_schema():
    cache = SchemaCache()
    tags = [
        SchemaTag(name="Supplier", properties=[SchemaProperty(name="id", type="string"), SchemaProperty(name="name", type="string")]),
        SchemaTag(name="PurchaseOrder", properties=[SchemaProperty(name="id", type="string"), SchemaProperty(name="amount", type="double")]),
    ]
    edges = [
        SchemaEdge(name="PLACED_WITH", properties=[SchemaProperty(name="date", type="string")]),
    ]
    cache.load_schema(tags, edges)

    assert "SUPPLIER" in cache.get_tags()
    assert "PURCHASEORDER" in cache.get_tags()
    assert "PLACED_WITH" in cache.get_edges()
    assert cache.get_tags()["SUPPLIER"].properties[0].name == "id"


def test_schema_cache_is_ready():
    cache = SchemaCache()
    assert not cache.is_ready()

    cache.load_schema([], [])
    assert cache.is_ready()


def test_schema_cache_get_schema_as_tags_edges():
    """Test that get_schema_as_tags_edges returns correct tuple of lists."""
    cache = SchemaCache()
    tags = [
        SchemaTag(name="Supplier", properties=[SchemaProperty(name="id", type="string")]),
    ]
    edges = [
        SchemaEdge(name="PLACED_WITH", properties=[]),
    ]
    cache.load_schema(tags, edges)

    result_tags, result_edges = cache.get_schema_as_tags_edges()
    assert len(result_tags) == 1
    assert result_tags[0].name == "Supplier"
    assert len(result_edges) == 1
    assert result_edges[0].name == "PLACED_WITH"
