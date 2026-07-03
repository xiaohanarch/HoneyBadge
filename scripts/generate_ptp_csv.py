#!/usr/bin/env python3
"""
HoneyBadge PTP Synthetic CSV Generator

Generates synthetic CSV data for the 9 PTP main-chain ODS tables:
    ods_organization, ods_supplier, ods_item,
    ods_purchase_order, ods_purchase_order_line,
    ods_receipt, ods_receipt_line,
    ods_ap_invoice, ods_ap_invoice_line

Data distribution mirrors nebula_seed.py (amount formulas, date offsets,
status mix) but extends to row-level data (PO lines, receipt lines, invoice
lines) that the seed does not cover, enabling three-way-match verification.

Intentional data quality issues (to exercise quality.py):
    - 5 purchase orders with malformed po_number
    - 3 AP invoices with negative total_amount
    - 2 suppliers with invalid status

Usage:
    python scripts/generate_ptp_csv.py --output-dir deploy/test-data/ptp_csv/ --batch-id ETL-TEST-001
"""

import argparse
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

# ── Reproducibility ─────────────────────────────────────────────────────────
random.seed(42)

# ── Data constants (aligned with nebula_seed.py) ────────────────────────────
ORGS = [1000, 1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008, 1009, 1010, 1021]
ORG_NAMES = {
    1000: "总部集团", 1001: "华北大区", 1002: "华东大区", 1003: "华南大区",
    1004: "西南大区", 1005: "西北大区", 1006: "华中大区", 1007: "东北大区",
    1008: "华北子公司", 1009: "华东子公司", 1010: "华南子公司", 1021: "子公司-广州",
}
ORG_TYPES = {1000: "LEGAL_ENTITY"}
for o in ORGS[1:]:
    ORG_TYPES[o] = "BUSINESS_UNIT"

SUPPLIER_NAMES = [
    "云南铜业股份有限公司", "宝武钢铁集团", "中国铝业股份有限公司",
    "比亚迪供应链管理有限公司", "富士康工业互联网股份有限公司",
    "中国化工集团有限公司", "海尔智家股份有限公司", "华为技术有限公司",
    "腾讯云计算有限公司", "阿里云计算有限公司",
    "中兴通讯股份有限公司", "京东方科技集团股份有限公司",
    "三一重工股份有限公司", "中联重科股份有限公司", "潍柴动力股份有限公司",
    "宁德时代新能源科技股份有限公司", "联想集团有限公司", "小米通讯技术有限公司",
    "海康威视数字技术股份有限公司", "大华技术股份有限公司",
    "格力电器股份有限公司", "美的集团股份有限公司", "海尔智家股份有限公司",
    "TCL科技集团股份有限公司", "四川长虹电器股份有限公司",
    "中国中车股份有限公司", "中国铁建股份有限公司", "中国中铁股份有限公司",
    "中国建筑股份有限公司", "中国交建股份有限公司", "中国电建集团股份有限公司",
    "中国能建集团股份有限公司", "华能国际电力股份有限公司", "大唐国际发电股份有限公司",
    "华电国际电力股份有限公司", "国电电力发展股份有限公司", "中石油天然气股份有限公司",
    "中石化石油化工股份有限公司", "中海油能源发展股份有限公司", "中粮集团有限公司",
    "中国五矿集团有限公司", "中国铝业集团有限公司", "中国宝武钢铁集团有限公司",
    "中国兵器工业集团有限公司", "中国航空工业集团有限公司", "中国航天科技集团有限公司",
    "中国电子科技集团有限公司", "中国核工业集团有限公司", "中国船舶集团有限公司",
    "中国机械工业集团有限公司",
]
SUPPLIER_RATINGS = ["AAA", "AA", "A", "BBB", "BB", "B"]
CREDIT_RATING_CYCLE = ["BB", "B", "BB", "BBB", "A", "AA", "BBB", "B", "AAA", "BB"]

ITEM_NAMES = [
    "铜板", "钢材", "铝合金", "电子元件", "精密仪器", "化工原料",
    "包装材料", "办公设备", "IT设备", "工程机械", "电缆线材", "橡胶制品",
    "塑料制品", "玻璃制品", "纸张印刷品", "劳保用品", "清洁用品",
    "维修配件", "检测设备", "运输工具",
]
ITEM_CATEGORIES = ["原材料", "半成品", "成品", "办公用品", "设备"]
ITEM_TYPES = ["RAW_MATERIAL", "FINISHED_GOOD", "SEMI_FINISHED", "SERVICE", "EXPENSE"]
ABC_CLASSES = ["A", "B", "C"]
UOM_CODES = ["EA", "KG", "M", "L", "PCS", "BOX"]

BUYERS = ["张伟", "李娜", "王芳", "赵磊", "钱红", "孙明", "周杰", "吴敏"]
PO_STATUSES = ["APPROVED"] * 7 + ["PENDING"] * 2 + ["CLOSED"] * 1
CURRENCIES = ["CNY", "USD", "EUR", "JPY", "GBP", "HKD"]
PAYMENT_TERMS = ["NET30", "NET60", "NET90", "IMMEDIATE", "NET45"]
RECEIPT_STATUSES = ["RECEIVED", "PARTIALLY_RECEIVED", "PENDING"]
INVOICE_STATUSES = ["DRAFT", "VALIDATED", "APPROVED", "PAID", "CANCELLED", "ON_HOLD"]

# Unix epoch base: 2024-01-01 00:00:00 UTC
BASE_DATE = datetime(2024, 1, 1)


def ts(offset_days: int = 0) -> str:
    """ISO timestamp string offset by N days from base."""
    return (BASE_DATE + timedelta(days=offset_days)).strftime("%Y-%m-%d %H:%M:%S")


# ── Standard ETL columns ────────────────────────────────────────────────────
ETL_COLUMNS = [
    "etl_batch_id",
    "etl_load_time",
    "source_system",
    "source_update_time",
    "is_deleted",
    "dq_status",
    "dq_errors",
]


def etl_row(batch_id: str, source_system: str = "EBS") -> dict:
    """Return the 8 standard ETL columns as a dict."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "etl_batch_id": batch_id,
        "etl_load_time": now,
        "source_system": source_system,
        "source_update_time": now,
        "is_deleted": "false",
        "dq_status": "pending",
        "dq_errors": "",
    }


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    """Write rows to a CSV file with the given fieldnames (header)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"  {path.name}: {len(rows)} rows")


# ── Table generators ────────────────────────────────────────────────────────

def gen_organization(batch_id: str) -> list[dict]:
    """12 organizations. org_id 1000 is LEGAL_ENTITY."""
    rows = []
    for org_id in ORGS:
        row = {
            "org_id": org_id,
            "org_code": f"ORG{org_id}",
            "org_name": ORG_NAMES[org_id],
            "org_type": ORG_TYPES[org_id],
            "parent_org_id": "" if org_id == 1000 else 1000,
            "legal_entity": "总部集团" if org_id == 1000 else "",
            "country": "CN",
            "city": "北京",
            "status": "ACTIVE",
        }
        row.update(etl_row(batch_id))
        rows.append(row)
    return rows


def gen_supplier(batch_id: str, count: int = 50) -> list[dict]:
    """50 suppliers with credit_rating covering AAA..B. 2 have invalid status."""
    rows = []
    invalid_status_indices = {7, 23}  # 2 suppliers get INVALID status
    for i in range(1, count + 1):
        name = SUPPLIER_NAMES[(i - 1) % len(SUPPLIER_NAMES)]
        rating = CREDIT_RATING_CYCLE[(i - 1) % len(CREDIT_RATING_CYCLE)]
        status = "FROZEN" if i in invalid_status_indices else "ACTIVE"
        row = {
            "vendor_id": i,
            "vendor_number": f"SUP{i:04d}",
            "vendor_name": f"{name}-{i}",
            "vendor_type": "ENTERPRISE",
            "status": status,
            "country": "CN",
            "city": "北京",
            "address": f"北京市朝阳区{i}号",
            "contact_person": f"采购联系人{i}",
            "contact_phone": f"010-{i:08d}",
            "contact_email": f"supplier{i}@example.com",
            "bank_account": f"62280{i:06d}",
            "bank_name": "中国工商银行",
            "vat_registration_num": f"91110000{i:08d}",
            "payment_terms": PAYMENT_TERMS[i % len(PAYMENT_TERMS)],
            "credit_rating": rating,
            "start_date": ts(i % 30),
            "end_date": ts((i % 30) + 90),
            "org_id": 1000,
        }
        row.update(etl_row(batch_id))
        rows.append(row)
    return rows


def gen_item(batch_id: str, count: int = 100) -> list[dict]:
    """100 items with abc_class A/B/C."""
    rows = []
    for i in range(1, count + 1):
        name = ITEM_NAMES[(i - 1) % len(ITEM_NAMES)]
        cost = (i * 137) % 9900 + 100
        row = {
            "inventory_item_id": i,
            "item_number": f"ITEM{i:04d}",
            "item_name": f"{name}-{i}",
            "item_description": f"标准采购品{i}",
            "item_type": ITEM_TYPES[i % len(ITEM_TYPES)],
            "category": ITEM_CATEGORIES[i % len(ITEM_CATEGORIES)],
            "uom": UOM_CODES[i % len(UOM_CODES)],
            "standard_cost": f"{cost}.00",
            "list_price": f"{cost * 1.2:.2f}",
            "weight": f"{(i % 10) + 0.5}",
            "weight_uom": "KG",
            "lead_time_days": (i % 5) + 1,
            "safety_stock": "50.0",
            "min_order_qty": "10.0",
            "status": "ACTIVE",
            "abc_class": ABC_CLASSES[i % len(ABC_CLASSES)],
            "org_id": 1000,
        }
        row.update(etl_row(batch_id))
        rows.append(row)
    return rows


def gen_purchase_order(batch_id: str, count: int = 500) -> list[dict]:
    """500 POs. org_id rotates. status 70% APPROVED / 20% PENDING / 10% CLOSED.
    5 POs have malformed po_number (intentional DQ issue — NOT NULL column,
    so we use a format violation rather than empty string)."""
    rows = []
    bad_po_number_indices = {50, 150, 250, 350, 450}  # 5 POs with malformed po_number
    for i in range(1, count + 1):
        org_id = ORGS[i % len(ORGS)]
        amount = ((i * 7 + org_id) % 950 + 1) * 1000 + ((i * 3) % 999)
        status = PO_STATUSES[i % len(PO_STATUSES)]
        buyer = BUYERS[i % len(BUYERS)]
        order_day = (i * 3) % 350
        approve_day = order_day + 2
        sup_idx = (i % 50) + 1
        po_number = f"BAD-PO-{i}" if i in bad_po_number_indices else f"PO{org_id}{i:05d}"
        row = {
            "po_header_id": i,
            "po_number": po_number,
            "po_type": "STANDARD",
            "description": f"采购-{org_id}-{i}",
            "status": status,
            "buyer_id": (i % 8) + 1,
            "buyer_name": buyer,
            "vendor_id": sup_idx,
            "vendor_name": f"供应商{sup_idx}",
            "order_date": ts(order_day),
            "approved_date": ts(approve_day) if status != "PENDING" else "",
            "total_amount": f"{amount}.00",
            "currency_code": "CNY",
            "exchange_rate": "1.0",
            "payment_terms": "NET30",
            "freight_terms": "STANDARD",
            "ship_to_location": f"仓库-{org_id}",
            "bill_to_location": f"账单-{org_id}",
            "close_date": ts(order_day + 60) if status == "CLOSED" else "",
            "cancel_reason": "",
            "org_id": org_id,
        }
        row.update(etl_row(batch_id))
        rows.append(row)
    return rows


def gen_purchase_order_line(batch_id: str, po_rows: list[dict]) -> list[dict]:
    """1-5 lines per PO. ~1500 lines total."""
    rows = []
    line_id = 0
    for po in po_rows:
        po_header_id = po["po_header_id"]
        num_lines = random.randint(1, 5)
        for ln in range(1, num_lines + 1):
            line_id += 1
            item_id = random.randint(1, 100)
            quantity = random.randint(10, 500)
            unit_price = random.randint(50, 5000)
            amount = quantity * unit_price
            order_day = (po_header_id * 3) % 350
            row = {
                "po_line_id": line_id,
                "po_header_id": po_header_id,
                "line_number": ln,
                "line_type": "GOODS",
                "item_id": item_id,
                "item_description": f"行物料-{item_id}",
                "quantity": str(quantity),
                "unit_price": str(unit_price),
                "amount": str(amount),
                "uom": UOM_CODES[item_id % len(UOM_CODES)],
                "need_by_date": ts(order_day + 14),
                "promised_date": ts(order_day + 10),
                "received_quantity": "0",
                "invoiced_quantity": "0",
                "status": po["status"],
                "tax_code": "VAT13",
                "tax_rate": "0.13",
                "org_id": po["org_id"],
            }
            row.update(etl_row(batch_id))
            rows.append(row)
    return rows


def gen_receipt(batch_id: str, po_rows: list[dict]) -> list[dict]:
    """350 receipts. 70% of POs get 1 receipt."""
    rows = []
    shipment_header_id = 0
    for po in po_rows:
        if random.random() > 0.7:
            continue
        shipment_header_id += 1
        po_header_id = po["po_header_id"]
        order_day = (po_header_id * 3) % 350
        receipt_day = order_day + 7
        status = random.choice(RECEIPT_STATUSES)
        row = {
            "shipment_header_id": shipment_header_id,
            "receipt_number": f"RCV{po_header_id:05d}",
            "receipt_type": "STANDARD",
            "receipt_date": ts(receipt_day),
            "status": status,
            "receiver_id": (po_header_id % 8) + 1,
            "receiver_name": BUYERS[po_header_id % len(BUYERS)],
            "po_header_id": po_header_id,
            "total_quantity": str(random.randint(50, 800)),
            "warehouse_code": f"WH{po['org_id']}",
            "comments": "",
            "org_id": po["org_id"],
        }
        row.update(etl_row(batch_id))
        rows.append(row)
    return rows


def gen_receipt_line(batch_id: str, receipt_rows: list[dict], po_line_rows: list[dict]) -> list[dict]:
    """~1000 receipt lines. Links to po_line_id. Some have rejected_quantity > 0."""
    rows = []
    shipment_line_id = 0
    # Build a map: po_header_id -> list of po_lines
    po_lines_by_header: dict[int, list[dict]] = {}
    for pl in po_line_rows:
        po_lines_by_header.setdefault(pl["po_header_id"], []).append(pl)

    for rcv in receipt_rows:
        po_header_id = rcv["po_header_id"]
        po_lines = po_lines_by_header.get(po_header_id, [])
        if not po_lines:
            continue
        # Receipt lines for a subset of PO lines
        num_rcv_lines = min(len(po_lines), random.randint(1, 3))
        for ln in range(1, num_rcv_lines + 1):
            shipment_line_id += 1
            po_line = po_lines[ln - 1]
            ordered_qty = int(po_line["quantity"])
            received_qty = ordered_qty if rcv["status"] == "RECEIVED" else ordered_qty // 2
            rejected_qty = random.randint(0, 5) if random.random() < 0.1 else 0
            accepted_qty = received_qty - rejected_qty
            row = {
                "shipment_line_id": shipment_line_id,
                "shipment_header_id": rcv["shipment_header_id"],
                "po_line_id": po_line["po_line_id"],
                "line_number": ln,
                "item_id": po_line["item_id"],
                "received_quantity": str(received_qty),
                "accepted_quantity": str(accepted_qty),
                "rejected_quantity": str(rejected_qty),
                "uom": po_line["uom"],
                "inspection_status": "PASSED" if rejected_qty == 0 else "FAILED",
                "lot_number": f"LOT{shipment_line_id:06d}",
                "subinventory": f"SUB{rcv['org_id']}",
                "sublocation": f"LOC{shipment_line_id:04d}",
                "org_id": rcv["org_id"],
            }
            row.update(etl_row(batch_id))
            rows.append(row)
    return rows


def gen_ap_invoice(batch_id: str, po_rows: list[dict]) -> list[dict]:
    """200 invoices. 1 per 5 POs. invoice_date = order_date + 10d.
    3 invoices have negative total_amount (intentional DQ issue)."""
    rows = []
    inv_id = 0
    negative_indices = {30, 100, 170}  # 3 invoices with negative amount
    for i, po in enumerate(po_rows):
        if i % 5 != 0:
            continue
        inv_id += 1
        po_header_id = po["po_header_id"]
        amount = ((po_header_id * 7 + po["org_id"]) % 950 + 1) * 1000
        if inv_id in negative_indices:
            amount = -amount  # intentional negative
        order_day = (po_header_id * 3) % 350
        inv_day = order_day + 10
        row = {
            "invoice_id": inv_id,
            "invoice_number": f"INV{po['org_id']}{inv_id:05d}",
            "invoice_type": "STANDARD",
            "vendor_id": po["vendor_id"],
            "vendor_name": po["vendor_name"],
            "vendor_site_id": (po["vendor_id"] % 5) + 1,
            "invoice_date": ts(inv_day),
            "due_date": ts(inv_day + 30),
            "status": random.choice(INVOICE_STATUSES),
            "total_amount": f"{amount}.00",
            "tax_amount": f"{amount * 0.09:.2f}" if amount > 0 else f"{amount * 0.09:.2f}",
            "currency_code": "CNY",
            "exchange_rate": "1.0",
            "payment_method": "BANK_TRANSFER",
            "description": f"采购发票-{inv_id}",
            "gl_date": ts(inv_day),
            "po_header_id": po_header_id,
            "org_id": po["org_id"],
        }
        row.update(etl_row(batch_id))
        rows.append(row)
    return rows


def gen_ap_invoice_line(batch_id: str, invoice_rows: list[dict], po_line_rows: list[dict], receipt_line_rows: list[dict]) -> list[dict]:
    """~600 invoice lines. Each links po_line_id AND receipt_line_id (three-way match)."""
    rows = []
    inv_line_id = 0
    # Build maps for lookup
    po_lines_by_header: dict[int, list[dict]] = {}
    for pl in po_line_rows:
        po_lines_by_header.setdefault(pl["po_header_id"], []).append(pl)
    rcv_lines_by_po_line: dict[int, list[dict]] = {}
    for rl in receipt_line_rows:
        rcv_lines_by_po_line.setdefault(rl["po_line_id"], []).append(rl)

    for inv in invoice_rows:
        po_header_id = inv["po_header_id"]
        po_lines = po_lines_by_header.get(po_header_id, [])
        if not po_lines:
            continue
        num_inv_lines = min(len(po_lines), random.randint(1, 5))
        for ln in range(1, num_inv_lines + 1):
            inv_line_id += 1
            po_line = po_lines[ln - 1]
            po_line_id = po_line["po_line_id"]
            # Find matching receipt line for this po_line
            rcv_lines = rcv_lines_by_po_line.get(po_line_id, [])
            receipt_line_id = rcv_lines[0]["shipment_line_id"] if rcv_lines else ""
            quantity = int(po_line["quantity"])
            unit_price = int(po_line["unit_price"])
            amount = quantity * unit_price
            row = {
                "invoice_line_id": inv_line_id,
                "invoice_id": inv["invoice_id"],
                "line_number": ln,
                "line_type": "ITEM",
                "item_id": po_line["item_id"],
                "item_description": po_line["item_description"],
                "quantity": str(quantity),
                "unit_price": str(unit_price),
                "amount": str(amount),
                "tax_code": "VAT13",
                "tax_rate": "0.13",
                "po_line_id": po_line_id,
                "receipt_line_id": receipt_line_id,
                "description": f"发票行-{inv_line_id}",
                "org_id": inv["org_id"],
            }
            row.update(etl_row(batch_id))
            rows.append(row)
    return rows


# ── Field name definitions (must match ods_schema.sql DDL order) ────────────

FIELD_MAP = {
    "ods_organization": [
        "org_id", "org_code", "org_name", "org_type", "parent_org_id",
        "legal_entity", "country", "city", "status",
    ] + ETL_COLUMNS,
    "ods_supplier": [
        "vendor_id", "vendor_number", "vendor_name", "vendor_type", "status",
        "country", "city", "address", "contact_person", "contact_phone",
        "contact_email", "bank_account", "bank_name", "vat_registration_num",
        "payment_terms", "credit_rating", "start_date", "end_date", "org_id",
    ] + ETL_COLUMNS,
    "ods_item": [
        "inventory_item_id", "item_number", "item_name", "item_description",
        "item_type", "category", "uom", "standard_cost", "list_price",
        "weight", "weight_uom", "lead_time_days", "safety_stock",
        "min_order_qty", "status", "abc_class", "org_id",
    ] + ETL_COLUMNS,
    "ods_purchase_order": [
        "po_header_id", "po_number", "po_type", "description", "status",
        "buyer_id", "buyer_name", "vendor_id", "vendor_name", "order_date",
        "approved_date", "total_amount", "currency_code", "exchange_rate",
        "payment_terms", "freight_terms", "ship_to_location",
        "bill_to_location", "close_date", "cancel_reason", "org_id",
    ] + ETL_COLUMNS,
    "ods_purchase_order_line": [
        "po_line_id", "po_header_id", "line_number", "line_type", "item_id",
        "item_description", "quantity", "unit_price", "amount", "uom",
        "need_by_date", "promised_date", "received_quantity",
        "invoiced_quantity", "status", "tax_code", "tax_rate", "org_id",
    ] + ETL_COLUMNS,
    "ods_receipt": [
        "shipment_header_id", "receipt_number", "receipt_type",
        "receipt_date", "status", "receiver_id", "receiver_name",
        "po_header_id", "total_quantity", "warehouse_code", "comments",
        "org_id",
    ] + ETL_COLUMNS,
    "ods_receipt_line": [
        "shipment_line_id", "shipment_header_id", "po_line_id", "line_number",
        "item_id", "received_quantity", "accepted_quantity",
        "rejected_quantity", "uom", "inspection_status", "lot_number",
        "subinventory", "sublocation", "org_id",
    ] + ETL_COLUMNS,
    "ods_ap_invoice": [
        "invoice_id", "invoice_number", "invoice_type", "vendor_id",
        "vendor_name", "vendor_site_id", "invoice_date", "due_date",
        "status", "total_amount", "tax_amount", "currency_code",
        "exchange_rate", "payment_method", "description", "gl_date",
        "po_header_id", "org_id",
    ] + ETL_COLUMNS,
    "ods_ap_invoice_line": [
        "invoice_line_id", "invoice_id", "line_number", "line_type",
        "item_id", "item_description", "quantity", "unit_price", "amount",
        "tax_code", "tax_rate", "po_line_id", "receipt_line_id",
        "description", "org_id",
    ] + ETL_COLUMNS,
}


def generate_all(output_dir: Path, batch_id: str, org_count: int, po_count: int) -> None:
    """Generate all 9 PTP CSV files."""
    print(f"Generating PTP CSV data (batch={batch_id}) -> {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    orgs = gen_organization(batch_id)
    write_csv(output_dir / "ods_organization.csv", FIELD_MAP["ods_organization"], orgs)

    suppliers = gen_supplier(batch_id, count=50)
    write_csv(output_dir / "ods_supplier.csv", FIELD_MAP["ods_supplier"], suppliers)

    items = gen_item(batch_id, count=100)
    write_csv(output_dir / "ods_item.csv", FIELD_MAP["ods_item"], items)

    pos = gen_purchase_order(batch_id, count=po_count)
    write_csv(output_dir / "ods_purchase_order.csv", FIELD_MAP["ods_purchase_order"], pos)

    po_lines = gen_purchase_order_line(batch_id, pos)
    write_csv(output_dir / "ods_purchase_order_line.csv", FIELD_MAP["ods_purchase_order_line"], po_lines)

    receipts = gen_receipt(batch_id, pos)
    write_csv(output_dir / "ods_receipt.csv", FIELD_MAP["ods_receipt"], receipts)

    receipt_lines = gen_receipt_line(batch_id, receipts, po_lines)
    write_csv(output_dir / "ods_receipt_line.csv", FIELD_MAP["ods_receipt_line"], receipt_lines)

    invoices = gen_ap_invoice(batch_id, pos)
    write_csv(output_dir / "ods_ap_invoice.csv", FIELD_MAP["ods_ap_invoice"], invoices)

    invoice_lines = gen_ap_invoice_line(batch_id, invoices, po_lines, receipt_lines)
    write_csv(output_dir / "ods_ap_invoice_line.csv", FIELD_MAP["ods_ap_invoice_line"], invoice_lines)

    print("\nSummary:")
    print(f"  ods_organization:        {len(orgs)}")
    print(f"  ods_supplier:            {len(suppliers)} (2 with invalid status)")
    print(f"  ods_item:                {len(items)}")
    print(f"  ods_purchase_order:      {len(pos)} (5 with malformed po_number)")
    print(f"  ods_purchase_order_line: {len(po_lines)}")
    print(f"  ods_receipt:             {len(receipts)}")
    print(f"  ods_receipt_line:        {len(receipt_lines)}")
    print(f"  ods_ap_invoice:          {len(invoices)} (3 with negative amount)")
    print(f"  ods_ap_invoice_line:     {len(invoice_lines)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate synthetic PTP CSV data for HoneyBadge ETL",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="deploy/test-data/ptp_csv/",
        help="Output directory for CSV files",
    )
    parser.add_argument(
        "--batch-id",
        type=str,
        default=f"ETL-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
        help="ETL batch identifier",
    )
    parser.add_argument("--org-count", type=int, default=12, help="Number of organizations")
    parser.add_argument("--po-count", type=int, default=500, help="Number of purchase orders")
    args = parser.parse_args()

    generate_all(
        output_dir=Path(args.output_dir),
        batch_id=args.batch_id,
        org_count=args.org_count,
        po_count=args.po_count,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
