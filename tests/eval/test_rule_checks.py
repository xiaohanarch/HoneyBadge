# tests/eval/test_rule_checks.py
"""Unit tests for eval.scorers.rule_checks — deterministic nGQL rule checks."""
from __future__ import annotations

from eval.scorers.rule_checks import run_check

# --- syntax_valid ---

def test_syntax_valid_passes_for_match_query() -> None:
    ngql = "MATCH (s:Supplier) RETURN s.Supplier.supplier_name AS name LIMIT 10"
    result = run_check({"type": "syntax_valid"}, ngql, user_context=None)
    assert result.passed


def test_syntax_valid_fails_for_empty_query() -> None:
    result = run_check({"type": "syntax_valid"}, "", user_context=None)
    assert not result.passed


def test_syntax_valid_fails_for_unbalanced_parens() -> None:
    result = run_check({"type": "syntax_valid"}, "MATCH (s:Supplier RETURN s", user_context=None)
    assert not result.passed


# --- has_limit ---

def test_has_limit_passes() -> None:
    ngql = "MATCH (s:Supplier) RETURN s LIMIT 10"
    result = run_check({"type": "has_limit"}, ngql, user_context=None)
    assert result.passed


def test_has_limit_fails_without_limit() -> None:
    ngql = "MATCH (s:Supplier) RETURN s"
    result = run_check({"type": "has_limit"}, ngql, user_context=None)
    assert not result.passed


# --- forbidden_ops_absent ---

def test_forbidden_ops_absent_passes_for_match() -> None:
    ngql = "MATCH (s:Supplier) RETURN s LIMIT 10"
    result = run_check(
        {"type": "forbidden_ops_absent", "ops": ["GO", "FETCH", "FIND PATH", "GET SUBGRAPH"]},
        ngql,
        user_context=None,
    )
    assert result.passed


def test_forbidden_ops_absent_fails_for_go() -> None:
    ngql = "GO 1 STEPS FROM 'vid' OVER SUPPLIES_ITEM YIELD id($$)"
    result = run_check(
        {"type": "forbidden_ops_absent", "ops": ["GO", "FETCH"]},
        ngql,
        user_context=None,
    )
    assert not result.passed


# --- expected_tags ---

def test_expected_tags_passes() -> None:
    ngql = "MATCH (s:Supplier)-[:PLACED_WITH]->(po:PurchaseOrder) RETURN po LIMIT 10"
    result = run_check(
        {"type": "expected_tags", "tags": ["Supplier", "PurchaseOrder"]},
        ngql,
        user_context=None,
    )
    assert result.passed


def test_expected_tags_fails_missing_tag() -> None:
    ngql = "MATCH (s:Supplier) RETURN s LIMIT 10"
    result = run_check(
        {"type": "expected_tags", "tags": ["Supplier", "PurchaseOrder"]},
        ngql,
        user_context=None,
    )
    assert not result.passed
    assert "PurchaseOrder" in result.detail


# --- order_by_uses_alias ---

def test_order_by_alias_passes() -> None:
    ngql = "MATCH (po:PurchaseOrder) RETURN po.PurchaseOrder.po_number AS po_number ORDER BY po_number DESC LIMIT 5"
    result = run_check({"type": "order_by_uses_alias"}, ngql, user_context=None)
    assert result.passed


def test_order_by_alias_fails_for_property_path() -> None:
    ngql = "MATCH (po:PurchaseOrder) RETURN po.PurchaseOrder.po_number AS po_number ORDER BY po.PurchaseOrder.order_date DESC LIMIT 5"
    result = run_check({"type": "order_by_uses_alias"}, ngql, user_context=None)
    assert not result.passed


# --- has_org_id ---

def test_has_org_id_passes_for_non_admin() -> None:
    ngql = "MATCH (s:Supplier) WHERE s.Supplier.org_id IN [1000] RETURN s LIMIT 10"
    result = run_check({"type": "has_org_id"}, ngql, user_context={"user_id": "analyst", "org_ids": [1000]})
    assert result.passed


def test_has_org_id_fails_for_non_admin_without_filter() -> None:
    ngql = "MATCH (s:Supplier) RETURN s LIMIT 10"
    result = run_check({"type": "has_org_id"}, ngql, user_context={"user_id": "analyst", "org_ids": [1000]})
    assert not result.passed


def test_has_org_id_skipped_for_admin() -> None:
    ngql = "MATCH (s:Supplier) RETURN s LIMIT 10"
    result = run_check({"type": "has_org_id"}, ngql, user_context={"user_id": "admin", "org_ids": None})
    assert result.passed  # admin doesn't need org_id filter
