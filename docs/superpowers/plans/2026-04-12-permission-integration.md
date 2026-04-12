# Permission System Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two-dimensional (process + org) access control to HoneyBadge, enforced via a standalone PermissionResolver service (soft layer: LLM prompt) and MCP PermissionEnforcer (hard layer: Cypher rewrite).

**Architecture:** A new FastAPI microservice (`honeybadge-permissions:8092`) serves `PermissionContext` per user. The graph-worker and analytics-worker call this service before every query, inject the context into the LLM prompt (soft enforcement), and pass it through to the MCP server which hard-enforces it via `PermissionEnforcer` before touching NebulaGraph.

**Tech Stack:** FastAPI, httpx (already in nebula-mcp deps), pytest, Docker Compose, NebulaGraph nGQL

---

## File Map

**New files:**
- `src/honeybadge/permission_service/models.py` — `PermissionContext` dataclass
- `src/honeybadge/permission_service/config.py` — `PROCESS_TAGS` + `PERMISSION_CONFIG` dict
- `src/honeybadge/permission_service/main.py` — FastAPI app, `GET /permissions/{user_id}`
- `src/honeybadge/permission_service/Dockerfile` — container image
- `mcp-servers/honeybadge-nebula-mcp/permission_enforcer.py` — `PermissionEnforcer` class
- `deploy/docker/nebula-demo-org2.ngql` — org_id=2 demo vertices + edges
- `tests/test_permission_service.py` — permission service unit tests
- `tests/test_permission_enforcer.py` — enforcer unit tests

**Modified files:**
- `src/honeybadge/server/auth.py` — add `procurement_lead`, `subsidiary_lead` to `DEMO_USERS`
- `tests/test_server_auth.py` — update count assertion, add tests for new users
- `mcp-servers/honeybadge-nebula-mcp/server.py` — add `get_user_permissions` tool + integrate `PermissionEnforcer` in `validate_and_execute_impl`
- `tests/test_nebula_mcp.py` — add tests for `get_user_permissions` + enforcer integration
- `deploy/docker/docker-compose.yaml` — add `honeybadge-permissions` service + `PERMISSION_SERVICE_URL` env to nebula-mcp
- `hiclaw/manager/agent/SOUL.md` — add user_id extraction + dispatch rule
- `hiclaw/workers/graph-worker/agent/SOUL.md` — add `get_user_permissions` step + prompt injection
- `hiclaw/workers/analytics-worker/agent/SOUL.md` — same as graph-worker

---

## Task 1: PermissionContext models

**Files:**
- Create: `src/honeybadge/permission_service/__init__.py`
- Create: `src/honeybadge/permission_service/models.py`
- Create: `tests/test_permission_service.py` (first batch of tests)

- [ ] **Step 1.1: Write failing tests for PermissionContext**

```python
# tests/test_permission_service.py
"""Tests for permission service models and config."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from honeybadge.permission_service.models import PermissionContext
from honeybadge.permission_service.config import PROCESS_TAGS, PERMISSION_CONFIG


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
        from dataclasses import asdict
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

    def test_subsidiary_lead_restricted_to_org_2(self):
        ctx = PERMISSION_CONFIG["subsidiary_lead"]
        assert "PTP" in ctx.allowed_processes
        assert "OTC" in ctx.allowed_processes
        assert ctx.org_ids == [2]
        assert ctx.data_scope == "ORG"

    def test_analyst_restricted_to_org_1(self):
        ctx = PERMISSION_CONFIG["analyst"]
        assert ctx.allowed_processes == ["PTP"]
        assert ctx.org_ids == [1]

    def test_auditor_all_processes_no_restriction(self):
        ctx = PERMISSION_CONFIG["auditor"]
        assert "PTP" in ctx.allowed_processes
        assert "OTC" in ctx.allowed_processes
        assert ctx.org_ids is None
```

- [ ] **Step 1.2: Run tests, verify they fail**

```
cd D:/dev/HoneyBadge
pytest tests/test_permission_service.py -v
```

Expected: `ModuleNotFoundError: No module named 'honeybadge.permission_service'`

- [ ] **Step 1.3: Create `__init__.py`**

```python
# src/honeybadge/permission_service/__init__.py
```
(empty file)

- [ ] **Step 1.4: Create `models.py`**

```python
# src/honeybadge/permission_service/models.py
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class PermissionContext:
    user_id: str
    allowed_processes: list[str]   # ["PTP"] / ["OTC"] / ["PTP", "OTC"]
    org_ids: list[int] | None      # None = all orgs; [2] = org_id=2 only
    dept_ids: list[int] | None     # reserved for future dept-level control
    data_scope: str                # "ALL" / "ORG" / "DEPT"
```

- [ ] **Step 1.5: Create `config.py`**

```python
# src/honeybadge/permission_service/config.py
from .models import PermissionContext

PROCESS_TAGS: dict[str, set[str]] = {
    "PTP": {
        "PurchaseRequisition", "PurchaseRequisitionLine",
        "PurchaseOrder", "PurchaseOrderLine",
        "Receipt", "ReceiptLine",
        "SupplierQualification",
        "Invoice", "InvoiceLine",
        "Payment", "PaymentBatch",
        "Contract",
    },
    "OTC": {
        "SalesOrder", "SalesOrderLine",
        "Shipment", "ShipmentLine",
        "ARInvoice", "ARReceipt",
    },
    "MASTER": {
        "Organization", "Employee", "Supplier", "Customer", "Item",
        "Warehouse", "BOM", "BOMComponent", "Currency", "UOM",
        "GLAccount", "GLJournalEntry", "GLJournalLine",
        "XLAEvent", "AccountingDistribution", "ApprovalRecord",
    },
}

PERMISSION_CONFIG: dict[str, PermissionContext] = {
    "admin": PermissionContext(
        user_id="admin",
        allowed_processes=["PTP", "OTC"],
        org_ids=None,
        dept_ids=None,
        data_scope="ALL",
    ),
    "procurement_lead": PermissionContext(
        user_id="procurement_lead",
        allowed_processes=["PTP"],
        org_ids=None,
        dept_ids=None,
        data_scope="ALL",
    ),
    "subsidiary_lead": PermissionContext(
        user_id="subsidiary_lead",
        allowed_processes=["PTP", "OTC"],
        org_ids=[2],
        dept_ids=None,
        data_scope="ORG",
    ),
    "analyst": PermissionContext(
        user_id="analyst",
        allowed_processes=["PTP"],
        org_ids=[1],
        dept_ids=None,
        data_scope="ORG",
    ),
    "auditor": PermissionContext(
        user_id="auditor",
        allowed_processes=["PTP", "OTC"],
        org_ids=None,
        dept_ids=None,
        data_scope="ALL",
    ),
}
```

- [ ] **Step 1.6: Run tests, verify they pass**

```
pytest tests/test_permission_service.py -v
```

Expected: all 13 tests PASS

- [ ] **Step 1.7: Commit**

```bash
git add src/honeybadge/permission_service/ tests/test_permission_service.py
git commit -m "feat(permissions): add PermissionContext models and config"
```

---

## Task 2: PermissionResolver FastAPI service + Dockerfile

**Files:**
- Create: `src/honeybadge/permission_service/main.py`
- Create: `src/honeybadge/permission_service/Dockerfile`
- Modify: `tests/test_permission_service.py` (add API tests)

- [ ] **Step 2.1: Add API tests to `tests/test_permission_service.py`**

Append this class at the bottom of `tests/test_permission_service.py`:

```python
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
        assert data["org_ids"] == [2]
        assert data["data_scope"] == "ORG"

    def test_unknown_user_returns_404(self, client):
        r = client.get("/permissions/nonexistent_user")
        assert r.status_code == 404

    def test_all_demo_users_reachable(self, client):
        for username in ["admin", "procurement_lead", "subsidiary_lead", "analyst", "auditor"]:
            r = client.get(f"/permissions/{username}")
            assert r.status_code == 200, f"Failed for {username}"
```

- [ ] **Step 2.2: Run new tests, verify they fail**

```
pytest tests/test_permission_service.py::TestPermissionServiceAPI -v
```

Expected: `ImportError` (main.py doesn't exist yet)

- [ ] **Step 2.3: Create `main.py`**

```python
# src/honeybadge/permission_service/main.py
from __future__ import annotations
from dataclasses import asdict

from fastapi import FastAPI, HTTPException

from .config import PERMISSION_CONFIG

app = FastAPI(
    title="HoneyBadge Permission Service",
    description="Returns PermissionContext for a given user_id.",
    version="1.0.0",
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "honeybadge-permissions"}


@app.get("/permissions/{user_id}")
async def get_permissions(user_id: str):
    ctx = PERMISSION_CONFIG.get(user_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
    return asdict(ctx)
```

- [ ] **Step 2.4: Run API tests, verify they pass**

```
pytest tests/test_permission_service.py -v
```

Expected: all tests PASS (including the new API tests)

- [ ] **Step 2.5: Create `Dockerfile`**

```dockerfile
# src/honeybadge/permission_service/Dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn
COPY src/honeybadge/__init__.py /app/honeybadge/__init__.py
COPY src/honeybadge/permission_service/ /app/honeybadge/permission_service/
RUN touch /app/honeybadge/__init__.py /app/honeybadge/permission_service/__init__.py
CMD ["uvicorn", "honeybadge.permission_service.main:app", "--host", "0.0.0.0", "--port", "8092"]
```

- [ ] **Step 2.6: Commit**

```bash
git add src/honeybadge/permission_service/main.py src/honeybadge/permission_service/Dockerfile tests/test_permission_service.py
git commit -m "feat(permissions): add PermissionResolver FastAPI service and Dockerfile"
```

---

## Task 3: Add demo users (procurement_lead, subsidiary_lead)

**Files:**
- Modify: `src/honeybadge/server/auth.py`
- Modify: `tests/test_server_auth.py`

- [ ] **Step 3.1: Update `tests/test_server_auth.py`**

In `tests/test_server_auth.py`, make these two changes:

Change line 24 (in `TestDemoUsers`):
```python
    def test_demo_users_has_three_entries(self):
        """DEMO_USERS should contain exactly three users."""
        assert len(DEMO_USERS) == 3
```
to:
```python
    def test_demo_users_has_five_entries(self):
        """DEMO_USERS should contain exactly five users."""
        assert len(DEMO_USERS) == 5
```

Also add these two new test methods inside `TestDemoUsers` (after the `test_auditor_user_exists` method):
```python
    def test_procurement_lead_user_exists(self):
        """procurement_lead user should be present."""
        assert "procurement_lead" in DEMO_USERS

    def test_subsidiary_lead_user_exists(self):
        """subsidiary_lead user should be present."""
        assert "subsidiary_lead" in DEMO_USERS

    def test_procurement_lead_fields(self):
        """procurement_lead should have correct fields."""
        user = DEMO_USERS["procurement_lead"]
        assert user["username"] == "procurement_lead"
        assert user["display_name"] == "采购部门领导"
        assert "analyst" in user["roles"]
        assert user["org_id"] == 1

    def test_subsidiary_lead_fields(self):
        """subsidiary_lead should have correct fields and org_id=2."""
        user = DEMO_USERS["subsidiary_lead"]
        assert user["username"] == "subsidiary_lead"
        assert user["display_name"] == "子公司领导"
        assert "analyst" in user["roles"]
        assert user["org_id"] == 2
```

- [ ] **Step 3.2: Run tests, verify they fail**

```
pytest tests/test_server_auth.py -v
```

Expected: `test_demo_users_has_five_entries` FAILS (count is still 3), `test_procurement_lead_user_exists` FAILS, `test_subsidiary_lead_user_exists` FAILS

- [ ] **Step 3.3: Update `src/honeybadge/server/auth.py`**

After the `"auditor"` entry in `DEMO_USERS` (around line 57), add:

```python
    "procurement_lead": {
        "id": "procurement_lead",
        "username": "procurement_lead",
        "password_hash": pwd_context.hash("lead123"),
        "display_name": "采购部门领导",
        "roles": ["analyst"],
        "org_id": 1,
    },
    "subsidiary_lead": {
        "id": "subsidiary_lead",
        "username": "subsidiary_lead",
        "password_hash": pwd_context.hash("lead123"),
        "display_name": "子公司领导",
        "roles": ["analyst"],
        "org_id": 2,
    },
```

- [ ] **Step 3.4: Run tests, verify they pass**

```
pytest tests/test_server_auth.py -v
```

Expected: all tests PASS

- [ ] **Step 3.5: Commit**

```bash
git add src/honeybadge/server/auth.py tests/test_server_auth.py
git commit -m "feat(auth): add procurement_lead and subsidiary_lead demo users"
```

---

## Task 4: PermissionEnforcer

**Files:**
- Create: `mcp-servers/honeybadge-nebula-mcp/permission_enforcer.py`
- Create: `tests/test_permission_enforcer.py`

- [ ] **Step 4.1: Write failing tests**

```python
# tests/test_permission_enforcer.py
"""Tests for PermissionEnforcer — the L3 hard enforcement gate."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import importlib.util
import pytest

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_enforcer_path = os.path.join(
    _project_root, "mcp-servers", "honeybadge-nebula-mcp", "permission_enforcer.py"
)
_spec = importlib.util.spec_from_file_location("permission_enforcer", _enforcer_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

PermissionEnforcer = _mod.PermissionEnforcer
PermissionViolationError = _mod.PermissionViolationError

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


class TestProcessTagRejection:
    def test_ptp_query_allowed_for_ptp_user(self):
        enforcer = PermissionEnforcer()
        ngql = "MATCH (po:PurchaseOrder) RETURN po.po_number"
        ctx = _ctx(allowed_processes=["PTP"])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert result_ngql == ngql
        assert warnings == []

    def test_otc_query_rejected_for_ptp_only_user(self):
        enforcer = PermissionEnforcer()
        ngql = "MATCH (so:SalesOrder) RETURN so.status"
        ctx = _ctx(allowed_processes=["PTP"])
        with pytest.raises(PermissionViolationError) as exc:
            enforcer.enforce(ngql, ctx)
        assert "SalesOrder" in str(exc.value)

    def test_ptp_query_rejected_for_otc_only_user(self):
        enforcer = PermissionEnforcer()
        ngql = "MATCH (inv:Invoice) RETURN inv.total_amount"
        ctx = _ctx(allowed_processes=["OTC"])
        with pytest.raises(PermissionViolationError):
            enforcer.enforce(ngql, ctx)

    def test_master_tag_always_allowed(self):
        enforcer = PermissionEnforcer()
        ngql = "MATCH (s:Supplier) RETURN s.supplier_name"
        ctx = _ctx(allowed_processes=["PTP"])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert result_ngql == ngql

    def test_mixed_master_and_ptp_allowed(self):
        enforcer = PermissionEnforcer()
        ngql = "MATCH (po:PurchaseOrder)-[:has_supplier]->(s:Supplier) RETURN po.po_number, s.supplier_name"
        ctx = _ctx(allowed_processes=["PTP"])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert result_ngql == ngql

    def test_ceo_can_query_both_processes(self):
        enforcer = PermissionEnforcer()
        ngql = "MATCH (po:PurchaseOrder), (so:SalesOrder) RETURN po.po_number, so.status"
        ctx = _ctx(allowed_processes=["PTP", "OTC"])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert result_ngql == ngql


class TestOrgFilterInjection:
    def test_no_injection_when_org_ids_is_none(self):
        enforcer = PermissionEnforcer()
        ngql = "MATCH (po:PurchaseOrder) RETURN po.po_number"
        ctx = _ctx(org_ids=None)
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert result_ngql == ngql
        assert warnings == []

    def test_injects_where_when_none_present(self):
        enforcer = PermissionEnforcer()
        ngql = "MATCH (po:PurchaseOrder) RETURN po.po_number"
        ctx = _ctx(org_ids=[2])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "po.org_id IN [2]" in result_ngql
        assert len(warnings) == 1
        assert "PERMISSION WARNING" in warnings[0]

    def test_appends_and_to_existing_where(self):
        enforcer = PermissionEnforcer()
        ngql = "MATCH (po:PurchaseOrder) WHERE po.status == 'APPROVED' RETURN po.po_number"
        ctx = _ctx(org_ids=[2])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "po.org_id IN [2]" in result_ngql
        assert "po.status == 'APPROVED'" in result_ngql
        assert len(warnings) == 1

    def test_no_injection_when_filter_already_present(self):
        enforcer = PermissionEnforcer()
        ngql = "MATCH (po:PurchaseOrder) WHERE po.org_id IN [2] RETURN po.po_number"
        ctx = _ctx(org_ids=[2])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        # Should not double-inject
        assert result_ngql.count("po.org_id IN") == 1
        assert warnings == []

    def test_master_tag_not_filtered_by_org(self):
        enforcer = PermissionEnforcer()
        ngql = "MATCH (s:Supplier) RETURN s.supplier_name"
        ctx = _ctx(org_ids=[2])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        # Supplier is MASTER — no org_id injection
        assert "org_id" not in result_ngql
        assert warnings == []

    def test_multiple_org_ids(self):
        enforcer = PermissionEnforcer()
        ngql = "MATCH (po:PurchaseOrder) RETURN po.po_number"
        ctx = _ctx(org_ids=[1, 2])
        result_ngql, warnings = enforcer.enforce(ngql, ctx)
        assert "po.org_id IN [1, 2]" in result_ngql
```

- [ ] **Step 4.2: Run tests, verify they fail**

```
pytest tests/test_permission_enforcer.py -v
```

Expected: `FileNotFoundError` or `ModuleNotFoundError` (permission_enforcer.py doesn't exist)

- [ ] **Step 4.3: Create `permission_enforcer.py`**

```python
# mcp-servers/honeybadge-nebula-mcp/permission_enforcer.py
"""L3 hard enforcement for NebulaGraph queries.

Parses (var:Tag) patterns from MATCH clauses and:
  1. Hard-rejects forbidden process tags
  2. Auto-injects missing org_id filters for org-scoped users
"""
from __future__ import annotations

import re
import sys
import os

# Allow running standalone (adds src/ to path)
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_project_root, "src"))

from honeybadge.permission_service.config import PROCESS_TAGS
from honeybadge.permission_service.models import PermissionContext


class PermissionViolationError(Exception):
    """Raised when a query accesses a forbidden process."""


# Regex to extract (varname:TagName) from MATCH clauses
_TAG_VAR_RE = re.compile(r'\((\w+):(\w+)\)')


def _get_tag_category(tag: str) -> str | None:
    """Return 'PTP', 'OTC', 'MASTER', or None if unknown tag."""
    for category, tags in PROCESS_TAGS.items():
        if tag in tags:
            return category
    return None


def _has_org_filter(ngql: str, var: str) -> bool:
    """Return True if ngql already contains an org_id filter for the given variable."""
    # Matches: var.org_id IN [ or var.org_id ==
    pattern = re.compile(rf'{re.escape(var)}\.org_id\s+IN\b', re.IGNORECASE)
    return bool(pattern.search(ngql))


def _inject_org_filter(ngql: str, var: str, org_ids: list[int]) -> str:
    """Inject org_id filter for `var` into the WHERE clause."""
    ids_str = ", ".join(str(i) for i in org_ids)
    condition = f"{var}.org_id IN [{ids_str}]"

    # If WHERE already exists, append AND
    where_re = re.compile(r'\bWHERE\b', re.IGNORECASE)
    if where_re.search(ngql):
        # Insert before RETURN/YIELD by finding the first of those keywords
        return_re = re.compile(r'\b(RETURN|YIELD)\b', re.IGNORECASE)
        match = return_re.search(ngql)
        if match:
            insert_pos = match.start()
            return ngql[:insert_pos] + f"AND {condition} " + ngql[insert_pos:]
        # Fallback: append at end
        return ngql + f" AND {condition}"
    else:
        # Insert WHERE before RETURN/YIELD
        return_re = re.compile(r'\b(RETURN|YIELD)\b', re.IGNORECASE)
        match = return_re.search(ngql)
        if match:
            insert_pos = match.start()
            return ngql[:insert_pos] + f"WHERE {condition} " + ngql[insert_pos:]
        return ngql + f" WHERE {condition}"


class PermissionEnforcer:
    """Hard enforcement gate for NebulaGraph queries.

    Usage:
        enforcer = PermissionEnforcer()
        ngql, warnings = enforcer.enforce(ngql, permission_context)
        # ngql is safe to execute; warnings list any auto-injected filters
    """

    def enforce(
        self, ngql: str, ctx: PermissionContext
    ) -> tuple[str, list[str]]:
        """Enforce permissions on an nGQL statement.

        Returns:
            (modified_ngql, warnings) where modified_ngql has org filters injected.

        Raises:
            PermissionViolationError: if the query accesses a forbidden process tag.
        """
        warnings: list[str] = []
        tag_vars = _TAG_VAR_RE.findall(ngql)  # list of (var, tag) tuples

        # --- 1. Process tag check (hard reject) ---
        for var, tag in tag_vars:
            category = _get_tag_category(tag)
            if category is None or category == "MASTER":
                continue  # unknown or master tags are always allowed
            if category not in ctx.allowed_processes:
                raise PermissionViolationError(
                    f"无权访问 {category} 数据: tag '{tag}' 不在允许的流程范围内"
                )

        # --- 2. Org filter auto-injection ---
        if ctx.org_ids is None:
            return ngql, warnings  # full org access, no injection needed

        for var, tag in tag_vars:
            category = _get_tag_category(tag)
            if category is None or category == "MASTER":
                continue  # master data: no org filter required
            if not _has_org_filter(ngql, var):
                ngql = _inject_org_filter(ngql, var, ctx.org_ids)
                ids_str = ", ".join(str(i) for i in ctx.org_ids)
                warnings.append(
                    f"[PERMISSION WARNING] 自动注入 org_id 过滤条件: {var}:{tag} "
                    f"WHERE {var}.org_id IN [{ids_str}]"
                )

        return ngql, warnings
```

- [ ] **Step 4.4: Run tests, verify they pass**

```
pytest tests/test_permission_enforcer.py -v
```

Expected: all 12 tests PASS

- [ ] **Step 4.5: Commit**

```bash
git add mcp-servers/honeybadge-nebula-mcp/permission_enforcer.py tests/test_permission_enforcer.py
git commit -m "feat(permissions): add PermissionEnforcer with process tag rejection and org filter injection"
```

---

## Task 5: Integrate PermissionEnforcer into MCP server

**Files:**
- Modify: `mcp-servers/honeybadge-nebula-mcp/server.py`
- Modify: `tests/test_nebula_mcp.py`

- [ ] **Step 5.1: Add tests for new MCP tool and enforcer integration**

Append to `tests/test_nebula_mcp.py`:

```python
# At the top of the file, also import these (add to existing imports section):
# from honeybadge.permission_service.models import PermissionContext
# (add sys.path insert for src if not already there)

class TestGetUserPermissions:
    """Tests for the get_user_permissions MCP tool impl."""

    @pytest.mark.asyncio
    async def test_known_user_returns_permissions(self):
        """get_user_permissions should return PermissionContext for known user."""
        import importlib.util as ilu
        import os
        _pr = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        _sp = ilu.spec_from_file_location(
            "nebula_mcp_server2",
            os.path.join(_pr, "mcp-servers", "honeybadge-nebula-mcp", "server.py"),
        )
        _m = ilu.module_from_spec(_sp)
        _sp.loader.exec_module(_m)
        get_user_permissions_impl = _m.get_user_permissions_impl

        result = await get_user_permissions_impl("admin")
        assert result["user_id"] == "admin"
        assert "PTP" in result["allowed_processes"]
        assert result["data_scope"] == "ALL"

    @pytest.mark.asyncio
    async def test_unknown_user_returns_default(self):
        import importlib.util as ilu
        import os
        _pr = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        _sp = ilu.spec_from_file_location(
            "nebula_mcp_server3",
            os.path.join(_pr, "mcp-servers", "honeybadge-nebula-mcp", "server.py"),
        )
        _m = ilu.module_from_spec(_sp)
        _sp.loader.exec_module(_m)
        get_user_permissions_impl = _m.get_user_permissions_impl

        result = await get_user_permissions_impl("google_12345")
        # Unknown Google users get restrictive default
        assert result["allowed_processes"] == ["PTP"]
        assert result["org_ids"] == [1]


class TestValidateAndExecuteWithPermissions:
    """Tests for permission enforcement inside validate_and_execute_impl."""

    @pytest.fixture
    def validator(self):
        from honeybadge.protocols.validator import NgqlValidator
        return NgqlValidator()

    @pytest.fixture
    def nebula(self):
        from honeybadge.db.nebula import NebulaQueryResult
        class FakeNebula:
            async def execute(self, ngql, space=None):
                return NebulaQueryResult(columns=["po_number"], rows=[{"po_number": "PO-001"}], execution_time_ms=1, success=True)
        return FakeNebula()

    @pytest.mark.asyncio
    async def test_forbidden_process_returns_permission_denied(self, nebula, validator):
        from honeybadge.db.nebula import NebulaQueryResult
        # Load the impl
        import importlib.util as ilu
        import os
        _pr = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        _sp = ilu.spec_from_file_location(
            "nebula_mcp_server4",
            os.path.join(_pr, "mcp-servers", "honeybadge-nebula-mcp", "server.py"),
        )
        _m = ilu.module_from_spec(_sp)
        _sp.loader.exec_module(_m)
        validate_and_execute_impl = _m.validate_and_execute_impl

        user_context = {
            "user_id": "analyst",
            "permissions": {
                "user_id": "analyst",
                "allowed_processes": ["PTP"],
                "org_ids": [1],
                "dept_ids": None,
                "data_scope": "ORG",
            }
        }
        result = await validate_and_execute_impl(
            nebula, validator,
            "MATCH (so:SalesOrder) RETURN so.status",
            user_context=user_context,
        )
        assert result["success"] is False
        assert result["error"] == "L3_PERMISSION"
        assert "SalesOrder" in result["details"][0]["message"]

    @pytest.mark.asyncio
    async def test_org_filter_auto_injected(self, nebula, validator):
        import importlib.util as ilu
        import os
        _pr = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        _sp = ilu.spec_from_file_location(
            "nebula_mcp_server5",
            os.path.join(_pr, "mcp-servers", "honeybadge-nebula-mcp", "server.py"),
        )
        _m = ilu.module_from_spec(_sp)
        _sp.loader.exec_module(_m)
        validate_and_execute_impl = _m.validate_and_execute_impl

        user_context = {
            "user_id": "subsidiary_lead",
            "permissions": {
                "user_id": "subsidiary_lead",
                "allowed_processes": ["PTP", "OTC"],
                "org_ids": [2],
                "dept_ids": None,
                "data_scope": "ORG",
            }
        }
        result = await validate_and_execute_impl(
            nebula, validator,
            "MATCH (po:PurchaseOrder) RETURN po.po_number",
            user_context=user_context,
        )
        assert result["success"] is True
        assert "warnings" in result
        assert any("PERMISSION WARNING" in w for w in result["warnings"])
```

- [ ] **Step 5.2: Run new tests, verify they fail**

```
pytest tests/test_nebula_mcp.py::TestGetUserPermissions tests/test_nebula_mcp.py::TestValidateAndExecuteWithPermissions -v
```

Expected: `AttributeError: module has no attribute 'get_user_permissions_impl'`

- [ ] **Step 5.3: Modify `mcp-servers/honeybadge-nebula-mcp/server.py`**

At the top of server.py, after the existing imports (around line 30), add:

```python
import sys as _sys
_sys.path.insert(0, os.path.join(_project_root, "mcp-servers", "honeybadge-nebula-mcp"))
from permission_enforcer import PermissionEnforcer, PermissionViolationError
from honeybadge.permission_service.config import PERMISSION_CONFIG
from dataclasses import asdict
```

Add a module-level constant (after the existing `_WRITE_OPS` constant):

```python
PERMISSION_SERVICE_URL: str = os.environ.get(
    "PERMISSION_SERVICE_URL", "http://honeybadge-permissions:8092"
)

_DEFAULT_PERMISSION = {
    "user_id": "unknown",
    "allowed_processes": ["PTP"],
    "org_ids": [1],
    "dept_ids": None,
    "data_scope": "ORG",
}
```

Add a new impl function (before the MCP tool wrappers section):

```python
async def get_user_permissions_impl(user_id: str) -> dict:
    """Fetch PermissionContext from PermissionResolver, with local fallback.

    First checks PERMISSION_CONFIG (local dict) for instant lookup.
    Falls back to HTTP call to PERMISSION_SERVICE_URL.
    Unknown users (e.g. Google SSO) receive a restrictive default.
    """
    from honeybadge.permission_service.models import PermissionContext

    # Local fast path
    ctx = PERMISSION_CONFIG.get(user_id)
    if ctx is not None:
        return asdict(ctx)

    # Remote call
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{PERMISSION_SERVICE_URL}/permissions/{user_id}")
            if r.status_code == 200:
                return r.json()
    except Exception as exc:
        logger.warning("permission_service_unreachable", user_id=user_id, error=str(exc))

    # Default: restrictive (PTP only, org_id=[1])
    logger.warning("using_default_permissions", user_id=user_id)
    return {**_DEFAULT_PERMISSION, "user_id": user_id}
```

Replace the L3 block inside `validate_and_execute_impl` (the `if user_context:` block, lines ~296-304):

```python
    # --- L3: Permission enforcement (PermissionEnforcer) -------------------
    if user_context and user_context.get("permissions"):
        from honeybadge.permission_service.models import PermissionContext
        try:
            perm_dict = user_context["permissions"]
            ctx = PermissionContext(**perm_dict)
            enforcer = PermissionEnforcer()
            ngql, perm_warnings = enforcer.enforce(ngql, ctx)
        except PermissionViolationError as exc:
            return {
                "success": False,
                "error": "L3_PERMISSION",
                "details": [{"code": "E300", "message": str(exc)}],
                "trace_id": trace_id,
            }
    else:
        perm_warnings = []
```

Update the success return at the end of `validate_and_execute_impl` to include `perm_warnings`:

```python
    return {
        "success": True,
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "execution_time_ms": result.execution_time_ms,
        "trace_id": trace_id,
        "warnings": perm_warnings,
    }
```

Add the MCP tool wrapper for `get_user_permissions` (in the MCP Tool wrappers section):

```python
@mcp.tool()
async def get_user_permissions(user_id: str) -> dict:
    """Fetch PermissionContext for a user from the PermissionResolver service.

    Workers MUST call this as the first step before any query.
    Returns a PermissionContext dict with allowed_processes, org_ids, data_scope.

    Args:
        user_id: Plain username (e.g. 'admin', 'subsidiary_lead').
                 Extract from the 'username' claim in the x-hb-auth JWT.
    """
    return await get_user_permissions_impl(user_id)
```

- [ ] **Step 5.4: Run all MCP tests**

```
pytest tests/test_nebula_mcp.py -v
```

Expected: all tests PASS (existing + new ones)

- [ ] **Step 5.5: Run full test suite**

```
pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 5.6: Commit**

```bash
git add mcp-servers/honeybadge-nebula-mcp/server.py tests/test_nebula_mcp.py
git commit -m "feat(mcp): add get_user_permissions tool and PermissionEnforcer L3 integration"
```

---

## Task 6: Docker deployment

**Files:**
- Modify: `deploy/docker/docker-compose.yaml`
- Create: `deploy/docker/nebula-demo-org2.ngql`

- [ ] **Step 6.1: Add `honeybadge-permissions` service to `docker-compose.yaml`**

After the `honeybadge-auth` service block (around line 516), add:

```yaml
  # =============================================================================
  # HoneyBadge Permission Service
  # Returns PermissionContext per user for L3 enforcement.
  # =============================================================================

  honeybadge-permissions:
    build:
      context: ../..
      dockerfile: src/honeybadge/permission_service/Dockerfile
    container_name: honeybadge-permissions
    hostname: honeybadge-permissions
    restart: unless-stopped
    ports:
      - "8092:8092"
    networks:
      - honeybadge-net
    healthcheck:
      test: ["CMD", "python", "-c", "import socket; s=socket.create_connection(('localhost',8092),2); s.close()"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    labels:
      com.honeybadge.service: "honeybadge-permissions"
      com.honeybadge.version: "${IMAGE_TAG:-latest}"
```

Also add `PERMISSION_SERVICE_URL` environment variable to the `honeybadge-nebula-mcp` service. Find the `honeybadge-nebula-mcp` service in docker-compose.yaml and add to its `environment:` section:

```yaml
      - PERMISSION_SERVICE_URL=http://honeybadge-permissions:8092
```

- [ ] **Step 6.2: Create `deploy/docker/nebula-demo-org2.ngql`**

```ngql
# ============================================================
# HoneyBadge NebulaGraph Demo Data — Subsidiary (org_id=2)
#
# Run after init-nebula.sh to load org_id=2 demo data:
#   bash deploy/docker/init-nebula.sh  (schema + indexes)
#   Then load this file via nebula-console or init-nebula.sh
#
# Purpose: subsidiary_lead (org_ids=[2]) needs data to query.
# ============================================================
USE honeybadge;

# Supplier (MASTER — visible to all users)
INSERT VERTEX Supplier(supplier_number, supplier_name, supplier_type, status, country, city, currency, org_id, is_active, created_at, updated_at)
  VALUES "supplier-org2-001":("SUP-ORG2-001", "华南供应商A", "DIRECT", "ACTIVE", "CN", "广州", "CNY", 2, true, now(), now());

# PurchaseOrder for org_id=2
INSERT VERTEX PurchaseOrder(po_number, po_type, status, buyer, order_date, total_amount, currency, org_id, is_active, created_at, updated_at)
  VALUES "po-org2-001":("PO-ORG2-001", "STANDARD", "APPROVED", "李四", now(), 580000.00, "CNY", 2, true, now(), now());

INSERT VERTEX PurchaseOrder(po_number, po_type, status, buyer, order_date, total_amount, currency, org_id, is_active, created_at, updated_at)
  VALUES "po-org2-002":("PO-ORG2-002", "BLANKET", "OPEN", "王五", now(), 320000.00, "CNY", 2, true, now(), now());

# Receipt for org_id=2
INSERT VERTEX Receipt(receipt_number, receipt_type, receipt_date, status, receiver, org_id, is_active, created_at, updated_at)
  VALUES "receipt-org2-001":("RCV-ORG2-001", "STANDARD", now(), "RECEIVED", "赵六", 2, true, now(), now());

# Invoice for org_id=2
INSERT VERTEX Invoice(invoice_number, invoice_type, invoice_date, status, total_amount, currency, org_id, is_active, created_at, updated_at)
  VALUES "inv-org2-001":("INV-ORG2-001", "STANDARD", now(), "POSTED", 580000.00, "CNY", 2, true, now(), now());

# SalesOrder for org_id=2 (tests OTC access for subsidiary_lead)
INSERT VERTEX SalesOrder(order_number, order_type, status, customer_id, order_date, total_amount, currency, org_id, is_active, created_at, updated_at)
  VALUES "so-org2-001":("SO-ORG2-001", "STANDARD", "BOOKED", "customer-org2-001", now(), 750000.00, "CNY", 2, true, now(), now());

# Edges
INSERT EDGE placed_with() VALUES "po-org2-001" -> "supplier-org2-001":();
INSERT EDGE has_receipt() VALUES "po-org2-001" -> "receipt-org2-001":();
INSERT EDGE has_invoice() VALUES "receipt-org2-001" -> "inv-org2-001":();
```

- [ ] **Step 6.3: Verify docker-compose syntax**

```bash
cd deploy/docker && docker compose config --quiet && echo "Syntax OK"
```

Expected: `Syntax OK` (no errors)

- [ ] **Step 6.4: Commit**

```bash
git add deploy/docker/docker-compose.yaml deploy/docker/nebula-demo-org2.ngql
git commit -m "feat(deploy): add honeybadge-permissions service and org_id=2 demo data"
```

---

## Task 7: Update Manager SOUL.md

**Files:**
- Modify: `hiclaw/manager/agent/SOUL.md`

- [ ] **Step 7.1: Add user_id extraction + dispatch rule to Manager SOUL**

In `hiclaw/manager/agent/SOUL.md`, add a new section **after** the `# Security Rules` section:

```markdown
# User Identity Propagation

When a user message contains an `x-hb-auth` header field (a signed JWT):

1. Decode the JWT payload by Base64url-decoding the middle segment (between the two dots).
2. Extract the `username` claim (plain username like "admin", "subsidiary_lead").
3. When dispatching a task to a Worker, include `user_id: <username>` in the task payload.

Example task dispatch format:
```
Task for graph-worker:
user_id: "subsidiary_lead"
question: "查询本公司的所有采购订单"
```

If no `x-hb-auth` field is present, omit `user_id` from the task (Workers will use anonymous defaults).
```

- [ ] **Step 7.2: Commit**

```bash
git add hiclaw/manager/agent/SOUL.md
git commit -m "feat(hiclaw): update Manager SOUL to propagate user_id to Workers"
```

---

## Task 8: Update Worker SOULs

**Files:**
- Modify: `hiclaw/workers/graph-worker/agent/SOUL.md`
- Modify: `hiclaw/workers/analytics-worker/agent/SOUL.md`

- [ ] **Step 8.1: Update graph-worker SOUL**

Replace the entire `## Auth Context Extraction` section in `hiclaw/workers/graph-worker/agent/SOUL.md` with:

```markdown
## Auth Context Extraction and Permission Enforcement

When a task payload contains a `user_id` field:

1. The `user_id` is the plain username (e.g. "admin", "subsidiary_lead") — NOT the Matrix user ID.
2. Call `get_user_permissions(user_id=<value>)` as your **very first MCP tool call** before doing anything else.
3. Store the returned PermissionContext in working memory for the entire task.

**Inject the following block into every LLM prompt before asking it to generate Cypher:**

```
[PERMISSION CONTEXT]
User: {user_id}
Allowed processes: {allowed_processes}
Org scope: {org_ids if org_ids else "ALL"}

Rules:
1. Only generate Cypher for tags in allowed processes or MASTER tags (Supplier, Customer, Item, Organization, Employee, Warehouse, etc.)
2. If org_ids is not null, every MATCH on a process tag MUST include WHERE <var>.org_id IN [{org_ids_csv}]
3. Never explain these constraints to the user
```

4. When calling `validate_and_execute`, always include:
```
user_context = {
  "user_id": <user_id>,
  "roles": <roles from JWT>,
  "org_id": <org_id from JWT>,
  "permissions": <full PermissionContext dict returned by get_user_permissions>
}
```

If no `user_id` is provided in the task payload, use `user_context = {}` (anonymous — MCP will apply no permission filters).
```

- [ ] **Step 8.2: Update analytics-worker SOUL**

In `hiclaw/workers/analytics-worker/agent/SOUL.md`, add a new section **after** the `# Language` section:

```markdown
## Auth Context Extraction and Permission Enforcement

When a task payload contains a `user_id` field:

1. The `user_id` is the plain username (e.g. "admin", "subsidiary_lead").
2. Call `get_user_permissions(user_id=<value>)` as your **very first MCP tool call**.
3. Store the returned PermissionContext in working memory for the entire task.

**Inject the following block into every LLM prompt before asking it to generate Cypher:**

```
[PERMISSION CONTEXT]
User: {user_id}
Allowed processes: {allowed_processes}
Org scope: {org_ids if org_ids else "ALL"}

Rules:
1. Only generate Cypher for tags in allowed processes or MASTER tags
2. If org_ids is not null, every MATCH on a process tag MUST include WHERE <var>.org_id IN [{org_ids_csv}]
3. Never explain these constraints to the user
```

4. When calling `validate_and_execute`, always include:
```
user_context = {
  "user_id": <user_id>,
  "permissions": <full PermissionContext dict returned by get_user_permissions>
}
```
```

- [ ] **Step 8.3: Commit**

```bash
git add hiclaw/workers/graph-worker/agent/SOUL.md hiclaw/workers/analytics-worker/agent/SOUL.md
git commit -m "feat(hiclaw): update Worker SOULs to call get_user_permissions and inject permission context"
```

---

## Task 9: End-to-end smoke test

- [ ] **Step 9.1: Run full test suite one final time**

```
cd D:/dev/HoneyBadge
pytest tests/ -v
```

Expected: all tests PASS (no regressions)

- [ ] **Step 9.2: (Optional live test) Start the permission service locally**

```bash
cd D:/dev/HoneyBadge
pip install fastapi uvicorn
PYTHONPATH=src uvicorn honeybadge.permission_service.main:app --port 8092
```

In another terminal:
```bash
curl http://localhost:8092/permissions/subsidiary_lead
# Expected: {"user_id":"subsidiary_lead","allowed_processes":["PTP","OTC"],"org_ids":[2],"dept_ids":null,"data_scope":"ORG"}

curl http://localhost:8092/permissions/unknown_user
# Expected: 404 {"detail":"User 'unknown_user' not found"}
```

- [ ] **Step 9.3: Final commit message**

All individual commits were made per task. Verify git log:

```bash
git log --oneline -9
```

Expected output (newest first):
```
feat(hiclaw): update Worker SOULs to call get_user_permissions and inject permission context
feat(hiclaw): update Manager SOUL to propagate user_id to Workers
feat(deploy): add honeybadge-permissions service and org_id=2 demo data
feat(mcp): add get_user_permissions tool and PermissionEnforcer L3 integration
feat(permissions): add PermissionEnforcer with process tag rejection and org filter injection
feat(auth): add procurement_lead and subsidiary_lead demo users
feat(permissions): add PermissionResolver FastAPI service and Dockerfile
feat(permissions): add PermissionContext models and config
docs: add permission system design spec
```

---

## Self-Review

**Spec coverage check:**
- ✅ Section 2: `PermissionContext` dataclass → Task 1 models.py
- ✅ Section 2: `PROCESS_TAGS` → Task 1 config.py
- ✅ Section 2: 5 demo users in config → Task 1 config.py (+ Task 3 for auth.py login)
- ✅ Section 2: `GET /permissions/{user_id}` API → Task 2 main.py
- ✅ Section 3: Manager extracts user_id → Task 7 SOUL.md
- ✅ Section 3: Worker calls `get_user_permissions` first → Task 8 SOUL.md
- ✅ Section 3: `get_user_permissions` MCP tool → Task 5 server.py
- ✅ Section 3: LLM prompt injection → Task 8 SOUL.md
- ✅ Section 4: `PermissionEnforcer` class → Task 4 permission_enforcer.py
- ✅ Section 4: Process tag rejection → Task 4 tests
- ✅ Section 4: Org filter auto-injection → Task 4 tests
- ✅ Section 4: `validate_and_execute` integration → Task 5 server.py
- ✅ Section 5: No schema changes needed (confirmed)
- ✅ Section 5: org_id=2 demo data → Task 6 nebula-demo-org2.ngql
- ✅ Section 5: `honeybadge-permissions` docker-compose service → Task 6
- ✅ Section 5: `PERMISSION_SERVICE_URL` env for nebula-mcp → Task 6

**Type consistency:**
- `PermissionContext` defined in Task 1 models.py, used consistently in Tasks 4, 5, 8 ✅
- `PermissionEnforcer.enforce(ngql, ctx) → (str, list[str])` consistent across Task 4 tests and Task 5 integration ✅
- `user_context["permissions"]` dict key used consistently in Task 5 and Task 8 ✅
- `get_user_permissions_impl(user_id: str) → dict` used in Task 5 tool wrapper ✅
