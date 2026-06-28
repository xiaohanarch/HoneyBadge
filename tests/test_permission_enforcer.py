"""Tests for PermissionEnforcer — the L3 hard enforcement gate."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

# conftest.py adds mcp-servers/honeybadge-nebula-mcp to sys.path
from permission_enforcer import PermissionEnforcer, PermissionViolationError
from honeybadge.permission_service.models import PermissionContext


def _ctx(**kwargs):
    defaults = dict(
        user_id="test",
        allowed_processes=["PTP"],
        org_ids=None,
        dept_ids=None,
        data_scope="ALL",
    )
    defaults.update(kwargs)
    return PermissionContext(**defaults)


@pytest.fixture
def enforcer():
    return PermissionEnforcer()


class TestProcessTagRejection:
    def test_ptp_query_allowed_for_ptp_user(self, enforcer):
        ngql = "MATCH (po:PurchaseOrder) RETURN po.po_number"
        ctx = _ctx(allowed_processes=["PTP"])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert result_ngql == ngql
        assert warnings == []

    def test_otc_query_rejected_for_ptp_only_user(self, enforcer):
        ngql = "MATCH (so:SalesOrder) RETURN so.status"
        ctx = _ctx(allowed_processes=["PTP"])
        with pytest.raises(PermissionViolationError) as exc:
            enforcer.enforce(ngql, ctx)
        assert "SalesOrder" in str(exc.value)

    def test_ptp_query_rejected_for_otc_only_user(self, enforcer):
        ngql = "MATCH (inv:Invoice) RETURN inv.total_amount"
        ctx = _ctx(allowed_processes=["OTC"])
        with pytest.raises(PermissionViolationError):
            enforcer.enforce(ngql, ctx)

    def test_master_tag_always_allowed(self, enforcer):
        ngql = "MATCH (s:Supplier) RETURN s.supplier_name"
        ctx = _ctx(allowed_processes=["PTP"])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert result_ngql == ngql

    def test_mixed_master_and_ptp_allowed(self, enforcer):
        ngql = "MATCH (po:PurchaseOrder)-[:has_supplier]->(s:Supplier) RETURN po.po_number, s.supplier_name"
        ctx = _ctx(allowed_processes=["PTP"])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert result_ngql == ngql

    def test_ceo_can_query_both_processes(self, enforcer):
        ngql = "MATCH (po:PurchaseOrder), (so:SalesOrder) RETURN po.po_number, so.status"
        ctx = _ctx(allowed_processes=["PTP", "OTC"])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert result_ngql == ngql


class TestOrgFilterInjection:
    def test_no_injection_when_org_ids_is_none(self, enforcer):
        ngql = "MATCH (po:PurchaseOrder) RETURN po.po_number"
        ctx = _ctx(org_ids=None)
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert result_ngql == ngql
        assert warnings == []

    def test_injects_where_when_none_present(self, enforcer):
        ngql = "MATCH (po:PurchaseOrder) RETURN po.po_number"
        ctx = _ctx(org_ids=[2])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "po.PurchaseOrder.org_id IN [2]" in result_ngql
        assert len(warnings) == 1
        assert "PERMISSION WARNING" in warnings[0]

    def test_appends_and_to_existing_where(self, enforcer):
        ngql = "MATCH (po:PurchaseOrder) WHERE po.status=='APPROVED' RETURN po.po_number"
        ctx = _ctx(org_ids=[2])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "po.PurchaseOrder.org_id IN [2]" in result_ngql
        assert "po.status=='APPROVED'" in result_ngql
        assert len(warnings) == 1

    def test_no_injection_when_in_filter_already_present(self, enforcer):
        ngql = "MATCH (po:PurchaseOrder) WHERE po.org_id IN [2] RETURN po.po_number"
        ctx = _ctx(org_ids=[2])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        # Should not double-inject
        assert result_ngql.count("po.org_id IN") == 1
        assert warnings == []

    def test_no_injection_when_eq_filter_already_present(self, enforcer):
        """Existing var.org_id == N filter should also prevent injection."""
        ngql = "MATCH (po:PurchaseOrder) WHERE po.org_id == 2 RETURN po.po_number"
        ctx = _ctx(org_ids=[2])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "po.org_id IN" not in result_ngql
        assert warnings == []

    def test_master_tag_not_filtered_by_org(self, enforcer):
        ngql = "MATCH (s:Supplier) RETURN s.supplier_name"
        ctx = _ctx(org_ids=[2])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        # Supplier is MASTER — no org_id injection
        assert "org_id" not in result_ngql
        assert warnings == []

    def test_multiple_org_ids(self, enforcer):
        ngql = "MATCH (po:PurchaseOrder) RETURN po.po_number"
        ctx = _ctx(org_ids=[1, 2])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "po.PurchaseOrder.org_id IN [1, 2]" in result_ngql

    def test_with_clause_inserts_before_with_not_return(self, enforcer):
        """org_id must be inserted before WITH, not before RETURN.

        WITH ends the current WHERE scope. If org_id is inserted after WITH
        (e.g. before RETURN), the variable is out of scope and the query
        silently returns 0 results. This was Bug 2 in production: PENDING/
        CLOSED status queries returned 0 for subsidiary despite data existing.
        """
        ngql = (
            "MATCH (po:PurchaseOrder) "
            "WHERE po.PurchaseOrder.status == 'PENDING' "
            "WITH count(po) AS total "
            "RETURN total"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        # org_id must appear BEFORE WITH (in WHERE scope)
        org_id_pos = result_ngql.find("po.PurchaseOrder.org_id IN [1021]")
        with_pos = result_ngql.find("WITH")
        assert org_id_pos != -1, "org_id filter should be present"
        assert with_pos != -1, "WITH keyword should be present"
        assert org_id_pos < with_pos, (
            f"org_id filter must come BEFORE WITH "
            f"(got org_id at {org_id_pos}, WITH at {with_pos}). "
            f"Full result: {result_ngql}"
        )

    def test_with_clause_no_where_inserts_where_before_with(self, enforcer):
        """MATCH with WITH but no WHERE: WHERE should be inserted before WITH."""
        ngql = (
            "MATCH (po:PurchaseOrder) "
            "WITH count(po) AS total "
            "RETURN total"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        # WHERE should be inserted before WITH
        where_pos = result_ngql.find("WHERE")
        with_pos = result_ngql.find("WITH")
        assert where_pos != -1, "WHERE should be inserted"
        assert where_pos < with_pos, (
            f"WHERE must come BEFORE WITH "
            f"(got WHERE at {where_pos}, WITH at {with_pos}). "
            f"Full result: {result_ngql}"
        )
        assert "po.PurchaseOrder.org_id IN [1021]" in result_ngql


class TestLookupOnOrgFilterInjection:
    """Tests for LOOKUP ON Tag queries — previously bypassed L3 entirely.

    The _TAG_VAR_RE regex only matches (var:Tag) from MATCH clauses.
    Without _LOOKUP_TAG_RE, LOOKUP ON queries had no org_id injection,
    causing a CRITICAL data leak (subsidiary sees all orgs' data).
    """

    def test_lookup_with_where_gets_org_filter_appended(self, enforcer):
        """LOOKUP ON with existing WHERE should get AND org_id appended."""
        ngql = (
            "LOOKUP ON PurchaseOrder "
            "WHERE PurchaseOrder.total_amount > 800000 "
            "YIELD id(vertex) AS po_id, PurchaseOrder.org_id AS org_id"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "PurchaseOrder.org_id IN [1021]" in result_ngql
        assert "PurchaseOrder.total_amount > 800000" in result_ngql
        assert len(warnings) == 1

    def test_lookup_without_where_gets_where_inserted(self, enforcer):
        """LOOKUP ON without WHERE should get WHERE org_id before YIELD."""
        ngql = "LOOKUP ON PurchaseOrder YIELD id(vertex) AS po_id"
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "WHERE PurchaseOrder.org_id IN [1021]" in result_ngql
        assert "YIELD" in result_ngql
        assert len(warnings) == 1

    def test_lookup_no_injection_when_org_filter_present(self, enforcer):
        """LOOKUP ON with existing org_id filter should not be double-injected."""
        ngql = (
            "LOOKUP ON PurchaseOrder "
            "WHERE PurchaseOrder.org_id IN [1021] "
            "YIELD id(vertex) AS po_id"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert result_ngql.count("PurchaseOrder.org_id IN") == 1
        assert warnings == []

    def test_lookup_master_tag_not_filtered_by_org(self, enforcer):
        """LOOKUP ON Supplier (MASTER) should not get org_id injection."""
        ngql = "LOOKUP ON Supplier YIELD id(vertex) AS sup_id"
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "org_id" not in result_ngql
        assert warnings == []

    def test_lookup_forbidden_tag_rejected(self, enforcer):
        """LOOKUP on a forbidden process tag should raise PermissionViolationError."""
        ngql = "LOOKUP ON SalesOrder YIELD id(vertex) AS so_id"
        ctx = _ctx(allowed_processes=["PTP"])
        with pytest.raises(PermissionViolationError) as exc:
            enforcer.enforce(ngql, ctx)
        assert "SalesOrder" in str(exc.value)

    def test_lookup_multiple_org_ids(self, enforcer):
        """LOOKUP ON with multiple org_ids."""
        ngql = "LOOKUP ON PurchaseOrder YIELD id(vertex) AS po_id"
        ctx = _ctx(org_ids=[1, 2])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "PurchaseOrder.org_id IN [1, 2]" in result_ngql

    def test_lookup_no_injection_when_org_ids_none(self, enforcer):
        """LOOKUP ON with org_ids=None (full access) should not be modified."""
        ngql = "LOOKUP ON PurchaseOrder YIELD id(vertex) AS po_id"
        ctx = _ctx(org_ids=None)
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert result_ngql == ngql
        assert warnings == []


class TestForbiddenOperationsRejected:
    """GO, FETCH, FIND PATH bypass L3 org_id injection — hard-rejected.

    These operations use syntax without (var:Tag) patterns, so the enforcer
    cannot inject org_id filters. The LLM prompt restricts to MATCH/LOOKUP;
    this is the safety net for when the LLM doesn't comply.
    """

    def test_go_query_rejected(self, enforcer):
        ngql = 'GO 1 STEPS FROM "po:1021-00001" OVER PLACED_WITH YIELD $$.Supplier.supplier_name'
        ctx = _ctx(org_ids=[1021])
        with pytest.raises(PermissionViolationError) as exc:
            enforcer.enforce(ngql, ctx)
        assert "GO" in str(exc.value) or "不支持" in str(exc.value)

    def test_go_without_steps_rejected(self, enforcer):
        ngql = 'GO FROM "po:1021-00001" OVER PLACED_WITH YIELD id(vertex)'
        ctx = _ctx(org_ids=[1021])
        with pytest.raises(PermissionViolationError):
            enforcer.enforce(ngql, ctx)

    def test_fetch_prop_rejected(self, enforcer):
        ngql = 'FETCH PROP ON PurchaseOrder "po:1021-00001" YIELD PurchaseOrder.po_number'
        ctx = _ctx(org_ids=[1021])
        with pytest.raises(PermissionViolationError) as exc:
            enforcer.enforce(ngql, ctx)
        assert "FETCH" in str(exc.value) or "不支持" in str(exc.value)

    def test_find_path_rejected(self, enforcer):
        ngql = 'FIND SHORTEST PATH FROM "po:1021-00001" TO "sup:0001" OVER PLACED_WITH YIELD path'
        ctx = _ctx(org_ids=[1021])
        with pytest.raises(PermissionViolationError) as exc:
            enforcer.enforce(ngql, ctx)
        assert "FIND" in str(exc.value) or "不支持" in str(exc.value)

    def test_find_all_path_rejected(self, enforcer):
        ngql = 'FIND ALL PATH FROM "po:1000-00001" TO "sup:0001" OVER * YIELD path'
        ctx = _ctx(org_ids=[1021])
        with pytest.raises(PermissionViolationError):
            enforcer.enforce(ngql, ctx)

    def test_go_rejected_even_for_admin(self, enforcer):
        """GO is rejected even for admin (org_ids=None) — it's a syntax
        restriction, not a permission scope issue."""
        ngql = 'GO FROM "po:1000-00001" OVER PLACED_WITH YIELD id(vertex)'
        ctx = _ctx(org_ids=None)
        with pytest.raises(PermissionViolationError):
            enforcer.enforce(ngql, ctx)

    def test_match_still_works_alongside_forbidden(self, enforcer):
        """Ensure the forbidden-ops check doesn't false-positive on MATCH."""
        ngql = "MATCH (po:PurchaseOrder) WHERE po.PurchaseOrder.org_id == 1021 RETURN po.PurchaseOrder.po_number AS po_number LIMIT 10"
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "MATCH" in result_ngql
        assert "GO" not in result_ngql.upper().split("MATCH")[0]
