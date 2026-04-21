"""Ontology loader — dynamic per-domain ontology injection for LLM prompts.

Loads `prompts/ontology/*.md` files, extracts routing keywords from each file's
`> **Keywords**:` header, routes a user question to 1–3 relevant domains, and
renders the concatenated ontology text for LLM context injection.
"""

from .loader import OntologyDomain, OntologyLoader, get_loader

__all__ = ["OntologyDomain", "OntologyLoader", "get_loader"]
