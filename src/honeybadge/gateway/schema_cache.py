"""L2 schema cache for Anti-Hallucination Framework (L2 Schema Validation)."""
from dataclasses import dataclass, field

from honeybadge.protocols.validator import SchemaTag, SchemaEdge, SchemaProperty


@dataclass
class SchemaCache:
    """
    Caches NebulaGraph schema for L2 validation.

    Schema is obtained via Matrix message to HiClaw Worker at startup.
    """

    _tags: dict[str, SchemaTag] = field(default_factory=dict)
    _edges: dict[str, SchemaEdge] = field(default_factory=dict)
    _ready: bool = False

    def load_schema(self, tags: list[SchemaTag], edges: list[SchemaEdge]) -> None:
        """Load schema from tags and edges list."""
        self._tags = {tag.name.upper(): tag for tag in tags}
        self._edges = {edge.name.upper(): edge for edge in edges}
        self._ready = True

    def get_tags(self) -> dict[str, SchemaTag]:
        """Get all schema tags."""
        return self._tags

    def get_edges(self) -> dict[str, SchemaEdge]:
        """Get all schema edges."""
        return self._edges

    def is_ready(self) -> bool:
        """Check if schema has been loaded."""
        return self._ready

    def get_schema_as_tags_edges(self) -> tuple[list[SchemaTag], list[SchemaEdge]]:
        """Return schema as lists (for NgqlValidator.load_schema)."""
        return list(self._tags.values()), list(self._edges.values())
