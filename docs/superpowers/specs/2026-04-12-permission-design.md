# Permission System Design

**Date:** 2026-04-12
**Status:** Approved
**Branch:** integration-with-google-SSO → master (next feature branch)

---

## 1. Overview

A custom permission/authorization system for HoneyBadge that enforces two-dimensional access control:

- **Process dimension**: which ERP process flows a user may access (PTP / OTC)
- **Org dimension**: which subsidiaries' data a user may see (all or specific `org_id` list)

No external framework (Casbin, OPA) is introduced. A standalone `PermissionResolver` microservice provides the permission contract, making the backend pluggable for future replacement with a production RBAC/ABAC system without touching any enforcement code.

Enforcement is dual-layer:
- **Layer 1 (soft):** LLM prompt injection — constrains what the LLM generates
- **Layer 2 (hard):** MCP Server `PermissionEnforcer` — validates and rewrites Cypher before execution, with hard reject on process violations and auto-injection of missing org filters

---

## 2. PermissionContext Data Structure

```python
# src/honeybadge/permission_service/models.py
from dataclasses import dataclass

@dataclass
class PermissionContext:
    user_id: str
    allowed_processes: list[str]   # ["PTP"] / ["OTC"] / ["PTP", "OTC"]
    org_ids: list[int] | None      # None = all orgs; [2] = org_id=2 only
    dept_ids: list[int] | None     # reserved for future dept-level control
    data_scope: str                # "ALL" / "ORG" / "DEPT"
```

### PermissionResolver API Contract

```
GET /permissions/{user_id}
→ 200 { user_id, allowed_processes, org_ids, dept_ids, data_scope }
→ 404 { detail: "User not found" }
```

Internal URL (Docker network): `http://honeybadge-permissions:8092`

### PROCESS_TAGS Classification

```python
PROCESS_TAGS = {
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
        # Always accessible to all users — no process filtering
        "Organization", "Employee", "Supplier", "Customer", "Item",
        "Warehouse", "BOM", "BOMComponent", "Currency", "UOM",
        "GLAccount", "GLJournalEntry", "GLJournalLine",
        "XLAEvent", "AccountingDistribution", "ApprovalRecord",
    },
}
```

### Demo Users (POC config)

| user_id           | allowed_processes | org_ids | data_scope | Description       |
|-------------------|-------------------|---------|------------|-------------------|
| admin             | PTP, OTC          | null    | ALL        | CEO / super admin |
| procurement_lead  | PTP               | null    | ALL        | 采购部门领导       |
| subsidiary_lead   | PTP, OTC          | [2]     | ORG        | 子公司领导         |
| analyst           | PTP               | [1]     | ORG        | 子公司分析师       |
| auditor           | PTP, OTC          | null    | ALL        | 审计员（只读）     |

---

## 3. Worker Integration

### Step 1: Manager extracts user_id from JWT

Manager's SOUL rule: before dispatching any task to a Worker, extract `user_id` from the `x-hb-auth` JWT header and include it in the task payload.

### Step 2: Worker calls get_user_permissions

Worker SOUL rule: upon receiving a task, the **first MCP call** must be `get_user_permissions(user_id)`. The returned `PermissionContext` is stored in working memory for the entire task.

MCP tool signature (added to `honeybadge-nebula-mcp`):

```python
@mcp.tool()
async def get_user_permissions(user_id: str) -> dict:
    """Fetch user's PermissionContext from PermissionResolver service."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{PERMISSION_SERVICE_URL}/permissions/{user_id}")
        r.raise_for_status()
        return r.json()
```

### Step 3: Permission context injected into LLM prompt

Worker injects the following block into every LLM system prompt before Cypher generation:

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

---

## 4. MCP Server L3 Hard Enforcement

### PermissionEnforcer behavior

File: `mcp-servers/honeybadge-nebula-mcp/permission_enforcer.py`

```
enforce(ngql: str, ctx: PermissionContext) → (ngql: str, warnings: list[str])
```

**Process tag check (hard reject):**
1. Parse all `(var:Tag)` patterns from MATCH clauses
2. For each tag: if tag ∈ PROCESS_TAGS and tag's process ∉ ctx.allowed_processes → raise `PermissionViolationError`
3. MASTER tags are always allowed, never rejected

**Org filter auto-injection (safety net):**
1. If `ctx.org_ids is None` → skip (user has full org access)
2. For each process tag variable where `org_id IN [...]` filter is missing → inject into WHERE clause
3. Append warning: `[PERMISSION WARNING] Auto-injected org_id filter for {var}:{tag}`

**WHERE injection logic:**
- Existing WHERE clause → append `AND {var}.org_id IN [{org_ids_csv}]`
- No WHERE clause → insert `WHERE {var}.org_id IN [{org_ids_csv}]` before `RETURN`/`YIELD`

### validate_and_execute integration

```python
async def validate_and_execute(ngql: str, user_context: dict) -> dict:
    ctx = PermissionContext(**user_context["permissions"])
    enforcer = PermissionEnforcer()
    try:
        ngql, warnings = enforcer.enforce(ngql, ctx)
    except PermissionViolationError as e:
        return {"error": str(e), "code": "PERMISSION_DENIED"}

    result = await nebula_client.execute(ngql)
    return {"data": result, "warnings": warnings}
```

---

## 5. NebulaGraph Demo Data + File Changes + Deployment

### NebulaGraph

No schema changes needed — `org_id` property already exists on all PTP/OTC tags.

New file `deploy/docker/nebula-demo-org2.ngql` adds org_id=2 sample data (PurchaseOrder, Receipt, Invoice, edges) so that `subsidiary_lead`'s restriction to org_id=[2] has meaningful effect in demos.

### Complete File Change List

**New files (6):**

```
src/honeybadge/permission_service/
├── main.py            # FastAPI app, GET /permissions/{user_id}
├── models.py          # PermissionContext dataclass
├── config.py          # POC config dict + PROCESS_TAGS
└── Dockerfile

mcp-servers/honeybadge-nebula-mcp/
└── permission_enforcer.py   # PermissionEnforcer class

deploy/docker/
└── nebula-demo-org2.ngql    # org_id=2 demo data
```

**Modified files (5):**

```
src/honeybadge/auth_service/main.py
  → Add procurement_lead, subsidiary_lead to DEMO_USERS

mcp-servers/honeybadge-nebula-mcp/server.py
  → Add get_user_permissions() tool
  → Integrate PermissionEnforcer into validate_and_execute()

deploy/hiclaw/soul.md (Manager SOUL)
  → Add: extract user_id from x-hb-auth JWT; include in Worker task dispatch

deploy/hiclaw/worker-soul.md (Worker SOUL)
  → Add: first step is always get_user_permissions; inject result into LLM prompt

deploy/docker/docker-compose.yaml
  → Add honeybadge-permissions service on port 8092
```

### docker-compose.yaml — New Service

```yaml
honeybadge-permissions:
  build:
    context: ../..
    dockerfile: src/honeybadge/permission_service/Dockerfile
  container_name: honeybadge-permissions
  ports:
    - "8092:8092"
  environment:
    - PORT=8092
  networks:
    - honeybadge-net
  healthcheck:
    test: ["CMD", "python", "-c", "import socket; s=socket.create_connection(('localhost',8092),2)"]
    interval: 30s
    timeout: 10s
    retries: 3
```

---

## 6. End-to-End Data Flow

```
User JWT (user_id)
  → Manager: extract user_id from x-hb-auth
  → Worker: get_user_permissions(user_id) → PermissionService:8092
  → Worker: PermissionContext injected into LLM system prompt  [soft layer]
  → LLM: generates Cypher constrained by prompt rules
  → MCP validate_and_execute:
      PermissionEnforcer.enforce()                              [hard layer]
      - process tag violation → hard reject, return error
      - missing org_id filter → auto-inject, add warning
  → NebulaGraph: execute safe Cypher
  → Result → Worker → Manager → User
```

---

## 7. Production Migration Path

When the POC is ready to graduate to production:

1. Replace `permission_service/config.py` backend with a call to the existing enterprise RBAC/ABAC service
2. No changes to PermissionEnforcer, Worker SOUL, or MCP tool signatures
3. The `PermissionContext` contract is the stable interface boundary

This is the only file that needs to change for production integration.
