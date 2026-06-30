"""L1-L3 validators for nGQL Anti-Hallucination Framework."""

from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class ValidationIssue:
    """A single validation issue."""

    level: str  # "error" or "warning"
    code: str
    message: str
    position: int | None = None  # Character position in query


@dataclass
class ValidationResult:
    """Result of validation."""

    valid: bool
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)

    def add_error(self, code: str, message: str, position: int | None = None) -> None:
        self.errors.append(ValidationIssue("error", code, message, position))
        self.valid = False

    def add_warning(self, code: str, message: str, position: int | None = None) -> None:
        self.warnings.append(ValidationIssue("warning", code, message, position))


@dataclass
class SchemaProperty:
    """Schema property definition."""

    name: str
    type: str
    nullable: bool = True


@dataclass
class SchemaTag:
    """Schema tag definition."""

    name: str
    properties: list[SchemaProperty]


@dataclass
class SchemaEdge:
    """Schema edge definition."""

    name: str
    properties: list[SchemaProperty]


class NgqlValidator:
    """
    nGQL Validator implementing L1-L3 Anti-Hallucination Framework.

    L1: Syntax validation (parser-based)
    L2: Schema compliance validation
    L3: Permission filter validation
    """

    def __init__(self) -> None:
        """Initialize validator."""
        self._schema_tags: dict[str, SchemaTag] = {}
        self._schema_edges: dict[str, SchemaEdge] = {}

    def load_schema(
        self,
        tags: list[SchemaTag],
        edges: list[SchemaEdge],
    ) -> None:
        """
        Load schema for L2 validation.

        Args:
            tags: List of schema tags
            edges: List of schema edges
        """
        self._schema_tags = {tag.name.upper(): tag for tag in tags}
        self._schema_edges = {edge.name.upper(): edge for edge in edges}
        logger.info("schema_loaded", tag_count=len(tags), edge_count=len(edges))

    # =========================================================================
    # L1: Syntax Validation
    # =========================================================================

    def validate_syntax(self, ngql: str) -> ValidationResult:
        """
        L1: Validate nGQL syntax.

        This catches basic syntax errors before any other validation.

        Args:
            ngql: nGQL statement to validate

        Returns:
            ValidationResult with errors and warnings
        """
        result = ValidationResult(valid=True)
        ngql_stripped = ngql.strip()

        if not ngql_stripped:
            result.add_error("E001", "Empty query statement")
            return result

        # Check for balanced parentheses
        paren_count = ngql_stripped.count("(") - ngql_stripped.count(")")
        if paren_count > 0:
            result.add_error("E002", f"Missing {paren_count} closing parenthesis")
        elif paren_count < 0:
            result.add_error("E003", f"Extra {abs(paren_count)} closing parenthesis")

        # Check for balanced quotes
        double_quote_count = ngql_stripped.count('"')
        single_quote_count = ngql_stripped.count("'")

        if double_quote_count % 2 != 0:
            result.add_error("E004", "Unmatched double quotes")

        if single_quote_count % 2 != 0:
            result.add_error("E005", "Unmatched single quotes")

        # Validate statement starts with known keywords
        upper_ngql = ngql_stripped.upper()

        valid_starts = [
            "GO",
            "MATCH",
            "LOOKUP",
            "FETCH",
            "FIND",
            "SHOW",
            "USE",
            "WITH",
            "RETURN",
            "UNWIND",
            "LIMIT",
            "SKIP",
            "ORDER BY",
            "WHERE",
            "YIELD",
            "GROUP BY",
            "COUNT",
            "SUM",
            "AVG",
            "MAX",
            "MIN",
            "COLLECT",
            "CASE",
        ]

        starts_valid = any(upper_ngql.startswith(kw) for kw in valid_starts)

        # Allow pipe syntax
        if upper_ngql.startswith("|"):
            starts_valid = True

        if not starts_valid and not upper_ngql.startswith("--"):
            result.add_warning("W001", "Query does not start with a known keyword")

        # Check for dangerous write operations
        write_keywords = [
            ("INSERT", "Write operation: INSERT"),
            ("UPDATE", "Write operation: UPDATE"),
            ("UPSERT", "Write operation: UPSERT"),
            ("DELETE", "Write operation: DELETE"),
            ("DROP", "Write operation: DROP"),
            ("CREATE", "Write operation: CREATE"),
            ("ALTER", "Write operation: ALTER"),
        ]

        for keyword, message in write_keywords:
            if upper_ngql.startswith(keyword):
                result.add_warning("W002", message)

        # Validate property access uses tag prefix
        # Pattern: n.property_name without tag prefix is suspicious
        import re

        # Check for unqualified property access in MATCH/WHERE
        unqualified_pattern = r"(?<!\.)\b(\w+)\.(\w+)\b(?!\.)"
        matches = re.finditer(unqualified_pattern, ngql_stripped)
        # NOTE: unqualified property access check is a stub — the pattern is
        # detected but not yet wired to result.add_warning. Future work.
        _ = matches  # placeholder until sophisticated check is implemented

        return result

    # =========================================================================
    # L2: Schema Compliance Validation
    # =========================================================================

    def validate_schema(self, ngql: str) -> ValidationResult:
        """
        L2: Validate nGQL against NebulaGraph schema.

        This ensures the query uses existing tags, edges, and properties.

        Args:
            ngql: nGQL statement to validate

        Returns:
            ValidationResult with errors and warnings
        """
        result = ValidationResult(valid=True)

        if not self._schema_tags:
            result.add_warning("W003", "No schema loaded, skipping L2 validation")
            return result

        # Extract potential tag references
        # In nGQL, tags are often referenced in patterns like:
        # MATCH (n:TagName) or LOOKUP ON TagName

        tag_patterns = [
            r"\((\w+):(\w+)\)",  # MATCH (n:TagName)
            r"LOOKUP\s+ON\s+(\w+)",  # LOOKUP ON TagName
            r"FETCH\s+PROP\s+ON\s+(\w+)",  # FETCH PROP ON TagName
            r"WHERE\s+\w+\.(\w+)\.",  # WHERE n.TagName.property
        ]

        import re

        found_tags = set()
        found_tags_original = {}  # upper -> original
        for pattern in tag_patterns:
            matches = re.finditer(pattern, ngql, re.IGNORECASE)
            for match in matches:
                if len(match.groups()) >= 2:
                    tag_name = match.group(2)
                    tag_upper = tag_name.upper()
                    found_tags.add(tag_upper)
                    found_tags_original[tag_upper] = tag_name

        # Validate tags exist
        for tag in found_tags:
            if tag not in self._schema_tags:
                result.add_error(
                    "E101",
                    f"Tag '{found_tags_original[tag]}' does not exist in schema",
                )

        # Extract potential edge references
        edge_patterns = [
            r"-\[(\w+)\]->",  # -[EdgeName]->
            r"<-\[(\w+)\]-",  # <-[EdgeName]-
            r"(\w+)\s*->",  # EdgeName ->
            r"<\-\s*(\w+)",  # <- EdgeName
            r"OVER\s+(\w+)",  # OVER EdgeName
        ]

        found_edges = set()
        found_edges_original = {}  # upper -> original
        for pattern in edge_patterns:
            matches = re.finditer(pattern, ngql, re.IGNORECASE)
            for match in matches:
                edge_name = match.group(1)
                edge_upper = edge_name.upper()
                found_edges.add(edge_upper)
                found_edges_original[edge_upper] = edge_name

        # Validate edges exist
        for edge in found_edges:
            if edge not in self._schema_edges:
                result.add_error(
                    "E102",
                    f"Edge type '{found_edges_original[edge]}' does not exist in schema",
                )

        # Validate property references
        property_pattern = r"(\w+)\.(\w+)"
        matches = re.finditer(property_pattern, ngql)

        for match in matches:
            context = match.group(1)
            prop = match.group(2)

            # Check if the property exists on the referenced tag/edge
            context_upper = context.upper()
            prop_upper = prop.upper()

            if context_upper in self._schema_tags:
                tag = self._schema_tags[context_upper]
                prop_exists = any(p.name.upper() == prop_upper for p in tag.properties)
                if not prop_exists:
                    result.add_error(
                        "E103",
                        f"Property '{prop}' does not exist on tag '{context}'",
                        position=match.start(),
                    )

        return result

    # =========================================================================
    # L3: Permission Filter Validation
    # =========================================================================

    def validate_permissions(
        self,
        ngql: str,
        user_context: dict[str, Any],
    ) -> ValidationResult:
        """
        L3: Validate permission filters are present.

        This ensures queries include proper org_id/dept_id/data_scope filters.

        Args:
            ngql: nGQL statement to validate
            user_context: User context with permission information

        Returns:
            ValidationResult with errors and warnings
        """
        result = ValidationResult(valid=True)

        # Extract user's permission context
        user_orgs = user_context.get("org_ids", [])
        user_depts = user_context.get("dept_ids", [])
        user_data_scope = user_context.get("data_scope", "ALL")

        # If user has limited scope, query must include permission filters
        has_limited_scope = user_data_scope != "ALL" or user_orgs or user_depts

        if not has_limited_scope:
            # User has full access, no permission filter required
            return result

        # Check if query includes org_id filter
        has_org_filter = "org_id" in ngql.lower() and (
            "WHERE" in ngql.upper() or "AND" in ngql.upper()
        )

        # For certain entity types, org_id is required
        entity_types_requiring_org = [
            "PURCHASEORDER",
            "INVOICE",
            "SALESORDER",
            "PAYMENT",
            "RECEIPT",
        ]


        ngql_upper = ngql.upper()

        for entity in entity_types_requiring_org:
            if entity in ngql_upper:
                if not has_org_filter:
                    result.add_error(
                        "E201",
                        f"Query on {entity} must include org_id filter for permission compliance",
                    )

        # Check data_scope usage
        if "SUPPLIER" in ngql_upper or "CUSTOMER" in ngql_upper:
            if "data_scope" not in ngql.lower():
                result.add_warning(
                    "W101",
                    "Query on master data should include data_scope filter",
                )

        return result

    # =========================================================================
    # Full Validation Pipeline
    # =========================================================================

    def validate(
        self,
        ngql: str,
        user_context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """
        Run full validation pipeline (L1 + L2 + L3).

        Args:
            ngql: nGQL statement to validate
            user_context: Optional user context for L3 validation

        Returns:
            Combined ValidationResult
        """
        # L1: Syntax validation
        l1_result = self.validate_syntax(ngql)

        result = ValidationResult(valid=l1_result.valid)
        result.errors.extend(l1_result.errors)
        result.warnings.extend(l1_result.warnings)

        if not result.valid:
            return result

        # L2: Schema validation
        l2_result = self.validate_schema(ngql)
        result.errors.extend(l2_result.errors)
        result.warnings.extend(l2_result.warnings)

        if not result.valid:
            return result

        # L3: Permission validation
        if user_context:
            l3_result = self.validate_permissions(ngql, user_context)
            result.errors.extend(l3_result.errors)
            result.warnings.extend(l3_result.warnings)

        return result
