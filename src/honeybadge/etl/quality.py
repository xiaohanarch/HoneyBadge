"""Data quality checks for HoneyBadge ETL pipeline.

Implements the data quality validation layer of the Anti-Hallucination Framework,
checking ODS data for referential integrity, null values, format compliance,
and business rules before transformation into NebulaGraph.

Quality check results:
    - passed: Record passed all checks, proceed to transformation
    - passed_with_warnings: Non-critical issues found, proceed with caution
    - failed: Critical issues found, quarantine the record
    - quarantined: Record moved to quarantine table
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import asyncpg
import structlog

from honeybadge.core.exceptions import HoneyBadgeError

logger = structlog.get_logger()


class DQStatus(str, Enum):
    """Data quality status values."""

    PENDING = "pending"
    PASSED = "passed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class ErrorType(str, Enum):
    """Error types for quarantine records."""

    NULL_CHECK = "null_check"
    TYPE_CHECK = "type_check"
    REF_INTEGRITY = "ref_integrity"
    BUSINESS_RULE = "business_rule"
    FORMAT_CHECK = "format_check"


class Severity(str, Enum):
    """Error severity levels."""

    WARNING = "warning"
    CRITICAL = "critical"


# =============================================================================
# Validation Rules
# =============================================================================


@dataclass
class ValidationRule:
    """A single validation rule definition."""

    name: str
    rule_type: str  # null_check, type_check, ref_integrity, business_rule, format_check
    column: str
    description: str
    severity: Severity = Severity.WARNING
    params: dict[str, Any] = field(default_factory=dict)

    # For expect_column_values_to_be_in_set
    value_set: list[Any] | None = None

    # For expect_column_values_to_be_between
    min_value: Any | None = None
    max_value: Any | None = None
    or_equal: bool = False

    # For expect_column_values_to_match_regex
    regex_pattern: str | None = None

    # For expect_column_pair_values_A_to_be_greater_than_B
    column_a: str | None = None
    column_b: str | None = None


# Validation rules for Purchase Order
PURCHASE_ORDER_RULES: list[ValidationRule] = [
    ValidationRule(
        name="po_number_not_null",
        rule_type="null_check",
        column="po_number",
        description="PO number must not be null",
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="vendor_id_not_null",
        rule_type="null_check",
        column="vendor_id",
        description="Vendor ID must not be null",
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="total_amount_not_null",
        rule_type="null_check",
        column="total_amount",
        description="Total amount must not be null",
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="order_date_not_null",
        rule_type="null_check",
        column="order_date",
        description="Order date must not be null",
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="org_id_not_null",
        rule_type="null_check",
        column="org_id",
        description="Organization ID must not be null",
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="total_amount_positive",
        rule_type="business_rule",
        column="total_amount",
        description="Total amount must be >= 0",
        params={"min_value": 0},
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="currency_code_valid",
        rule_type="business_rule",
        column="currency_code",
        description="Currency code must be valid",
        value_set=["CNY", "USD", "EUR", "JPY", "GBP", "HKD"],
        severity=Severity.WARNING,
    ),
    ValidationRule(
        name="status_valid",
        rule_type="business_rule",
        column="status",
        description="PO status must be valid",
        value_set=["DRAFT", "APPROVED", "OPEN", "CLOSED", "CANCELLED"],
        severity=Severity.WARNING,
    ),
    ValidationRule(
        name="po_number_format",
        rule_type="format_check",
        column="po_number",
        description="PO number must match expected format",
        regex_pattern=r"^PO[-/]\S+$",
        severity=Severity.WARNING,
    ),
    ValidationRule(
        name="approved_date_after_order",
        rule_type="business_rule",
        column="approved_date",
        description="Approved date must be >= order date",
        params={"column_a": "approved_date", "column_b": "order_date", "or_equal": True},
        severity=Severity.WARNING,
    ),
]

# Validation rules for Supplier
SUPPLIER_RULES: list[ValidationRule] = [
    ValidationRule(
        name="vendor_number_not_null",
        rule_type="null_check",
        column="vendor_number",
        description="Vendor number must not be null",
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="vendor_name_not_null",
        rule_type="null_check",
        column="vendor_name",
        description="Vendor name must not be null",
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="status_valid",
        rule_type="business_rule",
        column="status",
        description="Supplier status must be valid",
        value_set=["ACTIVE", "INACTIVE", "BLOCKED", "PENDING"],
        severity=Severity.WARNING,
    ),
]

# Validation rules for Item
ITEM_RULES: list[ValidationRule] = [
    ValidationRule(
        name="item_number_not_null",
        rule_type="null_check",
        column="item_number",
        description="Item number must not be null",
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="item_name_not_null",
        rule_type="null_check",
        column="item_name",
        description="Item name must not be null",
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="status_valid",
        rule_type="business_rule",
        column="status",
        description="Item status must be valid",
        value_set=["ACTIVE", "INACTIVE", "OBSOLETE"],
        severity=Severity.WARNING,
    ),
]

# Validation rules for Invoice
INVOICE_RULES: list[ValidationRule] = [
    ValidationRule(
        name="invoice_number_not_null",
        rule_type="null_check",
        column="invoice_number",
        description="Invoice number must not be null",
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="vendor_id_not_null",
        rule_type="null_check",
        column="vendor_id",
        description="Vendor ID must not be null",
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="invoice_date_not_null",
        rule_type="null_check",
        column="invoice_date",
        description="Invoice date must not be null",
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="total_amount_not_null",
        rule_type="null_check",
        column="total_amount",
        description="Total amount must not be null",
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="total_amount_positive",
        rule_type="business_rule",
        column="total_amount",
        description="Total amount must be >= 0",
        params={"min_value": 0},
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="status_valid",
        rule_type="business_rule",
        column="status",
        description="Invoice status must be valid",
        value_set=["DRAFT", "VALIDATED", "APPROVED", "PAID", "CANCELLED", "ON_HOLD"],
        severity=Severity.WARNING,
    ),
]

# Validation rules for Sales Order
SALES_ORDER_RULES: list[ValidationRule] = [
    ValidationRule(
        name="so_number_not_null",
        rule_type="null_check",
        column="so_number",
        description="SO number must not be null",
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="customer_id_not_null",
        rule_type="null_check",
        column="customer_id",
        description="Customer ID must not be null",
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="order_date_not_null",
        rule_type="null_check",
        column="order_date",
        description="Order date must not be null",
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="total_amount_not_null",
        rule_type="null_check",
        column="total_amount",
        description="Total amount must not be null",
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="total_amount_positive",
        rule_type="business_rule",
        column="total_amount",
        description="Total amount must be >= 0",
        params={"min_value": 0},
        severity=Severity.CRITICAL,
    ),
    ValidationRule(
        name="status_valid",
        rule_type="business_rule",
        column="status",
        description="SO status must be valid",
        value_set=["DRAFT", "BOOKED", "SHIPPED", "INVOICED", "CLOSED", "CANCELLED"],
        severity=Severity.WARNING,
    ),
]

# Table to rules mapping
TABLE_VALIDATION_RULES: dict[str, list[ValidationRule]] = {
    "ods_purchase_order": PURCHASE_ORDER_RULES,
    "ods_supplier": SUPPLIER_RULES,
    "ods_item": ITEM_RULES,
    "ods_ap_invoice": INVOICE_RULES,
    "ods_sales_order": SALES_ORDER_RULES,
}


# =============================================================================
# Quarantine Record
# =============================================================================


@dataclass
class QuarantineRecord:
    """A record sent to quarantine due to quality check failure."""

    batch_id: str
    source_table: str
    source_id: str
    error_type: ErrorType
    error_detail: dict[str, Any]
    severity: Severity
    rule_name: str
    created_at: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# Check Results
# =============================================================================


@dataclass
class IntegrityCheckResult:
    """Result of a referential integrity check."""

    rule: str  # e.g., "ods_purchase_order.vendor_id -> ods_supplier.vendor_id"
    passed: bool
    orphan_count: int = 0
    sample_values: list[Any] = field(default_factory=list)
    error_message: str | None = None


@dataclass
class ValidationResult:
    """Result of a validation rule check."""

    rule_name: str
    passed: bool
    column: str
    failed_values: list[Any] = field(default_factory=list)
    error_message: str | None = None


@dataclass
class DQCheckSummary:
    """Summary of data quality checks for a batch."""

    batch_id: str
    table_name: str
    total_records: int = 0
    passed: int = 0
    passed_with_warnings: int = 0
    failed: int = 0
    quarantined: int = 0
    validation_results: list[ValidationResult] = field(default_factory=list)
    integrity_results: list[IntegrityCheckResult] = field(default_factory=list)
    quarantined_records: list[QuarantineRecord] = field(default_factory=list)
    checked_at: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# Referential Integrity Check
# =============================================================================


class ReferentialIntegrityCheck:
    """
    Cross-table referential integrity validation.

    Validates that foreign key relationships in ODS tables are valid,
    e.g., ods_purchase_order.vendor_id must reference a valid ods_supplier.vendor_id.

    Example:
        >>> checker = ReferentialIntegrityCheck(postgres_dsn="postgresql://...")
        >>> results = await checker.check(batch_id="ETL-20260404-001")
        >>> for result in results:
        ...     if not result.passed:
        ...         print(f"Orphan found: {result.rule}")
    """

    # Referential integrity rules: (source_table.source_column, pk_table.pk_column)
    RULES: dict[str, tuple[str, str]] = {
        "ods_purchase_order.vendor_id": ("ods_supplier", "vendor_id"),
        "ods_purchase_order.buyer_id": ("ods_employee", "employee_id"),
        "ods_purchase_order_line.item_id": ("ods_item", "inventory_item_id"),
        "ods_purchase_order_line.po_header_id": ("ods_purchase_order", "po_header_id"),
        "ods_receipt.po_header_id": ("ods_purchase_order", "po_header_id"),
        "ods_receipt_line.shipment_header_id": ("ods_receipt", "shipment_header_id"),
        "ods_receipt_line.po_line_id": ("ods_purchase_order_line", "po_line_id"),
        "ods_ap_invoice.vendor_id": ("ods_supplier", "vendor_id"),
        "ods_ap_invoice.po_header_id": ("ods_purchase_order", "po_header_id"),
        "ods_ap_invoice_line.invoice_id": ("ods_ap_invoice", "invoice_id"),
        "ods_ap_invoice_line.po_line_id": ("ods_purchase_order_line", "po_line_id"),
        "ods_ap_invoice_line.receipt_line_id": ("ods_receipt_line", "shipment_line_id"),
        "ods_ap_payment.vendor_id": ("ods_supplier", "vendor_id"),
        "ods_sales_order.customer_id": ("ods_customer", "customer_id"),
        "ods_sales_order_line.header_id": ("ods_sales_order", "header_id"),
        "ods_sales_order_line.item_id": ("ods_item", "inventory_item_id"),
        "ods_shipment.so_header_id": ("ods_sales_order", "header_id"),
        "ods_shipment_line.delivery_detail_id": ("ods_shipment", "delivery_detail_id"),
        "ods_shipment_line.so_line_id": ("ods_sales_order_line", "line_id"),
        "ods_ar_invoice.customer_id": ("ods_customer", "customer_id"),
        "ods_ar_invoice.so_header_id": ("ods_sales_order", "header_id"),
        "ods_ar_receipt.customer_id": ("ods_customer", "customer_id"),
        "ods_bom_component.bom_id": ("ods_bom_header", "bom_id"),
        "ods_bom_component.component_item_id": ("ods_item", "inventory_item_id"),
        "ods_bom_header.assembly_item_id": ("ods_item", "inventory_item_id"),
        "ods_employee.org_id": ("ods_organization", "org_id"),
        "ods_warehouse.org_id": ("ods_organization", "org_id"),
        "ods_purchase_requisition.requester_id": ("ods_employee", "employee_id"),
        "ods_purchase_requisition_line.requisition_header_id": ("ods_purchase_requisition", "requisition_header_id"),
        "ods_purchase_requisition_line.item_id": ("ods_item", "inventory_item_id"),
        "ods_gl_journal_line.je_header_id": ("ods_gl_journal", "je_header_id"),
        "ods_gl_journal_line.code_combination_id": ("ods_gl_account", "code_combination_id"),
        "ods_xla_distribution.event_id": ("ods_xla_event", "event_id"),
        "ods_xla_distribution.code_combination_id": ("ods_gl_account", "code_combination_id"),
        "ods_supplier_qualification.vendor_id": ("ods_supplier", "vendor_id"),
        "ods_asl.vendor_id": ("ods_supplier", "vendor_id"),
        "ods_asl.item_id": ("ods_item", "inventory_item_id"),
        "ods_approval_record.approver_id": ("ods_employee", "employee_id"),
    }

    def __init__(self, postgres_dsn: str):
        """
        Initialize the referential integrity checker.

        Args:
            postgres_dsn: PostgreSQL connection string for ODS database
        """
        self.postgres_dsn = postgres_dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        """Connect to the ODS PostgreSQL database."""
        self._pool = await asyncpg.create_pool(
            self.postgres_dsn, min_size=2, max_size=10
        )
        logger.info("ref_integrity_checker_connected")

    async def disconnect(self) -> None:
        """Disconnect from the ODS PostgreSQL database."""
        if self._pool:
            await self._pool.close()
            self._pool = None
        logger.info("ref_integrity_checker_disconnected")

    async def check(self, batch_id: str) -> list[IntegrityCheckResult]:
        """
        Run all referential integrity checks for a batch.

        Args:
            batch_id: ETL batch identifier

        Returns:
            List of IntegrityCheckResult for each rule checked
        """
        results: list[IntegrityCheckResult] = []

        for fk_column, (pk_table, pk_column) in self.RULES.items():
            fk_table = fk_column.split(".")[0]
            fk_col = fk_column.split(".")[1]

            result = await self._check_single_rule(
                batch_id=batch_id,
                fk_table=fk_table,
                fk_column=fk_col,
                pk_table=pk_table,
                pk_column=pk_column,
            )
            results.append(result)

            if not result.passed:
                logger.warning(
                    "ref_integrity_violation",
                    rule=f"{fk_table}.{fk_col} -> {pk_table}.{pk_column}",
                    orphan_count=result.orphan_count,
                    batch_id=batch_id,
                )

        return results

    async def _check_single_rule(
        self,
        batch_id: str,
        fk_table: str,
        fk_column: str,
        pk_table: str,
        pk_column: str,
    ) -> IntegrityCheckResult:
        """
        Check a single referential integrity rule.

        Args:
            batch_id: ETL batch identifier
            fk_table: Foreign key table name
            fk_column: Foreign key column name
            pk_table: Primary key table name
            pk_column: Primary key column name

        Returns:
            IntegrityCheckResult for this rule
        """
        rule_name = f"{fk_table}.{fk_column} -> {pk_table}.{pk_column}"

        try:
            # Find orphans: FK values that don't exist in PK table
            query = f"""
                SELECT t.{fk_column}, count(*) as cnt
                FROM {fk_table} t
                LEFT JOIN {pk_table} p ON t.{fk_column} = p.{pk_column}
                WHERE t.etl_batch_id = $1
                  AND p.{pk_column} IS NULL
                  AND t.{fk_column} IS NOT NULL
                GROUP BY t.{fk_column}
                LIMIT 10
            """

            # TODO: Implement actual query execution
            assert self._pool is not None
            async with self._pool.acquire() as conn:
                orphans = await conn.fetch(query, batch_id)

            if orphans:
                orphan_count = sum(r["cnt"] for r in orphans)
                sample_values = [r[fk_column] for r in orphans]

                return IntegrityCheckResult(
                    rule=rule_name,
                    passed=False,
                    orphan_count=orphan_count,
                    sample_values=sample_values,
                )

            return IntegrityCheckResult(rule=rule_name, passed=True)

        except Exception as e:
            logger.error("ref_integrity_check_failed", rule=rule_name, error=str(e))
            return IntegrityCheckResult(
                rule=rule_name,
                passed=False,
                error_message=str(e),
            )


# =============================================================================
# Data Quality Checker
# =============================================================================


class DataQualityChecker:
    """
    Main data quality validation orchestrator.

    Runs validation rules and referential integrity checks against ODS tables,
    updates dq_status, and routes failed records to quarantine.

    Example:
        >>> checker = DataQualityChecker(postgres_dsn="postgresql://...")
        >>> summary = await checker.check_table(
        ...     table_name="ods_purchase_order",
        ...     batch_id="ETL-20260404-001"
        ... )
        >>> print(f"Passed: {summary.passed}, Quarantined: {summary.quarantined}")
    """

    def __init__(
        self,
        postgres_dsn: str,
        quarantine_threshold: int = 100,
    ):
        """
        Initialize the data quality checker.

        Args:
            postgres_dsn: PostgreSQL connection string for ODS database
            quarantine_threshold: Number of quarantined records to trigger alert
        """
        self.postgres_dsn = postgres_dsn
        self.quarantine_threshold = quarantine_threshold
        self._pool: asyncpg.Pool | None = None
        self._ref_checker: ReferentialIntegrityCheck | None = None

    async def connect(self) -> None:
        """Connect to the ODS PostgreSQL database."""
        self._pool = await asyncpg.create_pool(
            self.postgres_dsn, min_size=2, max_size=10
        )

        # Create referential integrity checker with same connection
        self._ref_checker = ReferentialIntegrityCheck(self.postgres_dsn)
        await self._ref_checker.connect()

        logger.info("data_quality_checker_connected")

    async def disconnect(self) -> None:
        """Disconnect from the ODS PostgreSQL database."""
        if self._ref_checker:
            await self._ref_checker.disconnect()

        if self._pool:
            await self._pool.close()
            self._pool = None

        logger.info("data_quality_checker_disconnected")

    async def check_table(
        self,
        table_name: str,
        batch_id: str,
    ) -> DQCheckSummary:
        """
        Run data quality checks for a specific ODS table.

        Args:
            table_name: Name of the ODS table to check
            batch_id: ETL batch identifier

        Returns:
            DQCheckSummary with check results
        """
        summary = DQCheckSummary(
            batch_id=batch_id,
            table_name=table_name,
        )

        # Get validation rules for this table
        rules = TABLE_VALIDATION_RULES.get(table_name, [])

        if not rules:
            logger.warning("no_validation_rules", table=table_name)
            return summary

        # Get total record count
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            summary.total_records = await conn.fetchval(
                f"SELECT COUNT(*) FROM {table_name} WHERE etl_batch_id = $1",
                batch_id,
            )

        # Run validation rules
        for rule in rules:
            result = await self._validate_rule(table_name, batch_id, rule)
            summary.validation_results.append(result)

            if not result.passed:
                if rule.severity == Severity.CRITICAL:
                    summary.failed += len(result.failed_values)
                    # Create quarantine records
                    for value in result.failed_values:
                        summary.quarantined_records.append(
                            QuarantineRecord(
                                batch_id=batch_id,
                                source_table=table_name,
                                source_id=str(value),
                                error_type=ErrorType(rule.rule_type),
                                error_detail={"rule": rule.name, "column": rule.column},
                                severity=Severity.CRITICAL,
                                rule_name=rule.name,
                            )
                        )
                else:
                    summary.passed_with_warnings += 1

        # Update dq_status in ODS table
        await self._update_dq_status(summary)

        # Insert quarantine records
        if summary.quarantined_records:
            await self._insert_quarantine(summary.quarantined_records)

        logger.info(
            "table_quality_check_complete",
            table=table_name,
            batch_id=batch_id,
            total=summary.total_records,
            passed=summary.passed,
            passed_with_warnings=summary.passed_with_warnings,
            failed=summary.failed,
            quarantined=summary.quarantined,
        )

        return summary

    async def check_all_tables(self, batch_id: str) -> list[DQCheckSummary]:
        """
        Run data quality checks for all ODS tables.

        Args:
            batch_id: ETL batch identifier

        Returns:
            List of DQCheckSummary for each table
        """
        summaries: list[DQCheckSummary] = []

        for table_name in TABLE_VALIDATION_RULES:
            summary = await self.check_table(table_name, batch_id)
            summaries.append(summary)

        # Run referential integrity checks
        if self._ref_checker:
            ref_results = await self._ref_checker.check(batch_id)

            # Check if any referential integrity violations
            for result in ref_results:
                if not result.passed:
                    logger.warning(
                        "ref_integrity_violation_found",
                        rule=result.rule,
                        orphan_count=result.orphan_count,
                        batch_id=batch_id,
                    )

        return summaries

    async def _validate_rule(
        self,
        table_name: str,
        batch_id: str,
        rule: ValidationRule,
    ) -> ValidationResult:
        """
        Validate a single rule against the table data.

        Args:
            table_name: Name of the ODS table
            batch_id: ETL batch identifier
            rule: ValidationRule to apply

        Returns:
            ValidationResult with pass/fail information
        """
        try:
            if rule.rule_type == "null_check":
                return await self._check_null(table_name, batch_id, rule)
            elif rule.rule_type == "business_rule":
                return await self._check_business_rule(table_name, batch_id, rule)
            elif rule.rule_type == "format_check":
                return await self._check_format(table_name, batch_id, rule)
            else:
                return ValidationResult(
                    rule_name=rule.name,
                    passed=True,
                    column=rule.column,
                    error_message=f"Unknown rule type: {rule.rule_type}",
                )

        except Exception as e:
            logger.error(
                "validation_rule_failed",
                rule=rule.name,
                table=table_name,
                error=str(e),
            )
            return ValidationResult(
                rule_name=rule.name,
                passed=False,
                column=rule.column,
                error_message=str(e),
            )

    async def _check_null(
        self,
        table_name: str,
        batch_id: str,
        rule: ValidationRule,
    ) -> ValidationResult:
        """Check for null values in a column."""
        query = f"""
            SELECT {rule.column} as val
            FROM {table_name}
            WHERE etl_batch_id = $1
              AND {rule.column} IS NULL
            LIMIT 100
        """

        assert self._pool is not None
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, batch_id)

        failed_values: list[Any] = [r["val"] for r in rows]

        return ValidationResult(
            rule_name=rule.name,
            passed=len(failed_values) == 0,
            column=rule.column,
            failed_values=[str(v) for v in failed_values],
        )

    async def _check_business_rule(
        self,
        table_name: str,
        batch_id: str,
        rule: ValidationRule,
    ) -> ValidationResult:
        """Check business rule constraints."""
        failed_values: list[Any] = []

        assert self._pool is not None
        async with self._pool.acquire() as conn:
            # Check value set constraint
            if rule.value_set is not None:
                values_str = ", ".join(f"'{v}'" for v in rule.value_set)
                query = f"""
                    SELECT {rule.column} as val
                    FROM {table_name}
                    WHERE etl_batch_id = $1
                      AND {rule.column} IS NOT NULL
                      AND {rule.column} NOT IN ({values_str})
                    LIMIT 100
                """
                rows = await conn.fetch(query, batch_id)
                failed_values.extend(r["val"] for r in rows)

            # Check min/max constraint (min_value may live on rule or in params)
            min_value = rule.min_value
            if min_value is None:
                min_value = rule.params.get("min_value")
            if min_value is not None:
                op = ">=" if rule.or_equal else ">"
                # BUG FIX: original query `AND {col} {op} {min}` returned rows
                # that SATISFY the rule. We want VIOLATIONS, so negate.
                query = f"""
                    SELECT {rule.column} as val
                    FROM {table_name}
                    WHERE etl_batch_id = $1
                      AND {rule.column} IS NOT NULL
                      AND NOT ({rule.column} {op} {min_value})
                    LIMIT 100
                """
                rows = await conn.fetch(query, batch_id)
                failed_values.extend(r["val"] for r in rows)

            # NOTE: column_a/column_b pair comparison (e.g. approved_date_after_order)
            # is not implemented yet — the rule passes silently. See plan Phase B4.

        return ValidationResult(
            rule_name=rule.name,
            passed=len(failed_values) == 0,
            column=rule.column,
            failed_values=[str(v) for v in failed_values],
        )

    async def _check_format(
        self,
        table_name: str,
        batch_id: str,
        rule: ValidationRule,
    ) -> ValidationResult:
        """Check format constraints (regex)."""
        if rule.regex_pattern is None:
            return ValidationResult(
                rule_name=rule.name,
                passed=True,
                column=rule.column,
            )

        # For regex checks, we need to fetch and check in Python
        # since PostgreSQL regex support varies
        query = f"""
            SELECT {rule.column} as val
            FROM {table_name}
            WHERE etl_batch_id = $1
              AND {rule.column} IS NOT NULL
            LIMIT 1000
        """

        assert self._pool is not None
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, batch_id)

        pattern = re.compile(rule.regex_pattern)
        failed_values: list[Any] = [
            r["val"] for r in rows if not pattern.match(str(r["val"]))
        ]

        return ValidationResult(
            rule_name=rule.name,
            passed=len(failed_values) == 0,
            column=rule.column,
            failed_values=[str(v) for v in failed_values],
        )

    async def _update_dq_status(self, summary: DQCheckSummary) -> None:
        """Update dq_status in ODS table based on check results.

        Three-tier update:
            1. quarantined — rows matching failed column values (critical failures)
            2. passed_with_warnings — remaining pending rows if warnings exist
            3. passed — all remaining pending rows
        """
        import json

        assert self._pool is not None
        async with self._pool.acquire() as conn:
            # 1. Quarantined — flag rows whose failing column matches a failed value.
            #    Group by column (from error_detail) to issue one UPDATE per column.
            if summary.quarantined_records:
                col_values: dict[str, set[str]] = {}
                col_errors: dict[str, list[dict[str, Any]]] = {}
                for rec in summary.quarantined_records:
                    col = rec.error_detail.get("column", "id")
                    col_values.setdefault(col, set()).add(rec.source_id)
                    col_errors.setdefault(col, []).append(
                        {
                            "rule": rec.rule_name,
                            "error_type": rec.error_type.value
                            if hasattr(rec.error_type, "value")
                            else str(rec.error_type),
                        }
                    )
                for col, values in col_values.items():
                    # Null-check failures have source_id="None" — handle via IS NULL
                    if "None" in values and len(values) == 1:
                        await conn.execute(
                            f"UPDATE {summary.table_name} "
                            "SET dq_status = 'quarantined', "
                            f"dq_errors = $2 "
                            f"WHERE etl_batch_id = $1 AND {col} IS NULL",
                            summary.batch_id,
                            json.dumps(col_errors[col]),
                        )
                    else:
                        # Match rows where the failing column equals any failed value.
                        # Exclude "None" sentinel from the value list.
                        real_values = [v for v in values if v != "None"]
                        if real_values:
                            placeholders = ", ".join(
                                f"${i + 2}" for i in range(len(real_values))
                            )
                            await conn.execute(
                                f"UPDATE {summary.table_name} "
                                "SET dq_status = 'quarantined', "
                                f"dq_errors = $2 "
                                f"WHERE etl_batch_id = $1 AND {col} IN ({placeholders})",
                                summary.batch_id,
                                json.dumps(col_errors[col]),
                                *real_values,
                            )

            # 2. Passed-with-warnings (records still pending and not quarantined)
            if summary.passed_with_warnings > 0:
                await conn.execute(
                    f"UPDATE {summary.table_name} "
                    "SET dq_status = 'passed_with_warnings' "
                    "WHERE etl_batch_id = $1 AND dq_status = 'pending'",
                    summary.batch_id,
                )

            # 3. Passed (remaining pending records)
            await conn.execute(
                f"UPDATE {summary.table_name} "
                "SET dq_status = 'passed' "
                "WHERE etl_batch_id = $1 AND dq_status = 'pending'",
                summary.batch_id,
            )

        logger.info("dq_status_updated", table=summary.table_name, batch_id=summary.batch_id)

    async def _insert_quarantine(self, records: list[QuarantineRecord]) -> None:
        """Insert quarantine records into the etl_quarantine table."""
        import json

        if not records:
            return

        rows = [
            (
                rec.batch_id,
                rec.source_table,
                rec.source_id,
                rec.error_type.value if hasattr(rec.error_type, "value") else str(rec.error_type),
                json.dumps(rec.error_detail),
                rec.severity.value if hasattr(rec.severity, "value") else str(rec.severity),
            )
            for rec in records
        ]

        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO etl_quarantine
                    (batch_id, source_table, source_id, error_type,
                     error_detail, severity, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, NOW())
                """,
                rows,
            )

        logger.info(
            "quarantine_records_inserted",
            count=len(records),
            batch_id=records[0].batch_id if records else None,
        )


# =============================================================================
# Exceptions
# =============================================================================


class DQError(HoneyBadgeError):
    """Base exception for data quality errors."""

    def __init__(self, message: str, code: str = "DQ_ERROR"):
        super().__init__(message, code)


class QuarantineThresholdExceeded(DQError):
    """Raised when quarantine record count exceeds threshold."""

    def __init__(self, threshold: int, actual: int):
        self.threshold = threshold
        self.actual = actual
        super().__init__(
            f"Quarantine threshold exceeded: {actual} records (threshold: {threshold})",
            "QUARANTINE_EXCEEDED",
        )
