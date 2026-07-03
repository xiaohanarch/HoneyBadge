#!/usr/bin/env python3
"""
HoneyBadge PTP CSV Generator — Real Data from USAspending.gov

Fetches real US government purchase order data from the USAspending.gov API
(award type B = Purchase Order) and maps it to the HoneyBadge ODS schema.

Produces 9 CSV files matching ods_schema.sql DDL:
    ods_organization        — from awarding agencies (HHS, GSA, DoD, ...)
    ods_supplier            — from recipient names (real companies)
    ods_item                — from NAICS codes (real industry categories)
    ods_purchase_order      — real POs from API (amounts, dates, numbers)
    ods_purchase_order_line — generated from real PO amounts (1-5 lines/PO)
    ods_receipt             — 70% of POs get receipts
    ods_receipt_line        — linked to PO lines (three-way match)
    ods_ap_invoice          — ~40% of POs get invoices
    ods_ap_invoice_line     — linked to PO lines + receipt lines

Intentional dirty data (to exercise quality.py):
    - 1% of POs get malformed po_number (NOT NULL column, so format violation)
    - 0.5% of invoices get negative total_amount
    - 2 randomly selected suppliers get FROZEN status

Usage:
    python scripts/fetch_usaspending_ptp.py --limit 5000 --year 2024
    python scripts/fetch_usaspending_ptp.py --limit 10000 --output-dir deploy/test-data/usaspending_csv/
"""

import argparse
import csv
import json
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# ── Standard ETL columns (must match generate_ptp_csv.py / ods_schema.sql) ──
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
    """Return the 7 standard ETL columns as a dict."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "etl_batch_id": batch_id,
        "etl_load_time": now,
        "source_update_time": now,
        "source_system": source_system,
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

# ── Constants ───────────────────────────────────────────────────────────────
API_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
API_PAGE_SIZE = 100  # API max per page
API_DELAY_SEC = 0.3  # be respectful to the API
MAX_RETRIES = 3

random.seed(42)

# NAICS code prefix → category name (first 2 digits)
NAICS_CATEGORIES = {
    "11": "Agriculture & Forestry",
    "21": "Mining & Oil Gas",
    "22": "Utilities",
    "23": "Construction",
    "31": "Manufacturing", "32": "Manufacturing", "33": "Manufacturing",
    "42": "Wholesale Trade",
    "44": "Retail Trade", "45": "Retail Trade",
    "48": "Transportation", "49": "Transportation & Warehousing",
    "51": "Information Technology",
    "52": "Finance & Insurance",
    "53": "Real Estate",
    "54": "Professional Services",
    "55": "Management",
    "56": "Administrative Support",
    "61": "Educational Services",
    "62": "Health Care & Social Assistance",
    "71": "Arts & Entertainment",
    "72": "Accommodation & Food",
    "81": "Other Services",
    "92": "Public Administration",
}

BUYERS = [
    "James Smith", "Mary Johnson", "Robert Williams", "Patricia Brown",
    "John Davis", "Jennifer Miller", "Michael Wilson", "Linda Moore",
    "David Taylor", "Barbara Anderson",
]

PO_STATUSES = ["APPROVED"] * 7 + ["PENDING"] * 2 + ["CLOSED"] * 1
RECEIPT_STATUSES = ["RECEIVED", "PARTIALLY_RECEIVED", "PENDING"]
INVOICE_STATUSES = ["DRAFT", "VALIDATED", "APPROVED", "PAID", "CANCELLED", "ON_HOLD"]
UOM_CODES = ["EA", "KG", "M", "L", "PCS", "BOX", "LOT", "HR"]
PAYMENT_TERMS = ["NET30", "NET60", "NET90", "IMMEDIATE", "NET45"]


# ── API fetching ────────────────────────────────────────────────────────────

def _fetch_page(year: int, page: int) -> dict:
    """Fetch one page of purchase order awards from USAspending.gov."""
    body = {
        "filters": {
            "award_type_codes": ["B"],  # B = Purchase Order
            "time_period": [
                {"start_date": f"{year}-01-01", "end_date": f"{year}-12-31"}
            ],
        },
        "fields": [
            "Award ID",
            "Recipient Name",
            "Award Amount",
            "Awarding Agency",
            "Start Date",
            "End Date",
            "NAICS",
            "PSC",
        ],
        "page": page,
        "limit": API_PAGE_SIZE,
        "sort": "Award Amount",
        "order": "desc",
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_usaspending_pos(year: int, limit: int) -> list[dict]:
    """Fetch up to `limit` real purchase orders from USAspending.gov API."""
    results: list[dict] = []
    page = 1
    while len(results) < limit:
        for attempt in range(MAX_RETRIES):
            try:
                data = _fetch_page(year, page)
                break
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == MAX_RETRIES - 1:
                    print(f"  ERROR: API request failed after {MAX_RETRIES} retries: {exc}")
                    return results
                wait = 2 ** attempt
                print(f"  Retry {attempt+1}/{MAX_RETRIES} after {exc} (waiting {wait}s)...")
                time.sleep(wait)

        page_results = data.get("results", [])
        if not page_results:
            break

        for r in page_results:
            results.append(r)
            if len(results) >= limit:
                break

        meta = data.get("page_metadata", {})
        has_next = meta.get("hasNext", False)
        print(f"  Page {page}: fetched {len(page_results)} records (total: {len(results)}/{limit})")

        if not has_next or len(results) >= limit:
            break

        page += 1
        time.sleep(API_DELAY_SEC)

    return results


# ── Master data builders ────────────────────────────────────────────────────

def build_organizations(pos: list[dict], batch_id: str) -> tuple[list[dict], dict[str, int]]:
    """Extract unique awarding agencies as organizations. Returns (rows, name→id map)."""
    seen: dict[str, int] = {}
    rows: list[dict] = []
    next_id = 1000
    for po in pos:
        agency = po.get("Awarding Agency") or "UNKNOWN AGENCY"
        if agency not in seen:
            org_id = next_id
            next_id += 1
            seen[agency] = org_id
            row = {
                "org_id": org_id,
                "org_code": f"ORG{org_id}",
                "org_name": agency,
                "org_type": "LEGAL_ENTITY" if org_id == 1000 else "BUSINESS_UNIT",
                "parent_org_id": "" if org_id == 1000 else 1000,
                "legal_entity": agency if org_id == 1000 else "",
                "country": "US",
                "city": "Washington, DC",
                "status": "ACTIVE",
            }
            row.update(etl_row(batch_id, source_system="USASPENDING"))
            rows.append(row)
    return rows, seen


def build_suppliers(pos: list[dict], batch_id: str) -> tuple[list[dict], dict[str, int]]:
    """Extract unique recipient names as suppliers. Returns (rows, name→id map).
    2 randomly selected suppliers get FROZEN status (DQ issue)."""
    seen: dict[str, int] = {}
    rows: list[dict] = []
    next_id = 1
    for po in pos:
        name = po.get("Recipient Name") or "UNKNOWN SUPPLIER"
        if name not in seen:
            vid = next_id
            next_id += 1
            seen[name] = vid
            rows.append(name)

    # Select 2 suppliers for FROZEN status (or fewer if <4 suppliers)
    frozen_count = min(2, len(rows) // 10 + 1) if len(rows) > 4 else 0
    frozen_names = set(random.sample(rows, frozen_count)) if frozen_count else set()

    rows_final: list[dict] = []
    for i, name in enumerate(rows, 1):
        status = "FROZEN" if name in frozen_names else "ACTIVE"
        rating = random.choice(["AAA", "AA", "A", "BBB", "BB", "B"])
        row = {
            "vendor_id": i,
            "vendor_number": f"US-SUP{i:05d}",
            "vendor_name": name,
            "vendor_type": "ENTERPRISE",
            "status": status,
            "country": "US",
            "city": "Various",
            "address": f"US Business Address {i}",
            "contact_person": f"Contact {i}",
            "contact_phone": f"+1-555-{i:04d}",
            "contact_email": f"vendor{i}@example.com",
            "bank_account": f"US{i:08d}",
            "bank_name": "Bank of America",
            "vat_registration_num": f"US-TIN-{i:08d}",
            "payment_terms": PAYMENT_TERMS[i % len(PAYMENT_TERMS)],
            "credit_rating": rating,
            "start_date": _ts_local(0),
            "end_date": _ts_local(365),
            "org_id": 1000,
        }
        row.update(etl_row(batch_id, source_system="USASPENDING"))
        rows_final.append(row)
    return rows_final, seen


def build_items(pos: list[dict], batch_id: str) -> tuple[list[dict], dict[str, int]]:
    """Extract unique NAICS codes as items. Returns (rows, naics_code→id map)."""
    seen: dict[str, int] = {}
    rows: list[dict] = []
    next_id = 1
    for po in pos:
        naics = po.get("NAICS") or {}
        code = naics.get("code") or "UNKNOWN"
        if code not in seen:
            item_id = next_id
            next_id += 1
            seen[code] = item_id
            desc = naics.get("description") or "Unknown Category"
            prefix = code[:2] if len(code) >= 2 else "81"
            category = NAICS_CATEGORIES.get(prefix, "Other Services")
            psc = po.get("PSC") or {}
            psc_desc = psc.get("description") or ""
            cost = (item_id * 137) % 9900 + 100
            row = {
                "inventory_item_id": item_id,
                "item_number": f"NAICS-{code}",
                "item_name": desc,
                "item_description": psc_desc or desc,
                "item_type": "SERVICE" if prefix in {"54", "56", "61", "62", "81"} else "FINISHED_GOOD",
                "category": category,
                "uom": UOM_CODES[item_id % len(UOM_CODES)],
                "standard_cost": f"{cost}.00",
                "list_price": f"{cost * 1.2:.2f}",
                "weight": f"{(item_id % 10) + 0.5}",
                "weight_uom": "KG",
                "lead_time_days": (item_id % 5) + 1,
                "safety_stock": "50.0",
                "min_order_qty": "10.0",
                "status": "ACTIVE",
                "abc_class": ["A", "B", "C"][item_id % 3],
                "org_id": 1000,
            }
            row.update(etl_row(batch_id, source_system="USASPENDING"))
            rows.append(row)
    return rows, seen


# ── Purchase orders ─────────────────────────────────────────────────────────

def _ts(date_str: str | None, offset_days: int = 0) -> str:
    """Parse an ISO date string from the API and return a timestamp string."""
    if not date_str:
        return ""
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    dt = dt + timedelta(days=offset_days)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _ts_local(offset_days: int = 0) -> str:
    """Return a timestamp string offset from now."""
    return (datetime(2024, 1, 1) + timedelta(days=offset_days)).strftime("%Y-%m-%d %H:%M:%S")


def build_purchase_orders(
    pos: list[dict],
    org_map: dict[str, int],
    supplier_map: dict[str, int],
    batch_id: str,
) -> list[dict]:
    """Map API results to ODS purchase_order records.
    1% of POs get malformed po_number (DQ issue — NOT NULL column, so format violation)."""
    rows: list[dict] = []
    bad_count = max(1, len(pos) // 100)  # ~1% malformed po_number
    bad_indices = set(random.sample(range(len(pos)), min(bad_count, len(pos))))

    for i, po in enumerate(pos):
        po_header_id = i + 1
        agency = po.get("Awarding Agency") or "UNKNOWN AGENCY"
        recipient = po.get("Recipient Name") or "UNKNOWN SUPPLIER"
        org_id = org_map.get(agency, 1000)
        vendor_id = supplier_map.get(recipient, 1)

        amount = po.get("Award Amount") or 0.0
        start_date = po.get("Start Date") or "2024-01-01"
        end_date = po.get("End Date") or ""

        # Derive status from dates
        today = datetime(2024, 12, 31)
        try:
            start_dt = datetime.strptime(start_date[:10], "%Y-%m-%d")
        except ValueError:
            start_dt = today
        if end_date:
            try:
                end_dt = datetime.strptime(end_date[:10], "%Y-%m-%d")
                status = "CLOSED" if end_dt < today else "APPROVED"
            except ValueError:
                status = "APPROVED"
        else:
            status = "APPROVED" if start_dt <= today else "PENDING"

        po_number = f"BAD-US-{i}" if i in bad_indices else (po.get("Award ID") or f"PO-{po_header_id:06d}")

        row = {
            "po_header_id": po_header_id,
            "po_number": po_number,
            "po_type": "STANDARD",
            "description": f"USAspending PO - {agency[:40]}",
            "status": status,
            "buyer_id": (po_header_id % 10) + 1,
            "buyer_name": BUYERS[po_header_id % len(BUYERS)],
            "vendor_id": vendor_id,
            "vendor_name": recipient[:200],
            "order_date": _ts(start_date),
            "approved_date": _ts(start_date, offset_days=2) if status != "PENDING" else "",
            "total_amount": f"{amount:.2f}",
            "currency_code": "USD",
            "exchange_rate": "7.25",
            "payment_terms": PAYMENT_TERMS[po_header_id % len(PAYMENT_TERMS)],
            "freight_terms": "STANDARD",
            "ship_to_location": f"US Facility-{org_id}",
            "bill_to_location": f"US Billing-{org_id}",
            "close_date": _ts(end_date) if status == "CLOSED" else "",
            "cancel_reason": "",
            "org_id": org_id,
        }
        row.update(etl_row(batch_id, source_system="USASPENDING"))
        rows.append(row)
    return rows


# ── Line-level data generators ──────────────────────────────────────────────

def gen_po_lines(
    po_rows: list[dict],
    item_map: dict[str, int],
    pos_raw: list[dict],
    batch_id: str,
) -> list[dict]:
    """Split each PO into 1-5 lines. Amount distributed across lines."""
    rows: list[dict] = []
    line_id = 0
    for po, po_raw in zip(po_rows, pos_raw, strict=False):
        total = float(po["total_amount"]) if po["total_amount"] else 0.0
        num_lines = min(random.randint(1, 5), max(1, int(total / 1000) + 1))
        # Pick a NAICS item for this PO
        naics = po_raw.get("NAICS") or {}
        naics_code = naics.get("code") or "UNKNOWN"
        item_id = item_map.get(naics_code, 1)

        # Distribute amount across lines
        weights = [random.randint(1, 10) for _ in range(num_lines)]
        total_weight = sum(weights)

        for ln in range(1, num_lines + 1):
            line_id += 1
            line_amount = (total * weights[ln - 1] / total_weight) if total_weight else 0
            unit_price = max(1, line_amount / max(1, random.randint(10, 500)))
            quantity = max(1, int(line_amount / unit_price)) if unit_price else 1
            # Recalculate amount to be consistent
            amount = quantity * unit_price
            order_day_offset = (po["po_header_id"] * 3) % 350

            row = {
                "po_line_id": line_id,
                "po_header_id": po["po_header_id"],
                "line_number": ln,
                "line_type": "GOODS",
                "item_id": item_id,
                "item_description": (naics.get("description") or "Unknown Item")[:200],
                "quantity": f"{quantity:.2f}",
                "unit_price": f"{unit_price:.4f}",
                "amount": f"{amount:.2f}",
                "uom": UOM_CODES[item_id % len(UOM_CODES)],
                "need_by_date": _ts_local(order_day_offset + 14),
                "promised_date": _ts_local(order_day_offset + 10),
                "received_quantity": "0",
                "invoiced_quantity": "0",
                "status": po["status"],
                "tax_code": "SALES_TAX",
                "tax_rate": "0.08",
                "org_id": po["org_id"],
            }
            row.update(etl_row(batch_id, source_system="USASPENDING"))
            rows.append(row)
    return rows


def gen_receipts(po_rows: list[dict], batch_id: str) -> list[dict]:
    """70% of POs get a receipt. receipt_date = order_date + 7 days."""
    rows: list[dict] = []
    shipment_header_id = 0
    for po in po_rows:
        if random.random() > 0.7:
            continue
        shipment_header_id += 1
        po_header_id = po["po_header_id"]
        order_date_str = po["order_date"]
        offset = 7
        receipt_date = _ts(order_date_str, offset_days=offset) if order_date_str else _ts_local(7)

        row = {
            "shipment_header_id": shipment_header_id,
            "receipt_number": f"RCV-{po_header_id:06d}",
            "receipt_type": "STANDARD",
            "receipt_date": receipt_date,
            "status": random.choice(RECEIPT_STATUSES),
            "receiver_id": (po_header_id % 10) + 1,
            "receiver_name": BUYERS[po_header_id % len(BUYERS)],
            "po_header_id": po_header_id,
            "total_quantity": str(random.randint(50, 800)),
            "warehouse_code": f"WH-{po['org_id']}",
            "comments": "",
            "org_id": po["org_id"],
        }
        row.update(etl_row(batch_id, source_system="USASPENDING"))
        rows.append(row)
    return rows


def gen_receipt_lines(
    receipt_rows: list[dict],
    po_line_rows: list[dict],
    batch_id: str,
) -> list[dict]:
    """Link receipt lines to PO lines."""
    rows: list[dict] = []
    shipment_line_id = 0
    po_lines_by_header: dict[int, list[dict]] = {}
    for pl in po_line_rows:
        po_lines_by_header.setdefault(pl["po_header_id"], []).append(pl)

    for rcv in receipt_rows:
        po_header_id = rcv["po_header_id"]
        po_lines = po_lines_by_header.get(po_header_id, [])
        if not po_lines:
            continue
        num_rcv = min(len(po_lines), random.randint(1, 3))
        for ln in range(1, num_rcv + 1):
            shipment_line_id += 1
            po_line = po_lines[ln - 1]
            ordered_qty = float(po_line["quantity"])
            received_qty = ordered_qty if rcv["status"] == "RECEIVED" else ordered_qty / 2
            rejected_qty = random.randint(0, 5) if random.random() < 0.1 else 0
            accepted_qty = received_qty - rejected_qty
            row = {
                "shipment_line_id": shipment_line_id,
                "shipment_header_id": rcv["shipment_header_id"],
                "po_line_id": po_line["po_line_id"],
                "line_number": ln,
                "item_id": po_line["item_id"],
                "received_quantity": f"{received_qty:.2f}",
                "accepted_quantity": f"{accepted_qty:.2f}",
                "rejected_quantity": f"{rejected_qty}",
                "uom": po_line["uom"],
                "inspection_status": "PASSED" if rejected_qty == 0 else "FAILED",
                "lot_number": f"LOT-{shipment_line_id:06d}",
                "subinventory": f"SUB-{rcv['org_id']}",
                "sublocation": f"LOC-{shipment_line_id:04d}",
                "org_id": rcv["org_id"],
            }
            row.update(etl_row(batch_id, source_system="USASPENDING"))
            rows.append(row)
    return rows


def gen_invoices(po_rows: list[dict], batch_id: str) -> list[dict]:
    """~40% of POs get an invoice. 0.5% get negative amount (DQ issue)."""
    rows: list[dict] = []
    inv_id = 0
    negative_count = max(1, len(po_rows) // 200)
    negative_indices = set(
        random.sample(range(len(po_rows)), min(negative_count, len(po_rows)))
    )

    for i, po in enumerate(po_rows):
        if random.random() > 0.4:
            continue
        inv_id += 1
        po_header_id = po["po_header_id"]
        amount = float(po["total_amount"]) if po["total_amount"] else 0.0
        if i in negative_indices:
            amount = -abs(amount)  # intentional negative
        order_date_str = po["order_date"]
        inv_date = _ts(order_date_str, offset_days=10) if order_date_str else _ts_local(10)

        row = {
            "invoice_id": inv_id,
            "invoice_number": f"INV-{po['org_id']}-{inv_id:05d}",
            "invoice_type": "STANDARD",
            "vendor_id": po["vendor_id"],
            "vendor_name": po["vendor_name"],
            "vendor_site_id": (po["vendor_id"] % 5) + 1,
            "invoice_date": inv_date,
            "due_date": _ts(inv_date, offset_days=30) if inv_date else "",
            "status": random.choice(INVOICE_STATUSES),
            "total_amount": f"{amount:.2f}",
            "tax_amount": f"{abs(amount) * 0.08:.2f}",
            "currency_code": "USD",
            "exchange_rate": "7.25",
            "payment_method": "BANK_TRANSFER",
            "description": f"USAspending Invoice-{inv_id}",
            "gl_date": inv_date,
            "po_header_id": po_header_id,
            "org_id": po["org_id"],
        }
        row.update(etl_row(batch_id, source_system="USASPENDING"))
        rows.append(row)
    return rows


def gen_invoice_lines(
    invoice_rows: list[dict],
    po_line_rows: list[dict],
    receipt_line_rows: list[dict],
    batch_id: str,
) -> list[dict]:
    """Link invoice lines to PO lines + receipt lines (three-way match)."""
    rows: list[dict] = []
    inv_line_id = 0
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
        num_inv = min(len(po_lines), random.randint(1, 5))
        for ln in range(1, num_inv + 1):
            inv_line_id += 1
            po_line = po_lines[ln - 1]
            po_line_id = po_line["po_line_id"]
            rcv_lines = rcv_lines_by_po_line.get(po_line_id, [])
            receipt_line_id = rcv_lines[0]["shipment_line_id"] if rcv_lines else ""
            quantity = float(po_line["quantity"])
            unit_price = float(po_line["unit_price"])
            amount = quantity * unit_price
            row = {
                "invoice_line_id": inv_line_id,
                "invoice_id": inv["invoice_id"],
                "line_number": ln,
                "line_type": "ITEM",
                "item_id": po_line["item_id"],
                "item_description": po_line["item_description"],
                "quantity": f"{quantity:.2f}",
                "unit_price": f"{unit_price:.4f}",
                "amount": f"{amount:.2f}",
                "tax_code": "SALES_TAX",
                "tax_rate": "0.08",
                "po_line_id": po_line_id,
                "receipt_line_id": receipt_line_id,
                "description": f"USAspending InvLine-{inv_line_id}",
                "org_id": inv["org_id"],
            }
            row.update(etl_row(batch_id, source_system="USASPENDING"))
            rows.append(row)
    return rows


# ── Orchestration ───────────────────────────────────────────────────────────

def generate_all(
    pos_raw: list[dict],
    output_dir: Path,
    batch_id: str,
) -> None:
    """Build all 9 ODS CSV files from raw USAspending PO data."""
    print(f"\nBuilding ODS CSVs from {len(pos_raw)} real purchase orders -> {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Master data
    orgs, org_map = build_organizations(pos_raw, batch_id)
    write_csv(output_dir / "ods_organization.csv", FIELD_MAP["ods_organization"], orgs)

    suppliers, supplier_map = build_suppliers(pos_raw, batch_id)
    write_csv(output_dir / "ods_supplier.csv", FIELD_MAP["ods_supplier"], suppliers)

    items, item_map = build_items(pos_raw, batch_id)
    write_csv(output_dir / "ods_item.csv", FIELD_MAP["ods_item"], items)

    # Purchase orders
    po_rows = build_purchase_orders(pos_raw, org_map, supplier_map, batch_id)
    write_csv(output_dir / "ods_purchase_order.csv", FIELD_MAP["ods_purchase_order"], po_rows)

    # Line-level data
    po_lines = gen_po_lines(po_rows, item_map, pos_raw, batch_id)
    write_csv(output_dir / "ods_purchase_order_line.csv", FIELD_MAP["ods_purchase_order_line"], po_lines)

    receipts = gen_receipts(po_rows, batch_id)
    write_csv(output_dir / "ods_receipt.csv", FIELD_MAP["ods_receipt"], receipts)

    receipt_lines = gen_receipt_lines(receipts, po_lines, batch_id)
    write_csv(output_dir / "ods_receipt_line.csv", FIELD_MAP["ods_receipt_line"], receipt_lines)

    invoices = gen_invoices(po_rows, batch_id)
    write_csv(output_dir / "ods_ap_invoice.csv", FIELD_MAP["ods_ap_invoice"], invoices)

    invoice_lines = gen_invoice_lines(invoices, po_lines, receipt_lines, batch_id)
    write_csv(output_dir / "ods_ap_invoice_line.csv", FIELD_MAP["ods_ap_invoice_line"], invoice_lines)

    # Summary
    frozen_count = sum(1 for s in suppliers if s["status"] == "FROZEN")
    null_po_count = sum(1 for p in po_rows if p["po_number"].startswith("BAD-"))
    neg_inv_count = sum(1 for i in invoices if float(i["total_amount"]) < 0)

    print(f"\n{'='*60}")
    print(f"USAspending PTP CSV Generation Complete (batch={batch_id})")
    print(f"{'='*60}")
    print(f"  ods_organization:        {len(orgs):>6}  (real US government agencies)")
    print(f"  ods_supplier:            {len(suppliers):>6}  (real company names, {frozen_count} FROZEN)")
    print(f"  ods_item:                {len(items):>6}  (from NAICS industry codes)")
    print(f"  ods_purchase_order:      {len(po_rows):>6}  (real POs, {null_po_count} with malformed po_number)")
    print(f"  ods_purchase_order_line: {len(po_lines):>6}  (generated from real PO amounts)")
    print(f"  ods_receipt:             {len(receipts):>6}")
    print(f"  ods_receipt_line:        {len(receipt_lines):>6}")
    print(f"  ods_ap_invoice:          {len(invoices):>6}  ({neg_inv_count} with negative amount)")
    print(f"  ods_ap_invoice_line:     {len(invoice_lines):>6}")
    total = len(orgs) + len(suppliers) + len(items) + len(po_rows) + len(po_lines) + len(receipts) + len(receipt_lines) + len(invoices) + len(invoice_lines)
    print(f"  {'TOTAL ROWS':<25} {total:>6}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch real purchase order data from USAspending.gov and generate PTP ODS CSVs",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum number of POs to fetch (default: 5000)",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=2024,
        help="Fiscal year to fetch data for (default: 2024)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="deploy/test-data/usaspending_csv/",
        help="Output directory for CSV files",
    )
    parser.add_argument(
        "--batch-id",
        type=str,
        default=f"USASPENDING-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        help="ETL batch identifier",
    )
    args = parser.parse_args()

    print(f"Fetching {args.limit} purchase orders from USAspending.gov (FY{args.year})...")
    pos_raw = fetch_usaspending_pos(args.year, args.limit)

    if not pos_raw:
        print("ERROR: No data fetched from USAspending.gov API. Exiting.")
        return 1

    print(f"Fetched {len(pos_raw)} real purchase orders.")

    generate_all(
        pos_raw=pos_raw,
        output_dir=Path(args.output_dir),
        batch_id=args.batch_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
