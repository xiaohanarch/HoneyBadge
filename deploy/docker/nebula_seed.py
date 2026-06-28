#!/usr/bin/env python3
"""
HoneyBadge NebulaGraph Seed Data
Inserts realistic ERP data for E2E test coverage.

Usage (Docker):
  docker run --rm --network honeybadge-network \
    -v $(pwd)/deploy/docker/nebula_seed.py:/seed.py \
    python:3.11-slim \
    sh -c "pip install nebula3-python -q && python /seed.py"

Usage (K8s, from ECS):
  kubectl -n honeybadge create job seed-nebula-manual \
    --image=python:3.11-slim \
    -- sh -c "pip install -i https://mirrors.aliyun.com/pypi/simple/ nebula3-python -q && python /scripts/seed.py"
  # (with script mounted from ConfigMap — see seed-nebula.yaml)
"""
import os
import time
import sys

# ── Config ─────────────────────────────────────────────────────────────────
NEBULA_HOST = os.getenv("NEBULA_HOST", "nebula-graphd")
NEBULA_PORT = int(os.getenv("NEBULA_PORT", "9669"))
NEBULA_USER = os.getenv("NEBULA_USER", "root")
NEBULA_PASSWORD = os.getenv("NEBULA_PASSWORD", "nebula")
NEBULA_SPACE = "honeybadge"
BATCH_SIZE = 100

# ── Data constants ──────────────────────────────────────────────────────────
ORGS = [1000, 1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008, 1009, 1010, 1021]
POS_PER_ORG = 310
SOS_PER_ORG = 100

ORG_NAMES = {
    1000: "总部集团", 1001: "华北大区", 1002: "华东大区", 1003: "华南大区",
    1004: "西南大区", 1005: "西北大区", 1006: "华中大区", 1007: "东北大区",
    1008: "华北子公司", 1009: "华东子公司", 1010: "华南子公司", 1021: "子公司-广州",
}
SUPPLIER_NAMES = [
    "云南铜业股份有限公司", "宝武钢铁集团", "中国铝业股份有限公司",
    "比亚迪供应链管理有限公司", "富士康工业互联网股份有限公司",
    "中国化工集团有限公司", "海尔智家股份有限公司", "华为技术有限公司",
    "腾讯云计算有限公司", "阿里云计算有限公司",
]
CUSTOMER_NAMES = [
    "国家电网有限公司", "中国石油化工集团有限公司", "中国建筑股份有限公司",
    "中国银行股份有限公司", "中国工商银行股份有限公司",
    "中国平安保险集团股份有限公司", "格力电器股份有限公司",
    "美的集团股份有限公司", "京东集团股份有限公司", "小米集团有限公司",
]
ITEM_NAMES = [
    "铜板", "钢材", "铝合金", "电子元件", "精密仪器", "化工原料",
    "包装材料", "办公设备", "IT设备", "工程机械", "电缆线材", "橡胶制品",
    "塑料制品", "玻璃制品", "纸张印刷品", "劳保用品", "清洁用品",
    "维修配件", "检测设备", "运输工具",
]
BUYERS = ["张伟", "李娜", "王芳", "赵磊", "钱红", "孙明", "周杰", "吴敏"]
PO_STATUSES = ["APPROVED"] * 7 + ["PENDING"] * 2 + ["CLOSED"] * 1

# Unix timestamps (seconds): 2024-01-01 to 2024-12-31
BASE_TS = 1704067200  # 2024-01-01 00:00:00 UTC
YEAR_SECS = 365 * 86400


def ts(offset_days: int = 0) -> int:
    return BASE_TS + offset_days * 86400


# ── NebulaGraph helpers ─────────────────────────────────────────────────────
def connect():
    from nebula3.gclient.net import ConnectionPool
    from nebula3.Config import Config

    config = Config()
    config.max_connection_pool_size = 5
    pool = ConnectionPool()
    ok = pool.init([(NEBULA_HOST, NEBULA_PORT)], config)
    if not ok:
        print(f"ERROR: Cannot connect to {NEBULA_HOST}:{NEBULA_PORT}", file=sys.stderr)
        sys.exit(1)
    session = pool.get_session(NEBULA_USER, NEBULA_PASSWORD)
    print(f"Connected to NebulaGraph at {NEBULA_HOST}:{NEBULA_PORT}")
    return pool, session


def exec_stmt(session, stmt: str) -> bool:
    result = session.execute(stmt)
    if not result.is_succeeded():
        print(f"  WARN: {result.error_msg()[:120]}", file=sys.stderr)
        return False
    return True


def use_space(session):
    exec_stmt(session, f"USE {NEBULA_SPACE};")


def wait_for_space(session, retries: int = 30):
    """Wait for the honeybadge space and tags to exist."""
    for i in range(retries):
        result = session.execute("SHOW SPACES;")
        if result.is_succeeded():
            spaces = str(result)
            if NEBULA_SPACE in spaces:
                use_space(session)
                # Check PurchaseOrder tag exists
                r2 = session.execute(f"USE {NEBULA_SPACE}; SHOW TAGS;")
                if r2.is_succeeded() and "PurchaseOrder" in str(r2):
                    print("Space and schema ready.")
                    return
        print(f"  Waiting for schema... ({i+1}/{retries})")
        time.sleep(10)
    print("ERROR: Schema not ready after waiting.", file=sys.stderr)
    sys.exit(1)


def insert_vertices(session, tag: str, props: list, rows: list):
    """Insert vertices in batches of BATCH_SIZE."""
    props_str = ", ".join(props)
    total = len(rows)
    inserted = 0
    for start in range(0, total, BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        vals = ",\n  ".join(batch)
        stmt = f"USE {NEBULA_SPACE};\nINSERT VERTEX IF NOT EXISTS {tag}({props_str})\nVALUES\n  {vals};"
        if exec_stmt(session, stmt):
            inserted += len(batch)
    print(f"  {tag}: {inserted}/{total} vertices inserted")


def insert_edges(session, edge_type: str, props: list, rows: list):
    """Insert edges in batches of BATCH_SIZE."""
    props_str = ", ".join(props) if props else ""
    total = len(rows)
    inserted = 0
    for start in range(0, total, BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        vals = ",\n  ".join(batch)
        if props_str:
            stmt = f"USE {NEBULA_SPACE};\nINSERT EDGE IF NOT EXISTS {edge_type}({props_str})\nVALUES\n  {vals};"
        else:
            stmt = f"USE {NEBULA_SPACE};\nINSERT EDGE IF NOT EXISTS {edge_type}()\nVALUES\n  {vals};"
        if exec_stmt(session, stmt):
            inserted += len(batch)
    print(f"  {edge_type}: {inserted}/{total} edges inserted")


# ── Master data ─────────────────────────────────────────────────────────────
def seed_master(session):
    print("\n--- Master Data ---")
    use_space(session)

    # Organizations
    # Schema: org_code, org_name, org_type, parent_org_code, legal_entity, country, city,
    #         status, org_id, dept_id, data_scope, created_at, updated_at,
    #         etl_batch_id, source_system, is_active
    org_rows = []
    for org_id in ORGS:
        name = ORG_NAMES[org_id]
        otype = "LEGAL_ENTITY" if org_id == 1000 else "BUSINESS_UNIT"
        legal_entity = "总部集团" if org_id == 1000 else "总部集团"
        parent = "null" if org_id == 1000 else f'"org:{1000}"'
        # parent_org_code is STRING (not VID) — use empty string for root
        parent_code = "" if org_id == 1000 else "1000"
        org_rows.append(
            f'"org:{org_id}":("{org_id}", "{name}", "{otype}", "{parent_code}", "{legal_entity}", '
            f'"CN", "北京", "ACTIVE", {org_id}, 0, "ALL", '
            f'{ts()}, {ts()}, "SEED-001", "SEED", true)'
        )
    insert_vertices(session, "Organization",
        ["org_code", "org_name", "org_type", "parent_org_code", "legal_entity",
         "country", "city", "status", "org_id", "dept_id", "data_scope",
         "created_at", "updated_at", "etl_batch_id", "source_system", "is_active"],
        org_rows)

    # Suppliers — assign varied credit_ratings so isolation tests can
    # distinguish high-risk (BB/B) from investment-grade (AAA/AA/A/BBB) POs.
    SUPPLIER_RATINGS = ["BB", "B", "BB", "BBB", "A", "AA", "BBB", "B", "AAA", "BB"]
    sup_rows = []
    for i, name in enumerate(SUPPLIER_NAMES, 1):
        rating = SUPPLIER_RATINGS[(i - 1) % len(SUPPLIER_RATINGS)]
        sup_rows.append(
            f'"sup:{i:04d}":("SUP{i:04d}", "{name}", "ENTERPRISE", "ACTIVE", '
            f'"CN", "北京", "北京市朝阳区", "采购联系人{i}", "010-{i:08d}", '
            f'"supplier{i}@example.com", "62280{i:06d}", "中国工商银行", '
            f'"91110000{i:08d}", "CNY", "NET30", "{rating}", '
            f'{ts(i)}, {ts(i + 90)}, 1000, 0, "ALL", '
            f'{ts()}, {ts()}, "SEED-001", "SEED", true)'
        )
    insert_vertices(session, "Supplier",
        ["supplier_number", "supplier_name", "supplier_type", "status",
         "country", "city", "address", "contact_person", "contact_phone",
         "contact_email", "bank_account", "bank_name", "tax_id", "currency",
         "payment_terms", "credit_rating", "registration_date", "qualification_expiry",
         "org_id", "dept_id", "data_scope",
         "created_at", "updated_at", "etl_batch_id", "source_system", "is_active"],
        sup_rows)

    # Customers
    cust_rows = []
    for i, name in enumerate(CUSTOMER_NAMES, 1):
        cust_rows.append(
            f'"cust:{i:04d}":("CUST{i:04d}", "{name}", "ENTERPRISE", "ACTIVE", '
            f'"CN", "上海", "上海市浦东新区", "销售联系人{i}", "021-{i:08d}", '
            f'"customer{i}@example.com", {5000000 + i * 100000}, "NET60", '
            f'"91310000{i:08d}", "CNY", "华东", 1000, 0, "ALL", '
            f'{ts()}, {ts()}, "SEED-001", "SEED", true)'
        )
    insert_vertices(session, "Customer",
        ["customer_number", "customer_name", "customer_type", "status",
         "country", "city", "address", "contact_person", "contact_phone",
         "contact_email", "credit_limit", "payment_terms", "tax_id", "currency",
         "sales_region", "org_id", "dept_id", "data_scope",
         "created_at", "updated_at", "etl_batch_id", "source_system", "is_active"],
        cust_rows)

    # Items
    item_rows = []
    for i, name in enumerate(ITEM_NAMES, 1):
        cost = (i * 137) % 9900 + 100
        item_rows.append(
            f'"item:{i:04d}":("ITEM{i:04d}", "{name}", "标准采购品{i}", '
            f'"PURCHASED", "原材料", "PCS", {cost}.00, {cost * 1.2:.2f}, '
            f'{(i % 10) + 0.5}, "KG", {(i % 5) + 1}, 50.0, 10.0, '
            f'"ACTIVE", "A", 1000, 0, "ALL", '
            f'{ts()}, {ts()}, "SEED-001", "SEED", true)'
        )
    insert_vertices(session, "Item",
        ["item_number", "item_name", "item_description", "item_type", "category",
         "uom", "standard_cost", "list_price", "weight", "weight_uom",
         "lead_time_days", "safety_stock", "min_order_qty", "status", "abc_class",
         "org_id", "dept_id", "data_scope",
         "created_at", "updated_at", "etl_batch_id", "source_system", "is_active"],
        item_rows)


# ── Procurement data ────────────────────────────────────────────────────────
def seed_procurement(session):
    print("\n--- PurchaseOrders ---")
    use_space(session)

    po_rows = []
    belongs_rows = []
    placed_rows = []

    for org_id in ORGS:
        for i in range(1, POS_PER_ORG + 1):
            vid = f"po:{org_id}-{i:05d}"
            po_number = f"PO{org_id}{i:05d}"
            amount = ((i * 7 + org_id) % 950 + 1) * 1000 + ((i * 3) % 999)
            status = PO_STATUSES[i % len(PO_STATUSES)]
            buyer = BUYERS[i % len(BUYERS)]
            order_day = (i * 3) % 350
            approve_day = order_day + 2
            sup_idx = (i % 10) + 1

            po_rows.append(
                f'"{vid}":("{po_number}", "STANDARD", "采购-{org_id}-{i}", '
                f'"{status}", "{buyer}", {ts(order_day)}, {ts(approve_day)}, '
                f'{amount}.00, "CNY", 1.0, "NET30", "STANDARD", "", '
                f'"", null, null, {org_id}, 0, "ORG", '
                f'{ts(order_day)}, {ts(order_day)}, "SEED-001", "EBS", true)'
            )
            # BELONGS_TO_ORG schema: org_id INT64, dept_id INT64
            belongs_rows.append(
                f'"{vid}" -> "org:{org_id}" @0:({org_id}, 0)'
            )
            # PLACED_WITH schema: order_date TIMESTAMP, org_id INT64, dept_id INT64
            placed_rows.append(
                f'"{vid}" -> "sup:{sup_idx:04d}" @0:({ts(order_day)}, {org_id}, 0)'
            )

    insert_vertices(session, "PurchaseOrder",
        ["po_number", "po_type", "description", "status", "buyer",
         "order_date", "approved_date", "total_amount", "currency", "exchange_rate",
         "payment_terms", "freight_terms", "ship_to_location", "bill_to_location",
         "close_date", "cancel_reason", "org_id", "dept_id", "data_scope",
         "created_at", "updated_at", "etl_batch_id", "source_system", "is_active"],
        po_rows)

    insert_edges(session, "BELONGS_TO_ORG", ["org_id", "dept_id"], belongs_rows)
    insert_edges(session, "PLACED_WITH", ["order_date", "org_id", "dept_id"], placed_rows)


# ── AP Invoices (1 per 5 POs) ───────────────────────────────────────────────
def seed_ap_invoices(session):
    print("\n--- AP Invoices ---")
    use_space(session)

    inv_rows = []
    has_inv_rows = []
    n = 0

    for org_id in ORGS:
        for i in range(1, POS_PER_ORG + 1, 5):
            n += 1
            vid = f"inv:{org_id}-{n:05d}"
            po_vid = f"po:{org_id}-{i:05d}"
            amount = ((i * 7 + org_id) % 950 + 1) * 1000
            inv_date = (i * 3) % 350 + 10

            inv_rows.append(
                f'"{vid}":("INV{org_id}{n:05d}", "STANDARD", {ts(inv_date)}, '
                f'{ts(inv_date + 30)}, "APPROVED", {amount}.00, '
                f'{amount * 0.09:.2f}, "CNY", 1.0, "BANK_TRANSFER", '
                f'"采购发票", {ts(inv_date)}, "GENERAL", "PO", '
                f'{org_id}, 0, "ORG", '
                f'{ts(inv_date)}, {ts(inv_date)}, "SEED-001", "EBS", true)'
            )
            # HAS_INVOICE schema: match_status STRING, match_date TIMESTAMP, org_id INT64, dept_id INT64
            has_inv_rows.append(
                f'"{po_vid}" -> "{vid}" @0:("MATCHED", {ts(inv_date)}, {org_id}, 0)'
            )

    insert_vertices(session, "Invoice",
        ["invoice_number", "invoice_type", "invoice_date", "due_date", "status",
         "total_amount", "tax_amount", "currency", "exchange_rate", "payment_method",
         "description", "gl_date", "pay_group", "source",
         "org_id", "dept_id", "data_scope",
         "created_at", "updated_at", "etl_batch_id", "source_system", "is_active"],
        inv_rows)
    insert_edges(session, "HAS_INVOICE",
        ["match_status", "match_date", "org_id", "dept_id"], has_inv_rows)


# ── Sales Orders ────────────────────────────────────────────────────────────
def seed_sales_orders(session):
    print("\n--- SalesOrders ---")
    use_space(session)

    so_rows = []
    sold_to_rows = []

    for org_id in ORGS:
        for i in range(1, SOS_PER_ORG + 1):
            vid = f"so:{org_id}-{i:05d}"
            so_number = f"SO{org_id}{i:05d}"
            amount = ((i * 13 + org_id) % 1900 + 1) * 500
            order_day = (i * 5) % 340
            cust_idx = (i % 10) + 1

            so_rows.append(
                f'"{vid}":("{so_number}", "STANDARD", {ts(order_day)}, '
                f'"BOOKED", {amount}.00, "CNY", 1.0, "NET30", '
                f'"客户地址{i}", "账单地址{i}", "销售员{i % 5 + 1}", '
                f'{ts(order_day)}, {ts(order_day + 7)}, null, '
                f'{org_id}, 0, "ORG", '
                f'{ts(order_day)}, {ts(order_day)}, "SEED-001", "EBS", true)'
            )
            # SOLD_TO schema: order_date TIMESTAMP, org_id INT64, dept_id INT64
            sold_to_rows.append(
                f'"cust:{cust_idx:04d}" -> "{vid}" @0:({ts(order_day)}, {org_id}, 0)'
            )

    insert_vertices(session, "SalesOrder",
        ["so_number", "order_type", "order_date", "status", "total_amount",
         "currency", "exchange_rate", "payment_terms", "ship_to_address",
         "bill_to_address", "salesperson", "requested_date", "scheduled_date",
         "cancel_reason", "org_id", "dept_id", "data_scope",
         "created_at", "updated_at", "etl_batch_id", "source_system", "is_active"],
        so_rows)
    insert_edges(session, "SOLD_TO",
        ["order_date", "org_id", "dept_id"], sold_to_rows)


# ── AR Invoices (1 per 5 SOs) ───────────────────────────────────────────────
def seed_ar_invoices(session):
    print("\n--- AR Invoices ---")
    use_space(session)

    arinv_rows = []
    has_arinv_rows = []
    n = 0

    for org_id in ORGS:
        for i in range(1, SOS_PER_ORG + 1, 5):
            n += 1
            vid = f"arinv:{org_id}-{n:05d}"
            so_vid = f"so:{org_id}-{i:05d}"
            amount = ((i * 13 + org_id) % 1900 + 1) * 500
            inv_date = (i * 5) % 340 + 5

            # ARInvoice schema: invoice_number, invoice_type, invoice_date, due_date, status,
            #                   total_amount, tax_amount, currency, exchange_rate, payment_terms,
            #                   gl_date, org_id, dept_id, data_scope,
            #                   created_at, updated_at, etl_batch_id, source_system, is_active
            arinv_rows.append(
                f'"{vid}":("ARINV{org_id}{n:05d}", "INV", {ts(inv_date)}, '
                f'{ts(inv_date + 30)}, "COMPLETE", {amount}.00, '
                f'{amount * 0.09:.2f}, "CNY", 1.0, "NET30", '
                f'{ts(inv_date)}, {org_id}, 0, "ORG", '
                f'{ts(inv_date)}, {ts(inv_date)}, "SEED-001", "EBS", true)'
            )
            # HAS_AR_INVOICE schema: org_id INT64, dept_id INT64
            has_arinv_rows.append(
                f'"{so_vid}" -> "{vid}" @0:({org_id}, 0)'
            )

    insert_vertices(session, "ARInvoice",
        ["invoice_number", "invoice_type", "invoice_date", "due_date", "status",
         "total_amount", "tax_amount", "currency", "exchange_rate", "payment_terms",
         "gl_date", "org_id", "dept_id", "data_scope",
         "created_at", "updated_at", "etl_batch_id", "source_system", "is_active"],
        arinv_rows)
    insert_edges(session, "HAS_AR_INVOICE",
        ["org_id", "dept_id"], has_arinv_rows)


# ── Verify ──────────────────────────────────────────────────────────────────
def verify(session):
    print("\n--- Verification ---")
    use_space(session)
    checks = [
        ("PurchaseOrder total",
         "MATCH (v:PurchaseOrder) RETURN COUNT(v) AS cnt"),
        ("PurchaseOrder org_id=1000",
         "MATCH (v:PurchaseOrder) WHERE v.PurchaseOrder.org_id == 1000 RETURN COUNT(v) AS cnt"),
        ("PurchaseOrder org_id=1021",
         "MATCH (v:PurchaseOrder) WHERE v.PurchaseOrder.org_id == 1021 RETURN COUNT(v) AS cnt"),
        ("SalesOrder total",
         "MATCH (v:SalesOrder) RETURN COUNT(v) AS cnt"),
        ("Supplier total",
         "MATCH (v:Supplier) RETURN COUNT(v) AS cnt"),
        ("Invoice (AP) total",
         "MATCH (v:Invoice) RETURN COUNT(v) AS cnt"),
    ]
    for label, stmt in checks:
        result = session.execute(f"USE {NEBULA_SPACE}; {stmt}")
        if result.is_succeeded() and result.row_size() > 0:
            cnt = result.row_values(0)[0].as_int()
            print(f"  {label}: {cnt}")
        else:
            print(f"  {label}: ERROR - {result.error_msg()[:60]}")


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    print("=== HoneyBadge NebulaGraph Seed ===")
    print(f"Target: {NEBULA_HOST}:{NEBULA_PORT}  Space: {NEBULA_SPACE}")

    pool, session = connect()
    try:
        wait_for_space(session)
        seed_master(session)
        seed_procurement(session)
        seed_ap_invoices(session)
        seed_sales_orders(session)
        seed_ar_invoices(session)
        verify(session)
        print("\n=== Seed complete ===")
    finally:
        session.release()
        pool.close()


if __name__ == "__main__":
    main()
