"""Tests for permission service models and config."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dataclasses import asdict

import pytest

from honeybadge.permission_service.config import PERMISSION_CONFIG, PROCESS_TAGS
from honeybadge.permission_service.models import PermissionContext


class TestPermissionContext:
    def test_dataclass_fields(self):
        ctx = PermissionContext(
            user_id="admin",
            allowed_processes=["PTP", "OTC"],
            org_ids=None,
            dept_ids=None,
            data_scope="ALL",
        )
        assert ctx.user_id == "admin"
        assert ctx.allowed_processes == ["PTP", "OTC"]
        assert ctx.org_ids is None
        assert ctx.data_scope == "ALL"

    def test_asdict(self):
        ctx = PermissionContext("analyst", ["PTP"], [1], None, "ORG")
        d = asdict(ctx)
        assert d["user_id"] == "analyst"
        assert d["org_ids"] == [1]


class TestProcessTags:
    def test_ptp_contains_purchase_order(self):
        assert "PurchaseOrder" in PROCESS_TAGS["PTP"]

    def test_otc_contains_sales_order(self):
        assert "SalesOrder" in PROCESS_TAGS["OTC"]

    def test_master_contains_supplier(self):
        assert "Supplier" in PROCESS_TAGS["MASTER"]

    def test_no_tag_in_multiple_categories(self):
        ptp = PROCESS_TAGS["PTP"]
        otc = PROCESS_TAGS["OTC"]
        master = PROCESS_TAGS["MASTER"]
        assert not ptp.intersection(otc)
        assert not ptp.intersection(master)
        assert not otc.intersection(master)


class TestPermissionConfig:
    def test_admin_has_all_processes(self):
        ctx = PERMISSION_CONFIG["admin"]
        assert "PTP" in ctx.allowed_processes
        assert "OTC" in ctx.allowed_processes

    def test_admin_has_no_org_restriction(self):
        ctx = PERMISSION_CONFIG["admin"]
        assert ctx.org_ids is None
        assert ctx.data_scope == "ALL"

    def test_procurement_lead_ptp_only(self):
        ctx = PERMISSION_CONFIG["procurement_lead"]
        assert ctx.allowed_processes == ["PTP"]
        assert ctx.org_ids is None

    def test_subsidiary_lead_restricted_to_org_1021(self):
        ctx = PERMISSION_CONFIG["subsidiary_lead"]
        assert "PTP" in ctx.allowed_processes
        assert "OTC" in ctx.allowed_processes
        assert ctx.org_ids == [1021]
        assert ctx.data_scope == "ORG"

    def test_analyst_restricted_to_org_1000(self):
        ctx = PERMISSION_CONFIG["analyst"]
        assert ctx.allowed_processes == ["PTP"]
        assert ctx.org_ids == [1000]

    def test_auditor_all_processes_no_restriction(self):
        ctx = PERMISSION_CONFIG["auditor"]
        assert "PTP" in ctx.allowed_processes
        assert "OTC" in ctx.allowed_processes
        assert ctx.org_ids is None
        assert ctx.data_scope == "ALL"


class TestPermissionServiceAPI:
    """Tests for the FastAPI service endpoints."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from honeybadge.permission_service.main import app
        return TestClient(app)

    def test_health_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_known_user_returns_200(self, client):
        r = client.get("/permissions/admin")
        assert r.status_code == 200
        data = r.json()
        assert data["user_id"] == "admin"
        assert "PTP" in data["allowed_processes"]
        assert "OTC" in data["allowed_processes"]
        assert data["org_ids"] is None
        assert data["data_scope"] == "ALL"

    def test_subsidiary_lead_restricted(self, client):
        r = client.get("/permissions/subsidiary_lead")
        assert r.status_code == 200
        data = r.json()
        assert data["org_ids"] == [1021]
        assert data["data_scope"] == "ORG"

    def test_unknown_user_returns_404(self, client):
        r = client.get("/permissions/nonexistent_user")
        assert r.status_code == 404

    def test_all_demo_users_reachable(self, client):
        for username in ["admin", "procurement_lead", "subsidiary_lead", "analyst", "auditor"]:
            r = client.get(f"/permissions/{username}")
            assert r.status_code == 200, f"Failed for {username}"
