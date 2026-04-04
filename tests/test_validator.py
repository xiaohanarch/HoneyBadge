"""Tests for L1-L3 validators."""

import pytest

from honeybadge.protocols.validator import (
    NgqlValidator,
    SchemaEdge,
    SchemaProperty,
    SchemaTag,
    ValidationResult,
)


class TestValidationResult:
    """Tests for ValidationResult class."""

    def test_valid_result_starts_true(self):
        """Should start as valid."""
        result = ValidationResult(valid=True)
        assert result.valid is True
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_add_error_makes_invalid(self):
        """Adding error should make result invalid."""
        result = ValidationResult(valid=True)
        result.add_error("E001", "Test error")

        assert result.valid is False
        assert len(result.errors) == 1
        assert result.errors[0].code == "E001"

    def test_add_warning_keeps_valid(self):
        """Adding warning should keep result valid."""
        result = ValidationResult(valid=True)
        result.add_warning("W001", "Test warning")

        assert result.valid is True
        assert len(result.warnings) == 1


class TestNgqlValidatorL1Syntax:
    """Tests for L1 syntax validation."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return NgqlValidator()

    def test_empty_query_is_invalid(self, validator):
        """Empty query should be invalid."""
        result = validator.validate_syntax("")
        assert result.valid is False
        assert any(e.code == "E001" for e in result.errors)

    def test_whitespace_only_is_invalid(self, validator):
        """Whitespace-only query should be invalid."""
        result = validator.validate_syntax("   \n\t  ")
        assert result.valid is False

    def test_unmatched_parentheses(self, validator):
        """Unmatched parentheses should be detected."""
        result = validator.validate_syntax("MATCH (n) RETURN n")
        assert result.valid is True

        result = validator.validate_syntax("MATCH (n RETURN n")
        assert result.valid is False
        assert any("parenthesis" in e.message.lower() for e in result.errors)

    def test_unmatched_quotes(self, validator):
        """Unmatched quotes should be detected."""
        result = validator.validate_syntax('MATCH (n) WHERE n.name == "test')
        assert result.valid is False
        assert any("quote" in e.message.lower() for e in result.errors)

    def test_valid_go_statement(self, validator):
        """Valid GO statement should pass."""
        result = validator.validate_syntax("GO FROM 'SUP:V001' OVER PLACED_WITH YIELD PLACED_WITH.order_date")
        assert result.valid is True

    def test_valid_match_statement(self, validator):
        """Valid MATCH statement should pass."""
        result = validator.validate_syntax("MATCH (n:Supplier) RETURN n")
        assert result.valid is True

    def test_write_operation_warning(self, validator):
        """Write operations should generate warning."""
        result = validator.validate_syntax("INSERT VERTEX Supplier(name) VALUES 'test':('name')")
        assert len(result.warnings) > 0
        assert any("INSERT" in w.message for w in result.warnings)


class TestNgqlValidatorL2Schema:
    """Tests for L2 schema validation."""

    @pytest.fixture
    def validator(self):
        """Create validator with schema loaded."""
        validator = NgqlValidator()

        # Load test schema
        tags = [
            SchemaTag(
                name="Supplier",
                properties=[
                    SchemaProperty(name="name", type="STRING"),
                    SchemaProperty(name="status", type="STRING"),
                ],
            ),
            SchemaTag(
                name="PurchaseOrder",
                properties=[
                    SchemaProperty(name="po_number", type="STRING"),
                    SchemaProperty(name="status", type="STRING"),
                    SchemaProperty(name="org_id", type="INT64"),
                ],
            ),
        ]

        edges = [
            SchemaEdge(
                name="PLACED_WITH",
                properties=[
                    SchemaProperty(name="order_date", type="TIMESTAMP"),
                    SchemaProperty(name="org_id", type="INT64"),
                ],
            ),
        ]

        validator.load_schema(tags, edges)
        return validator

    def test_valid_tag_is_accepted(self, validator):
        """Valid tag reference should pass."""
        result = validator.validate_schema("MATCH (n:Supplier) RETURN n")
        assert result.valid is True

    def test_invalid_tag_is_rejected(self, validator):
        """Invalid tag reference should fail."""
        result = validator.validate_schema("MATCH (n:InvalidTag) RETURN n")
        assert result.valid is False
        assert any("InvalidTag" in e.message for e in result.errors)

    def test_valid_edge_is_accepted(self, validator):
        """Valid edge reference should pass."""
        result = validator.validate_schema("GO FROM 'SUP:V001' OVER PLACED_WITH YIELD PLACED_WITH.order_date")
        assert result.valid is True

    def test_invalid_edge_is_rejected(self, validator):
        """Invalid edge reference should fail."""
        result = validator.validate_schema("GO FROM 'SUP:V001' OVER INVALID_EDGE YIELD INVALID_EDGE.prop")
        assert result.valid is False


class TestNgqlValidatorL3Permission:
    """Tests for L3 permission validation."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return NgqlValidator()

    def test_full_access_user_no_filter_required(self, validator):
        """User with full access doesn't need filters."""
        user_context = {"org_ids": [], "dept_ids": [], "data_scope": "ALL"}
        result = validator.validate_permissions(
            "MATCH (n:Supplier) RETURN n",
            user_context,
        )
        assert result.valid is True

    def test_limited_user_requires_org_filter(self, validator):
        """User with limited scope requires org_id filter."""
        user_context = {"org_ids": [1, 2], "dept_ids": [], "data_scope": "LIMITED"}

        # Query without org_id filter should fail
        result = validator.validate_permissions(
            "MATCH (n:PurchaseOrder) RETURN n",
            user_context,
        )
        assert result.valid is False

    def test_query_with_org_id_filter_passes(self, validator):
        """Query with org_id filter should pass."""
        user_context = {"org_ids": [1, 2], "dept_ids": [], "data_scope": "LIMITED"}

        result = validator.validate_permissions(
            "MATCH (n:PurchaseOrder) WHERE n.PurchaseOrder.org_id == 1 RETURN n",
            user_context,
        )
        assert result.valid is True


class TestNgqlValidatorFullPipeline:
    """Tests for full validation pipeline."""

    @pytest.fixture
    def validator(self):
        """Create validator with schema."""
        validator = NgqlValidator()
        validator.load_schema(
            tags=[
                SchemaTag(
                    name="Supplier",
                    properties=[
                        SchemaProperty(name="name", type="STRING"),
                    ],
                ),
            ],
            edges=[],
        )
        return validator

    def test_full_validation_passes(self, validator):
        """Valid query should pass full validation."""
        result = validator.validate("MATCH (n:Supplier) RETURN n")
        assert result.valid is True

    def test_full_validation_fails_at_l1(self, validator):
        """Syntax errors should fail at L1."""
        result = validator.validate("")
        assert result.valid is False
        assert any(e.code.startswith("E0") for e in result.errors)
