"""Tests for PermissionEnforcer — the L3 hard enforcement gate."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

# conftest.py adds mcp-servers/honeybadge-nebula-mcp to sys.path
from permission_enforcer import PermissionEnforcer, PermissionViolationError

from honeybadge.permission_service.models import PermissionContext


def _ctx(**kwargs):
    defaults = {
        "user_id": "test",
        "allowed_processes": ["PTP"],
        "org_ids": None,
        "dept_ids": None,
        "data_scope": "ALL",
    }
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
        ngql = "MATCH (c:Currency) RETURN c.currency_code"
        ctx = _ctx(org_ids=[2])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        # Currency is a global MASTER — no org_id injection
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
        """LOOKUP ON Currency (global MASTER) should not get org_id injection."""
        ngql = "LOOKUP ON Currency YIELD id(vertex) AS cur_id"
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


class TestAnonymousNodeHandling:
    """Anonymous ``(:Tag)`` nodes previously bypassed L3 org_id injection.

    The ``_TAG_VAR_RE`` regex used ``\\w+`` (requiring at least one char),
    so ``(:PurchaseOrder)`` was never matched.  The fix auto-names anonymous
    PTP/OTC nodes to ``_gen0``, ``_gen1``, ... so org_id can be injected.
    """

    def test_anonymous_ptp_node_gets_named_and_filtered(self, enforcer):
        """``(:PurchaseOrder)`` should be renamed and get org_id injected."""
        ngql = "MATCH (:PurchaseOrder) RETURN count(*)"
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "_gen0:PurchaseOrder" in result_ngql
        assert "_gen0.PurchaseOrder.org_id IN [1021]" in result_ngql
        assert len(warnings) == 1

    def test_anonymous_master_node_not_renamed(self, enforcer):
        """``(:Currency)`` (global MASTER) should NOT be renamed — no org_id needed."""
        ngql = "MATCH (:Currency) RETURN count(*)"
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "_gen" not in result_ngql
        assert "org_id" not in result_ngql
        assert warnings == []

    def test_named_node_not_renamed(self, enforcer):
        """Already-named ``(po:PurchaseOrder)`` should not be renamed."""
        ngql = "MATCH (po:PurchaseOrder) RETURN po.po_number"
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "_gen" not in result_ngql
        assert "po.PurchaseOrder.org_id IN [1021]" in result_ngql

    def test_multiple_anonymous_nodes_get_unique_names(self, enforcer):
        """Two anonymous PTP nodes should get _gen0 and _gen1."""
        ngql = (
            "MATCH (:PurchaseOrder)-[:INVOICED_BY]->(:Invoice) "
            "RETURN count(*)"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "_gen0:PurchaseOrder" in result_ngql
        assert "_gen1:Invoice" in result_ngql
        assert "_gen0.PurchaseOrder.org_id IN [1021]" in result_ngql
        assert "_gen1.Invoice.org_id IN [1021]" in result_ngql
        assert len(warnings) == 2

    def test_anonymous_node_with_existing_where(self, enforcer):
        """Anonymous node + existing WHERE should append AND org_id."""
        ngql = (
            "MATCH (:PurchaseOrder) "
            "WHERE PurchaseOrder.status == 'APPROVED' "
            "RETURN count(*)"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "_gen0:PurchaseOrder" in result_ngql
        assert "_gen0.PurchaseOrder.org_id IN [1021]" in result_ngql
        assert "APPROVED" in result_ngql
        assert len(warnings) == 1


class TestMultiHopTraversal:
    """Multi-hop queries (MASTER → PTP, PTP → PTP) must inject org_id on
    every PTP/OTC node in the traversal path.

    Previously, only the first PTP node got org_id; anonymous nodes in the
    path were silently skipped, leaking cross-org data.
    """

    def test_master_to_ptp_hop_injects_on_ptp_only(self, enforcer):
        """Currency (global MASTER) → PurchaseOrder (PTP): only PO gets org_id."""
        ngql = (
            "MATCH (c:Currency)-[:PRICED_IN]->(po:PurchaseOrder) "
            "RETURN c.currency_code, po.po_number"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "po.PurchaseOrder.org_id IN [1021]" in result_ngql
        assert "c.org_id" not in result_ngql  # global MASTER: no filter
        assert len(warnings) == 1

    def test_ptp_to_ptp_hop_injects_on_both(self, enforcer):
        """PurchaseOrder (PTP) → Invoice (PTP): both get org_id."""
        ngql = (
            "MATCH (po:PurchaseOrder)-[:INVOICED_BY]->(i:Invoice) "
            "RETURN po.po_number, i.invoice_number"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "po.PurchaseOrder.org_id IN [1021]" in result_ngql
        assert "i.Invoice.org_id IN [1021]" in result_ngql
        assert len(warnings) == 2

    def test_three_hop_master_ptp_ptp(self, enforcer):
        """Currency → PO → Invoice: both PTP nodes get org_id."""
        ngql = (
            "MATCH (c:Currency)-[:PRICED_IN]->(po:PurchaseOrder)"
            "-[:INVOICED_BY]->(i:Invoice) "
            "RETURN c.currency_code, po.po_number, i.invoice_number"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "po.PurchaseOrder.org_id IN [1021]" in result_ngql
        assert "i.Invoice.org_id IN [1021]" in result_ngql
        assert "c.org_id" not in result_ngql
        assert len(warnings) == 2

    def test_anonymous_node_in_multi_hop(self, enforcer):
        """Anonymous PTP node in a multi-hop path gets named + filtered."""
        ngql = (
            "MATCH (c:Currency)-[:PRICED_IN]->(:PurchaseOrder)"
            "-[:INVOICED_BY]->(i:Invoice) "
            "RETURN count(*)"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        # Anonymous PO renamed
        assert "_gen0:PurchaseOrder" in result_ngql
        assert "_gen0.PurchaseOrder.org_id IN [1021]" in result_ngql
        # Named Invoice also filtered
        assert "i.Invoice.org_id IN [1021]" in result_ngql
        # Global MASTER Currency not filtered
        assert "c.org_id" not in result_ngql
        assert len(warnings) == 2

    def test_multi_hop_with_existing_org_filter_on_one_node(self, enforcer):
        """If one PTP node already has org_id, only the other gets injected."""
        ngql = (
            "MATCH (po:PurchaseOrder)-[:INVOICED_BY]->(i:Invoice) "
            "WHERE po.PurchaseOrder.org_id IN [1021] "
            "RETURN po.po_number, i.invoice_number"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        # po already has org_id — should not be double-injected
        assert result_ngql.count("po.PurchaseOrder.org_id IN") == 1
        # i does not have org_id — should be injected
        assert "i.Invoice.org_id IN [1021]" in result_ngql
        assert len(warnings) == 1

    def test_multi_hop_with_clause_both_nodes_filtered(self, enforcer):
        """Multi-hop + WITH clause: both PTP nodes filtered before WITH."""
        ngql = (
            "MATCH (po:PurchaseOrder)-[:INVOICED_BY]->(i:Invoice) "
            "WHERE po.PurchaseOrder.status == 'APPROVED' "
            "WITH count(i) AS invoice_count "
            "RETURN invoice_count"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        # Both org_id filters must appear before WITH
        with_pos = result_ngql.find("WITH")
        po_org_pos = result_ngql.find("po.PurchaseOrder.org_id IN [1021]")
        i_org_pos = result_ngql.find("i.Invoice.org_id IN [1021]")
        assert po_org_pos != -1, "po org_id should be present"
        assert i_org_pos != -1, "i org_id should be present"
        assert po_org_pos < with_pos, "po org_id must be before WITH"
        assert i_org_pos < with_pos, "i org_id must be before WITH"
        assert len(warnings) == 2

    def test_multi_hop_forbidden_tag_rejected(self, enforcer):
        """Multi-hop with a forbidden process tag should be rejected."""
        ngql = (
            "MATCH (po:PurchaseOrder)-[:LINKED_TO]->(so:SalesOrder) "
            "RETURN po.po_number, so.status"
        )
        ctx = _ctx(allowed_processes=["PTP"])
        with pytest.raises(PermissionViolationError) as exc:
            enforcer.enforce(ngql, ctx)
        assert "SalesOrder" in str(exc.value)

    def test_two_anonymous_ptp_nodes_with_existing_var_collision(self, enforcer):
        """Generated var names must not collide with existing variables."""
        ngql = (
            "MATCH (_gen0:Currency)-[:PRICED_IN]->(:PurchaseOrder) "
            "RETURN count(*)"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        # _gen0 is taken by Currency, so the anonymous PO should get _gen1
        assert "_gen1:PurchaseOrder" in result_ngql
        assert "_gen1.PurchaseOrder.org_id IN [1021]" in result_ngql
        assert len(warnings) == 1


class TestForbiddenOpsBroadened:
    """Additional nGQL operations that bypass L3 org_id injection.

    The original _FORBIDDEN_OPS_RE only covered GO [n STEPS] FROM,
    FETCH PROP ON, and FIND PATH.  These tests verify the broadened
    regex catches GO UPTO, GET SUBGRAPH, FETCH without PROP, and DDL.
    """

    def test_go_upto_steps_rejected(self, enforcer):
        ngql = 'GO UPTO 3 STEPS FROM "po:1021-00001" OVER PLACED_WITH YIELD id(vertex)'
        ctx = _ctx(org_ids=[1021])
        with pytest.raises(PermissionViolationError):
            enforcer.enforce(ngql, ctx)

    def test_go_without_steps_keyword_rejected(self, enforcer):
        ngql = 'GO 1 FROM "po:1021-00001" OVER PLACED_WITH YIELD id(vertex)'
        ctx = _ctx(org_ids=[1021])
        with pytest.raises(PermissionViolationError):
            enforcer.enforce(ngql, ctx)

    def test_get_subgraph_rejected(self, enforcer):
        ngql = 'GET SUBGRAPH 1 STEPS FROM "po:1021-00001" BOTH PLACED_WITH'
        ctx = _ctx(org_ids=[1021])
        with pytest.raises(PermissionViolationError):
            enforcer.enforce(ngql, ctx)

    def test_fetch_without_prop_rejected(self, enforcer):
        ngql = 'FETCH ON PurchaseOrder "po:1021-00001" YIELD PurchaseOrder.po_number'
        ctx = _ctx(org_ids=[1021])
        with pytest.raises(PermissionViolationError):
            enforcer.enforce(ngql, ctx)

    def test_delete_vertex_rejected(self, enforcer):
        ngql = 'DELETE VERTEX "po:1021-00001"'
        ctx = _ctx(org_ids=[1021])
        with pytest.raises(PermissionViolationError):
            enforcer.enforce(ngql, ctx)

    def test_update_vertex_rejected(self, enforcer):
        ngql = 'UPDATE VERTEX ON PurchaseOrder "po:1021-00001" SET status = "CLOSED"'
        ctx = _ctx(org_ids=[1021])
        with pytest.raises(PermissionViolationError):
            enforcer.enforce(ngql, ctx)

    def test_insert_vertex_rejected(self, enforcer):
        ngql = 'INSERT VERTEX PurchaseOrder VALUES "po:new":("new", "PENDING", 1021)'
        ctx = _ctx(org_ids=[1021])
        with pytest.raises(PermissionViolationError):
            enforcer.enforce(ngql, ctx)

    def test_change_password_rejected(self, enforcer):
        ngql = 'CHANGE PASSWORD FROM "root" TO "newpass"'
        ctx = _ctx(org_ids=None)
        with pytest.raises(PermissionViolationError):
            enforcer.enforce(ngql, ctx)


class TestStringLiteralSafety:
    """String literals in data values must not trigger false-positive rejections.

    The enforcer strips string literals before applying _FORBIDDEN_OPS_RE
    and the fallback tag-name scan, so queries containing phrases like
    'find path' or tag names like 'SalesOrder' in data values are safe.
    """

    def test_find_path_in_string_literal_not_rejected(self, enforcer):
        """WHERE clause containing 'find path' in a string value should pass."""
        ngql = (
            "MATCH (po:PurchaseOrder) "
            "WHERE po.PurchaseOrder.description == 'find path manually' "
            "RETURN po.po_number"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "MATCH" in result_ngql

    def test_go_in_string_literal_not_rejected(self, enforcer):
        """WHERE clause containing 'GO' in a string value should pass."""
        ngql = (
            "MATCH (po:PurchaseOrder) "
            "WHERE po.PurchaseOrder.note == 'GO label here' "
            "RETURN po.po_number"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "MATCH" in result_ngql

    def test_forbidden_tag_name_in_string_literal_not_rejected(self, enforcer):
        """A forbidden tag name appearing as a string value should not reject."""
        ngql = (
            "MATCH (po:PurchaseOrder) "
            "WHERE po.PurchaseOrder.note == 'SalesOrder reference' "
            "RETURN po.po_number"
        )
        ctx = _ctx(allowed_processes=["PTP"])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "MATCH" in result_ngql

    def test_return_keyword_in_string_literal_not_corrupted(self, enforcer):
        """'RETURN' appearing in a string value must not be treated as boundary."""
        ngql = (
            "MATCH (po:PurchaseOrder) "
            "WHERE po.PurchaseOrder.status == 'RETURN' "
            "RETURN po.po_number"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        # org_id should be injected before the real RETURN, not inside the string
        assert "po.PurchaseOrder.org_id IN [1021]" in result_ngql
        # The string 'RETURN' should still be intact
        assert "'RETURN'" in result_ngql


class TestMultiWithScope:
    """Multi-WITH queries must inject org_id in the correct scope.

    For ``MATCH (a) WITH a MATCH (b) RETURN ...``, each variable's org_id
    must be injected in its own WHERE scope (between its MATCH and the next
    boundary keyword), not before the first WITH where the variable is
    out of scope.
    """

    def test_second_match_after_with_gets_own_scope(self, enforcer):
        """Variable defined after WITH gets org_id in its own scope."""
        ngql = (
            "MATCH (po:PurchaseOrder) "
            "WHERE po.PurchaseOrder.status == 'APPROVED' "
            "WITH po "
            "MATCH (i:Invoice) "
            "RETURN po.po_number, i.invoice_number"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        # po org_id should be before the first WITH
        po_org_pos = result_ngql.find("po.PurchaseOrder.org_id IN [1021]")
        with_pos = result_ngql.find("WITH")
        assert po_org_pos != -1
        assert po_org_pos < with_pos, "po org_id must be before WITH"

        # i org_id should be AFTER the WITH (in i's own scope)
        i_org_pos = result_ngql.find("i.Invoice.org_id IN [1021]")
        assert i_org_pos != -1
        assert i_org_pos > with_pos, "i org_id must be after WITH (in i's scope)"

        assert len(warnings) == 2

    def test_both_variables_in_separate_scopes(self, enforcer):
        """Two variables in separate MATCH...WITH scopes both get filtered."""
        ngql = (
            "MATCH (po:PurchaseOrder) "
            "WITH po "
            "MATCH (i:Invoice) "
            "WITH po, i "
            "RETURN po.po_number, i.invoice_number"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        # po org_id before first WITH
        first_with = result_ngql.find("WITH")
        po_org = result_ngql.find("po.PurchaseOrder.org_id IN [1021]")
        assert po_org < first_with

        # i org_id after first WITH but before second WITH
        second_with = result_ngql.find("WITH", first_with + 4)
        i_org = result_ngql.find("i.Invoice.org_id IN [1021]")
        assert i_org > first_with
        assert i_org < second_with

        assert len(warnings) == 2


class TestOrgScopedMasterTags:
    """Org-scoped MASTER tags (Supplier, Customer, Item, etc.) must get
    org_id injection for non-admin users.

    These are business entities that are org-scoped in ERP (each org has its
    own suppliers, customers, items), unlike global reference data (Currency,
    UOM) which is not org-filtered.
    """

    def test_supplier_gets_org_id_for_non_admin(self, enforcer):
        """Supplier (org-scoped MASTER) must get org_id injected for analyst."""
        ngql = "MATCH (s:Supplier) RETURN s.Supplier.supplier_name"
        ctx = _ctx(org_ids=[1000])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "s.Supplier.org_id IN [1000]" in result_ngql
        assert len(warnings) == 1

    def test_supplier_no_injection_for_admin(self, enforcer):
        """Supplier with org_ids=None (admin) should not get org_id injected."""
        ngql = "MATCH (s:Supplier) RETURN s.Supplier.supplier_name"
        ctx = _ctx(org_ids=None)
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert result_ngql == ngql
        assert warnings == []

    def test_currency_not_filtered_for_non_admin(self, enforcer):
        """Currency (global MASTER) should NOT get org_id injection."""
        ngql = "MATCH (c:Currency) RETURN c.Currency.currency_code"
        ctx = _ctx(org_ids=[1000])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "org_id" not in result_ngql
        assert warnings == []

    def test_anonymous_supplier_gets_named_and_filtered(self, enforcer):
        """Anonymous ``(:Supplier)`` should be renamed and get org_id injected."""
        ngql = "MATCH (:Supplier) RETURN count(*)"
        ctx = _ctx(org_ids=[1000])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "_gen0:Supplier" in result_ngql
        assert "_gen0.Supplier.org_id IN [1000]" in result_ngql
        assert len(warnings) == 1

    def test_customer_gets_org_id_for_non_admin(self, enforcer):
        """Customer (org-scoped MASTER) must get org_id injected for analyst."""
        ngql = "MATCH (c:Customer) RETURN c.Customer.customer_name"
        ctx = _ctx(org_ids=[1000])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "c.Customer.org_id IN [1000]" in result_ngql
        assert len(warnings) == 1

    def test_lookup_on_supplier_gets_org_id(self, enforcer):
        """LOOKUP ON Supplier should get org_id injected for non-admin."""
        ngql = "LOOKUP ON Supplier YIELD id(vertex) AS sup_id"
        ctx = _ctx(org_ids=[1000])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "Supplier.org_id IN [1000]" in result_ngql
        assert len(warnings) == 1

    def test_supplier_with_existing_org_filter_not_double_injected(self, enforcer):
        """Supplier with existing org_id filter should not be double-injected."""
        ngql = (
            "MATCH (s:Supplier) "
            "WHERE s.Supplier.org_id IN [1000] "
            "RETURN s.Supplier.supplier_name"
        )
        ctx = _ctx(org_ids=[1000])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert result_ngql.count("s.Supplier.org_id IN") == 1
        assert warnings == []

    def test_supplier_and_purchase_order_both_filtered(self, enforcer):
        """Multi-hop Supplier → PO: both get org_id (both are org-scoped)."""
        ngql = (
            "MATCH (s:Supplier)-[:SUPPLIED_TO]->(po:PurchaseOrder) "
            "RETURN s.Supplier.supplier_name, po.PurchaseOrder.po_number"
        )
        ctx = _ctx(org_ids=[1021])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "s.Supplier.org_id IN [1021]" in result_ngql
        assert "po.PurchaseOrder.org_id IN [1021]" in result_ngql
        assert len(warnings) == 2
