#!/usr/bin/env python3
"""
HoneyBadge Phase 1 Test Data Generator

Generates 1M+ realistic ERP test records for Oracle EBS simulation.
Outputs CSV files in nebula-importer format for NebulaGraph import.

Usage:
    python scripts/generate_test_data.py [--records N] [--output-dir PATH]

Author: HoneyBadge Team
Date: 2026-04-05
"""

import argparse
import csv
import random
import uuid
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path
import sys

# =============================================================================
# Configuration Constants
# =============================================================================

# Entity counts for data generation
NUM_SUPPLIERS = 100
NUM_CUSTOMERS = 80
NUM_ITEMS = 500
NUM_ORGANIZATIONS = 10
NUM_EMPLOYEES = 50
NUM_WAREHOUSES = 5
NUM_GL_ACCOUNTS = 30
NUM_CURRENCIES = 8
NUM_UOMS = 15

# Transaction counts (reduced for testing - full ~500K)
NUM_PURCHASE_REQUISITIONS = 1000
NUM_PURCHASE_ORDERS = 3000
NUM_RECEIPTS = 2500
NUM_INVOICES = 3000
NUM_PAYMENTS = 2000
NUM_SALES_ORDERS = 2000
NUM_SHIPMENTS = 1800
NUM_AR_INVOICES = 1500
NUM_AR_RECEIPTS = 1000
NUM_GL_JOURNAL_ENTRIES = 5000
NUM_XLA_EVENTS = 6000
NUM_APPROVAL_RECORDS = 5000
NUM_CONTRACTS = 200
NUM_BOMS = 50

# v2.0 new entity counts
NUM_SUPPLIER_SITES = 250       # ~2.5 per supplier
NUM_CUSTOMER_SITES = 200       # ~2.5 per customer
NUM_EXPENSE_REPORTS = 500
NUM_INVENTORY_TXNS = 3000
NUM_ITEM_CATEGORIES = 30
NUM_BANK_ACCOUNTS = 20
NUM_BANK_STATEMENTS = 100
NUM_LEDGERS = 3
NUM_GL_PERIODS = 24            # 24 months
NUM_GL_CODE_COMBINATIONS = 100
NUM_GL_JOURNAL_BATCHES = 500
NUM_CURRENCY_RATES = 200

# Anomaly rates (realistic noisy data)
THREE_WAY_MATCH_FAILURE_RATE = 0.05  # 5%
TEMPORAL_VIOLATION_RATE = 0.03  # 3%
DUPLICATE_INVOICE_RATE = 0.015  # 1.5%
EXPIRED_QUALIFICATION_RATE = 0.10  # 10% of suppliers

# Anomaly pattern constants (Phase 1 - 6 fraud patterns)
NUM_CIRCULAR_TRADING_GROUPS = 2      # 2 groups of 3 suppliers each
NUM_SPLIT_PO_GROUPS = 3              # 3 split-PO groups
APPROVAL_THRESHOLD = 500000          # 50万元 approval threshold
NUM_BLOCKED_SUPPLIER_POS = 5         # POs to blocked suppliers
NUM_SUSPICIOUS_BANK_CHANGES = 3      # suppliers with suspicious bank changes
BLOCKED_SUPPLIER_NUMBERS = ["SUP00091", "SUP00092", "SUP00093"]

# OTC anomaly pattern constants (Phase 1 - patterns 7-9)
NUM_GHOST_SHIPMENTS = 4                   # SOs with inflated/phantom shipments
NUM_CREDIT_MEMO_FRAUDS = 3                # credit memos after AR receipts

# PTP+OTC cross-process fraud constants (Phase 1 - patterns 10-12)
NUM_ROUND_TRIP_PAIRS = 2                  # supplier-customer round-trip pairs
NUM_TRANSFER_PRICING_ITEMS = 3            # items with buy-high-sell-low pricing
NUM_SHIP_BEFORE_RECEIPT = 3               # items shipped before supplier receipt

# Time range for data (24 months)
DATA_START_DATE = datetime(2024, 4, 1)
DATA_END_DATE = datetime(2026, 4, 1)

# Output configuration
BATCH_SIZE = 50  # Records per CSV file

# =============================================================================
# VID Prefix Constants (aligned with constants.py)
# =============================================================================

VID_PREFIX_SUPPLIER = "SUP"
VID_PREFIX_CUSTOMER = "CUS"
VID_PREFIX_ITEM = "ITM"
VID_PREFIX_ORG = "ORG"
VID_PREFIX_EMPLOYEE = "EMP"
VID_PREFIX_WAREHOUSE = "WH"
VID_PREFIX_BOM = "BOM"
VID_PREFIX_BOM_COMP = "BOMC"
VID_PREFIX_PR = "PR"
VID_PREFIX_PR_LINE = "PRL"
VID_PREFIX_PO = "PO"
VID_PREFIX_PO_LINE = "POL"
VID_PREFIX_RECEIPT = "RCV"
VID_PREFIX_RECEIPT_LINE = "RCVL"
VID_PREFIX_QUALIFICATION = "SQ"
VID_PREFIX_INVOICE = "INV"
VID_PREFIX_INVOICE_LINE = "INVL"
VID_PREFIX_PAYMENT = "PAY"
VID_PREFIX_PAYMENT_BATCH = "PB"
VID_PREFIX_SO = "SO"
VID_PREFIX_SO_LINE = "SOL"
VID_PREFIX_SHIPMENT = "SHP"
VID_PREFIX_SHIPMENT_LINE = "SHPL"
VID_PREFIX_AR_INVOICE = "ARI"
VID_PREFIX_AR_RECEIPT = "ARR"
VID_PREFIX_GL_ACCOUNT = "GLA"
VID_PREFIX_JOURNAL = "JLE"
VID_PREFIX_JOURNAL_LINE = "JLL"
VID_PREFIX_XLA_EVENT = "XLA"
VID_PREFIX_ACCT_DIST = "ACD"
VID_PREFIX_APPROVAL = "APR"
VID_PREFIX_CONTRACT = "CNT"
VID_PREFIX_CURRENCY = "CUR"
VID_PREFIX_UOM = "UOM"

# v2.0 new VID prefixes
VID_PREFIX_SUPPLIER_SITE = "SUPS"
VID_PREFIX_CUSTOMER_SITE = "CUSS"
VID_PREFIX_PO_SHIPMENT = "POSH"
VID_PREFIX_RCV_TXN = "RCVT"
VID_PREFIX_INV_DIST = "INVD"
VID_PREFIX_INV_HOLD = "INVH"
VID_PREFIX_PAY_SCHEDULE = "PAYS"
VID_PREFIX_EXPENSE = "EXP"
VID_PREFIX_ARI_LINE = "ARIL"
VID_PREFIX_LEDGER = "LDG"
VID_PREFIX_GL_PERIOD = "GLP"
VID_PREFIX_CCID = "CCID"
VID_PREFIX_GL_BATCH = "GLB"
VID_PREFIX_GL_BALANCE = "GLBL"
VID_PREFIX_CURRENCY_RATE = "CXRT"
VID_PREFIX_XLA_JOURNAL = "XLAJ"
VID_PREFIX_XLA_LINE = "XLAL"
VID_PREFIX_XLA_DIST_LINK = "XLDL"
VID_PREFIX_INV_TXN = "INVT"
VID_PREFIX_ITEM_CAT = "ICAT"
VID_PREFIX_BANK_ACCT = "BACT"
VID_PREFIX_BANK_STMT = "BSTM"
VID_PREFIX_BANK_STMT_LINE = "BSTL"

# =============================================================================
# Chinese Name Data
# =============================================================================

CHINESE_SURNAMES = [
    "王", "李", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴",
    "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗",
    "梁", "宋", "郑", "谢", "韩", "唐", "冯", "于", "董", "萧",
    "程", "曹", "袁", "邓", "许", "傅", "沈", "曾", "彭", "吕",
    "苏", "卢", "蒋", "蔡", "贾", "丁", "魏", "薛", "叶", "阎",
]

CHINESE_GIVEN_NAMES = [
    "伟", "芳", "娜", "敏", "静", "丽", "强", "磊", "军", "洋",
    "勇", "艳", "杰", "娟", "涛", "明", "超", "秀英", "华", "平",
    "刚", "桂英", "建华", "建国", "俊杰", "志明", "志强", "秀兰", "婷", "慧",
    "建军", "海", "军", "杰", "鹏", "飞", "霞", "梅", "琳", "云",
    "凤兰", "英", "锋", "玲", "宇", "浩", "凯", "博", "鑫", "龙",
]

SUPPLIER_PREFIXES = [
    "上海", "北京", "广州", "深圳", "杭州", "苏州", "南京", "武汉", "成都", "西安",
    "重庆", "天津", "青岛", "大连", "沈阳", "长沙", "郑州", "济南", "福州", "厦门",
]

SUPPLIER_SUFFIXES = [
    "贸易有限公司", "实业有限公司", "科技有限公司", "工业有限公司", "物资有限公司",
    "材料有限公司", "设备有限公司", "电子有限公司", "机械有限公司", "化工有限公司",
    "建材有限公司", "金属有限公司", "纺织有限公司", "食品有限公司", "包装有限公司",
]

ITEM_CATEGORIES = [
    "原材料-金属", "原材料-塑料", "原材料-化工", "原材料-纺织", "原材料-电子",
    "半成品-部件", "半成品-组件", "成品-设备", "成品-仪器", "成品-工具",
    "辅料-包装", "辅料-辅助", "备件-机械", "备件-电气", "办公用品",
]

ITEM_TYPES = ["RAW", "SEMI", "FINISHED", "SUB", "PS"]

CITIES = [
    ("北京", "北京"), ("上海", "上海"), ("广州", "广东"), ("深圳", "广东"),
    ("杭州", "浙江"), ("苏州", "江苏"), ("南京", "江苏"), ("武汉", "湖北"),
    ("成都", "四川"), ("西安", "陕西"), ("重庆", "重庆"), ("天津", "天津"),
    ("青岛", "山东"), ("大连", "辽宁"), ("沈阳", "辽宁"), ("长沙", "湖南"),
    ("郑州", "河南"), ("济南", "山东"), ("福州", "福建"), ("厦门", "福建"),
]

DEPARTMENTS = [
    "采购部", "销售部", "财务部", "仓库部", "生产部", "质量部", "工程部",
    "人力资源部", "IT部", "行政部", "物流部", "研发部", "市场部", "商务部",
]

POSITIONS = [
    "采购员", "采购经理", "销售员", "销售经理", "会计", "财务经理",
    "仓管员", "仓库经理", "质量工程师", "生产主管", "设备工程师",
    "HR专员", "HR经理", "IT工程师", "IT经理", "物流专员", "物流经理",
]

WAREHOUSE_TYPES = ["原材料仓", "成品仓", "半成品仓", "危险品仓", "冷链仓", "暂存仓"]

# =============================================================================
# Helper Functions
# =============================================================================

def random_date(start: datetime, end: datetime) -> datetime:
    """Generate a random date between start and end."""
    delta = end - start
    random_days = random.randint(0, delta.days)
    random_seconds = random.randint(0, 86399)
    return start + timedelta(days=random_days, seconds=random_seconds)

def random_phone() -> str:
    """Generate a random Chinese mobile phone number."""
    prefixes = ["130", "131", "132", "133", "134", "135", "136", "137", "138", "139",
                "150", "151", "152", "153", "155", "156", "157", "158", "159",
                "170", "171", "172", "173", "175", "176", "177", "178",
                "180", "181", "182", "183", "184", "185", "186", "187", "188", "189"]
    return f"{random.choice(prefixes)}{random.randint(10000000, 99999999)}"

def random_company_name() -> str:
    """Generate a realistic Chinese company name."""
    return f"{random.choice(SUPPLIER_PREFIXES)}{random.choice(CHINESE_SURNAMES)}{random.choice(CHINESE_GIVEN_NAMES)}{random.choice(SUPPLIER_SUFFIXES)}"

def random_person_name() -> str:
    """Generate a random Chinese person name."""
    return f"{random.choice(CHINESE_SURNAMES)}{random.choice(CHINESE_GIVEN_NAMES)}"

def random_item_name(category: str) -> str:
    """Generate a random item name based on category."""
    prefixes = ["优等", "标准", "普通", "高纯", "工业级", "食品级", "医疗级"]
    suffixes = {
        "原材料-金属": ["钢板", "钢管", "钢丝", "铜棒", "铝锭", "锌锭", "镍板"],
        "原材料-塑料": ["PVC粒", "PP粒", "PE粒", "ABS粒", "PC粒", "PA粒"],
        "原材料-化工": ["甲苯", "乙醇", "丙酮", "硫酸", "盐酸", "氢氧化钠"],
        "原材料-纺织": ["棉纱", "涤纶丝", "尼龙丝", "粘胶丝", "氨纶丝"],
        "原材料-电子": ["电容", "电阻", "IC芯片", "PCB板", "连接器"],
        "半成品-部件": ["冲压件", "注塑件", "铸造件", "焊接件", "钣金件"],
        "半成品-组件": ["模块", "总成", "部件", "装置", "组件"],
        "成品-设备": ["主机", "机组", "装置", "系统", "设备"],
        "成品-仪器": ["仪表", "仪器", "表计", "传感器", "监测仪"],
        "成品-工具": ["刀具", "量具", "夹具", "模具", "工装"],
        "辅料-包装": ["纸箱", "木箱", "托盘", "包装膜", "标签"],
        "辅料-辅助": ["润滑油", "清洁剂", "胶水", "胶带", "砂纸"],
        "备件-机械": ["轴承", "齿轮", "皮带", "链条", "密封件"],
        "备件-电气": ["接触器", "断路器", "继电器", "开关", "电缆"],
        "办公用品": ["打印纸", "墨盒", "笔", "文件夹", "订书机"],
    }
    suffix_list = suffixes.get(category, ["物料"])
    return f"{random.choice(prefixes)}{random.choice(suffix_list)}"

def generate_tax_id() -> str:
    """Generate a random Chinese tax ID (统一社会信用代码)."""
    return f"{random.randint(100000, 999999)}{random.randint(100000, 999999)}{random.choice('ABCDEFGH')}{random.randint(100000000, 999999999)}"

def generate_bank_account() -> str:
    """Generate a random bank account number."""
    return f"{random.randint(100000, 999999)}{random.randint(100000000, 999999999)}{random.randint(1000, 9999)}"

def vid(prefix: str, key: str) -> str:
    """Generate a VID in format {Prefix}:{Key}."""
    return f"{prefix}:{key}"

def format_timestamp(dt: datetime) -> str:
    """Format datetime for NebulaGraph CSV."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000000Z")

# =============================================================================
# Data Generator Classes
# =============================================================================

@dataclass
class DataRegistry:
    """Central registry for all generated entity IDs."""

    # Master data
    suppliers: list[str] = field(default_factory=list)
    customers: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)
    organizations: list[str] = field(default_factory=list)
    employees: list[str] = field(default_factory=list)
    warehouses: list[str] = field(default_factory=list)
    gl_accounts: list[str] = field(default_factory=list)
    currencies: list[str] = field(default_factory=list)
    uoms: list[str] = field(default_factory=list)

    # Procurement
    purchase_requisitions: list[str] = field(default_factory=list)
    purchase_orders: list[str] = field(default_factory=list)
    receipts: list[str] = field(default_factory=list)
    invoices: list[str] = field(default_factory=list)
    payments: list[str] = field(default_factory=list)
    payment_batches: list[str] = field(default_factory=list)
    # (pay_vid, payment_date, org_id, amount, currency) for batch grouping
    payment_details: list[tuple] = field(default_factory=list)

    # OTC
    sales_orders: list[str] = field(default_factory=list)
    shipments: list[str] = field(default_factory=list)
    ar_invoices: list[str] = field(default_factory=list)
    ar_receipts: list[str] = field(default_factory=list)

    # Accounting
    gl_journal_entries: list[str] = field(default_factory=list)
    xla_events: list[str] = field(default_factory=list)

    # Other
    approvals: list[str] = field(default_factory=list)
    contracts: list[str] = field(default_factory=list)
    boms: list[str] = field(default_factory=list)

    # v2.0 new entities
    supplier_sites: list[str] = field(default_factory=list)
    customer_sites: list[str] = field(default_factory=list)
    po_shipments: list[str] = field(default_factory=list)
    receiving_transactions: list[str] = field(default_factory=list)
    invoice_distributions: list[str] = field(default_factory=list)
    invoice_holds: list[str] = field(default_factory=list)
    payment_schedules: list[str] = field(default_factory=list)
    expense_reports: list[str] = field(default_factory=list)
    ar_invoice_lines: list[str] = field(default_factory=list)
    ledgers: list[str] = field(default_factory=list)
    gl_periods: list[str] = field(default_factory=list)
    gl_code_combinations: list[str] = field(default_factory=list)
    gl_journal_batches: list[str] = field(default_factory=list)
    gl_balances: list[str] = field(default_factory=list)
    currency_rates: list[str] = field(default_factory=list)
    xla_journal_entries: list[str] = field(default_factory=list)
    xla_journal_lines: list[str] = field(default_factory=list)
    xla_dist_links: list[str] = field(default_factory=list)
    inventory_transactions: list[str] = field(default_factory=list)
    item_categories: list[str] = field(default_factory=list)
    bank_accounts: list[str] = field(default_factory=list)
    bank_statements: list[str] = field(default_factory=list)
    bank_statement_lines: list[str] = field(default_factory=list)

    # Edge mappings (source_id -> list of target_ids)
    po_to_supplier: dict[str, str] = field(default_factory=dict)
    po_to_employee: dict[str, str] = field(default_factory=dict)
    receipt_to_po: dict[str, str] = field(default_factory=dict)
    invoice_to_po: dict[str, str] = field(default_factory=dict)
    payment_to_invoice: dict[str, list[str]] = field(default_factory=dict)

    so_to_customer: dict[str, str] = field(default_factory=dict)
    shipment_to_so: dict[str, str] = field(default_factory=dict)
    ar_invoice_to_so: dict[str, str] = field(default_factory=dict)
    ar_receipt_to_ar_invoice: dict[str, list[str]] = field(default_factory=dict)

    # v2.0 edge mappings
    supplier_to_sites: dict[str, list[str]] = field(default_factory=dict)
    customer_to_sites: dict[str, list[str]] = field(default_factory=dict)
    po_line_to_shipments: dict[str, list[str]] = field(default_factory=dict)
    invoice_to_distributions: dict[str, list[str]] = field(default_factory=dict)

    # Three-way match tracking for anomaly injection
    invoice_amount_by_po_line: dict[str, float] = field(default_factory=dict)
    receipt_amount_by_po_line: dict[str, float] = field(default_factory=dict)

    # Anomaly tracking
    po_to_receipt_date: dict[str, datetime] = field(default_factory=dict)   # po_number -> receipt_date
    item_to_category: dict[str, str] = field(default_factory=dict)          # item_vid -> category_vid
    invoice_dates: dict[str, datetime] = field(default_factory=dict)        # invoice_number -> invoice_date
    po_order_dates: dict[str, datetime] = field(default_factory=dict)       # po_number -> order_date
    po_amounts: dict[str, float] = field(default_factory=dict)              # po_number -> total_amount

    # OTC/Cross-process anomaly tracking
    so_to_shipment_date: dict[str, datetime] = field(default_factory=dict)  # so_number -> shipment_date
    so_line_quantities: dict[str, float] = field(default_factory=dict)      # "SO_NUMBER-line_number" -> quantity
    ar_receipt_details: list[tuple] = field(default_factory=list)            # (receipt_vid, amount, date, customer_number)


class CSVWriter:
    """Handles CSV file writing with batching."""

    def __init__(self, output_dir: Path, batch_size: int = BATCH_SIZE):
        self.output_dir = output_dir
        self.batch_size = batch_size
        self.writers: dict[str, csv.writer] = {}
        self.files: dict[str, Path] = {}
        self.buffers: dict[str, list] = {}

    def _ensure_dir(self, subdir: str):
        """Ensure output subdirectory exists."""
        dir_path = self.output_dir / subdir
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path

    def write_vertex(self, tag: str, vid: str, properties: dict):
        """Write a vertex record."""
        self._write_record("vertices", tag, [vid, self._props_to_str(properties)])

    def write_edge(self, edge_type: str, src_vid: str, dst_vid: str, properties: dict, rank: int = 0):
        """Write an edge record."""
        # NebulaGraph edge format: src_vid,dst_vid,rank,properties
        self._write_record("edges", edge_type, [src_vid, dst_vid, str(rank), self._props_to_str(properties)])

    def _write_record(self, category: str, name: str, record: list):
        """Write a record to the appropriate CSV file."""
        key = f"{category}/{name}"
        if key not in self.buffers:
            dir_path = self._ensure_dir(category)
            file_path = dir_path / f"{name}.csv"
            self.files[key] = file_path
            self.buffers[key] = []
            # NebulaGraph importer requires: vid,properties (vertices) or src_vid,dst_vid,rank,properties (edges)
            mode = 'vertex' if category == 'vertices' else 'edge'
            self._init_file(file_path, mode)

        self.buffers[key].append(record)

        if len(self.buffers[key]) >= self.batch_size:
            self._flush(key)

    def _init_file(self, file_path: Path, mode: str):
        """Initialize a new CSV file with header."""
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if mode == 'vertex':
                # VID,properties format
                writer.writerow(["vid", "properties"])
            else:
                # src_vid,dst_vid,rank,properties format
                writer.writerow(["src_vid", "dst_vid", "rank", "properties"])

    def _props_to_str(self, props: dict) -> str:
        """Convert properties dict to JSON string."""
        import json
        # Convert all values to strings for CSV
        str_props = {}
        for k, v in props.items():
            if v is None:
                str_props[k] = ""
            elif isinstance(v, bool):
                str_props[k] = "true" if v else "false"
            elif isinstance(v, datetime):
                str_props[k] = format_timestamp(v)
            elif isinstance(v, list):
                str_props[k] = json.dumps(v)
            else:
                str_props[k] = str(v)
        return json.dumps(str_props, ensure_ascii=False)

    def _flush(self, key: str):
        """Flush buffer to file."""
        if key not in self.buffers or not self.buffers[key]:
            return

        with open(self.files[key], 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerows(self.buffers[key])

        self.buffers[key] = []

    def flush_all(self):
        """Flush all buffers to files."""
        for key in self.buffers:
            self._flush(key)

    def close(self):
        """Flush all and finalize."""
        self.flush_all()


class TestDataGenerator:
    """Main test data generator for HoneyBadge ERP simulation."""

    def __init__(self, output_dir: Path, seed: int = 42):
        self.output_dir = output_dir
        self.registry = DataRegistry()
        self.writer = CSVWriter(output_dir)
        random.seed(seed)
        self.etl_batch_id = f"TEST_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.source_system = "ORACLE_EBS_SIMULATION"

        # Counters for unique IDs
        self._po_line_counter = 0
        self._receipt_line_counter = 0
        self._invoice_line_counter = 0
        self._so_line_counter = 0
        self._shipment_line_counter = 0
        self._pr_line_counter = 0
        self._journal_line_counter = 0

    def close(self):
        """Close the writer and flush all buffers."""
        self.writer.close()

    def generate_all(self):
        """Generate all test data."""
        print("=" * 60)
        print("HoneyBadge Phase 1 Test Data Generator")
        print("=" * 60)
        print(f"Output directory: {self.output_dir}")
        print(f"ETL Batch ID: {self.etl_batch_id}")
        print()

        print("[1/24] Generating master data (Organizations, Employees, Warehouses)...")
        self._generate_organizations()
        self._generate_employees()
        self._generate_warehouses()
        self._generate_gl_accounts()
        self._generate_currencies()
        self._generate_uoms()

        print("[2/24] Generating Items and BOMs...")
        self._generate_items()
        self._generate_boms()

        print("[3/24] Generating Suppliers...")
        self._generate_suppliers()

        print("[3b/24] Generating Supplier Sites (v2.0)...")
        self._generate_supplier_sites()

        print("[4/24] Generating Customers...")
        self._generate_customers()

        print("[4b/24] Generating Customer Sites (v2.0)...")
        self._generate_customer_sites()

        print("[5/24] Generating Contracts...")
        self._generate_contracts()

        print("[5b/24] Generating Item Categories (v2.0)...")
        self._generate_item_categories()

        print("[6/24] Generating GL reference data (v2.0: Ledgers, Periods, CCIDs, Rates, Bank Accounts)...")
        self._generate_ledgers()
        self._generate_gl_periods()
        self._generate_gl_code_combinations()
        self._generate_currency_rates()
        self._generate_bank_accounts()

        print("[7/24] Generating Purchase Requisitions...")
        self._generate_purchase_requisitions()

        print("[8/24] Generating Purchase Orders...")
        self._generate_purchase_orders()

        print("[9/24] Generating Receipts...")
        self._generate_receipts()

        print("[10/24] Generating Invoices (with 5% three-way match failures)...")
        self._generate_invoices()

        print("[11/24] Generating Payments...")
        self._generate_payments()

        print("[12/24] Generating Payment Batches...")
        self._generate_payment_batches()

        print("[12b/24] Generating Expense Reports (v2.0)...")
        self._generate_expense_reports()

        print("[13/24] Generating Sales Orders...")
        self._generate_sales_orders()

        print("[14/24] Generating Shipments...")
        self._generate_shipments()

        print("[15/24] Generating AR Invoices...")
        self._generate_ar_invoices()

        print("[16/24] Generating AR Receipts...")
        self._generate_ar_receipts()

        print("[17/24] Generating GL Journal Batches (v2.0)...")
        self._generate_gl_journal_batches()

        print("[18/24] Generating GL Journal Entries...")
        self._generate_gl_journal_entries()

        print("[19/24] Generating XLA Events...")
        self._generate_xla_events()

        print("[20/24] Generating GL Balances (v2.0)...")
        self._generate_gl_balances()

        print("[21/24] Generating Inventory Transactions (v2.0)...")
        self._generate_inventory_transactions()

        print("[22/24] Generating Bank Statements (v2.0)...")
        self._generate_bank_statements()

        print("[23/24] Generating Approval Records...")
        self._generate_approval_records()

        print("[24/24] Injecting anomaly patterns...")
        print("  PTP patterns (1-6):")
        self._inject_circular_trading()
        self._inject_split_pos()
        self._inject_blocked_supplier_pos()
        self._inject_suspicious_bank_changes()
        self._inject_supplier_concentration()
        print("  OTC patterns (7-9):")
        self._inject_ghost_shipments()
        self._inject_credit_memo_fraud()
        print("  PTP+OTC cross-process patterns (10-12):")
        self._inject_round_tripping()
        self._inject_transfer_pricing()
        self._inject_ship_before_receipt()

        # Final flush
        self.writer.flush_all()

        print()
        print("=" * 60)
        print("Data Generation Summary")
        print("=" * 60)
        print(f"Suppliers:            {len(self.registry.suppliers)}")
        print(f"Supplier Sites:       {len(self.registry.supplier_sites)}")
        print(f"Customers:            {len(self.registry.customers)}")
        print(f"Customer Sites:       {len(self.registry.customer_sites)}")
        print(f"Items:                {len(self.registry.items)}")
        print(f"Item Categories:      {len(self.registry.item_categories)}")
        print(f"Organizations:        {len(self.registry.organizations)}")
        print(f"Employees:            {len(self.registry.employees)}")
        print(f"Warehouses:           {len(self.registry.warehouses)}")
        print(f"GL Accounts:          {len(self.registry.gl_accounts)}")
        print(f"GL Code Combos:       {len(self.registry.gl_code_combinations)}")
        print(f"Ledgers:              {len(self.registry.ledgers)}")
        print(f"GL Periods:           {len(self.registry.gl_periods)}")
        print(f"Currency Rates:       {len(self.registry.currency_rates)}")
        print(f"Bank Accounts:        {len(self.registry.bank_accounts)}")
        print(f"BOMs:                 {len(self.registry.boms)}")
        print(f"Contracts:            {len(self.registry.contracts)}")
        print(f"Purchase Reqs:        {len(self.registry.purchase_requisitions)}")
        print(f"Purchase Orders:      {len(self.registry.purchase_orders)}")
        print(f"Receipts:             {len(self.registry.receipts)}")
        print(f"Invoices:             {len(self.registry.invoices)}")
        print(f"Invoice Holds:        {len(self.registry.invoice_holds)}")
        print(f"Payments:             {len(self.registry.payments)}")
        print(f"Payment Batches:      {len(self.registry.payment_batches)}")
        print(f"Expense Reports:      {len(self.registry.expense_reports)}")
        print(f"Sales Orders:         {len(self.registry.sales_orders)}")
        print(f"Shipments:            {len(self.registry.shipments)}")
        print(f"AR Invoices:          {len(self.registry.ar_invoices)}")
        print(f"AR Receipts:          {len(self.registry.ar_receipts)}")
        print(f"GL Journal Batches:   {len(self.registry.gl_journal_batches)}")
        print(f"GL Entries:           {len(self.registry.gl_journal_entries)}")
        print(f"GL Balances:          {len(self.registry.gl_balances)}")
        print(f"XLA Events:           {len(self.registry.xla_events)}")
        print(f"Inventory Txns:       {len(self.registry.inventory_transactions)}")
        print(f"Bank Statements:      {len(self.registry.bank_statements)}")
        print(f"Bank Stmt Lines:      {len(self.registry.bank_statement_lines)}")
        print(f"Approval Records:     {len(self.registry.approvals)}")
        print()
        print(f"Total records written to: {self.output_dir}")
        print("=" * 60)

    def _generate_organizations(self):
        """Generate hierarchical organizations."""
        org_codes = []

        # Generate top-level organizations
        for i in range(NUM_ORGANIZATIONS):
            org_code = f"ORG{str(i+1).zfill(5)}"
            org_codes.append(org_code)

            # Determine parent (for hierarchy)
            if i == 0:
                parent_code = None
            elif i < 10:
                parent_code = org_codes[0]  # First org is root
            else:
                parent_code = org_codes[random.randint(1, min(i-1, 20))]

            city_info = random.choice(CITIES)
            props = {
                "org_code": org_code,
                "org_name": f"{city_info[0]}分部{str(i+1)}" if i >= 10 else f"{city_info[0]}总部",
                "org_type": "HEADQUARTER" if i < 5 else "OPERATING_UNIT",
                "parent_org_code": parent_code,
                "legal_entity": f"{city_info[0]}法 人有限公司",
                "country": "中国",
                "city": city_info[0],
                "status": "ACTIVE",
                "org_id": 1000 + i,
                "dept_id": 1000 + i,
                "data_scope": "FULL",
                "created_at": DATA_START_DATE,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            self.writer.write_vertex("Organization", vid(VID_PREFIX_ORG, org_code), props)
            self.registry.organizations.append(vid(VID_PREFIX_ORG, org_code))

            # Write PARENT_ORG edge
            if parent_code:
                self.writer.write_edge(
                    "PARENT_ORG",
                    vid(VID_PREFIX_ORG, org_code),
                    vid(VID_PREFIX_ORG, parent_code),
                    {"org_id": props["org_id"], "dept_id": props["dept_id"]}
                )

        self.registry.organizations = org_codes

    def _generate_employees(self):
        """Generate employees linked to organizations."""
        for i in range(NUM_EMPLOYEES):
            emp_number = f"EMP{str(i+1).zfill(6)}"
            org_code = random.choice(self.registry.organizations)
            dept = random.choice(DEPARTMENTS)
            position = random.choice(POSITIONS)

            hire_date = random_date(DATA_START_DATE - timedelta(days=365*5), DATA_START_DATE)

            props = {
                "employee_number": emp_number,
                "employee_name": random_person_name(),
                "position": position,
                "department": dept,
                "email": f"{emp_number.lower()}@honeybadge.com",
                "phone": random_phone(),
                "manager_id": self.registry.employees[random.randint(0, len(self.registry.employees)-1)].split(":")[1] if self.registry.employees and i > 0 else None,
                "hire_date": hire_date,
                "status": "ACTIVE",
                "org_id": 1000 + int(org_code.split("ORG")[1]),
                "dept_id": random.randint(1000, 1119),
                "data_scope": "FULL",
                "created_at": hire_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            emp_vid = vid(VID_PREFIX_EMPLOYEE, emp_number)
            self.writer.write_vertex("Employee", emp_vid, props)
            self.registry.employees.append(emp_vid)

            # Write BELONGS_TO_ORG edge
            self.writer.write_edge(
                "BELONGS_TO_ORG",
                emp_vid,
                vid(VID_PREFIX_ORG, org_code),
                {"org_id": props["org_id"], "dept_id": props["dept_id"]}
            )

    def _generate_warehouses(self):
        """Generate warehouses."""
        for i in range(NUM_WAREHOUSES):
            wh_code = f"WH{str(i+1).zfill(3)}"
            city_info = random.choice(CITIES)

            props = {
                "warehouse_code": wh_code,
                "warehouse_name": f"{city_info[0]}{random.choice(WAREHOUSE_TYPES)}",
                "warehouse_type": random.choice(WAREHOUSE_TYPES),
                "location": f"{city_info[0]}{city_info[1]}区",
                "capacity": random.randint(1000, 50000),
                "status": "ACTIVE",
                "org_id": 1000 + random.randint(0, NUM_ORGANIZATIONS-1),
                "dept_id": 1000 + random.randint(0, 119),
                "data_scope": "FULL",
                "created_at": DATA_START_DATE,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            wh_vid = vid(VID_PREFIX_WAREHOUSE, wh_code)
            self.writer.write_vertex("Warehouse", wh_vid, props)
            self.registry.warehouses.append(wh_vid)

    def _generate_gl_accounts(self):
        """Generate GL accounts."""
        account_types = ["ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"]
        for i in range(NUM_GL_ACCOUNTS):
            acct_code = f"{random.choice(['1','2','3','4','5'])}{str(i+1).zfill(6)}"
            acct_type = account_types[int(acct_code[0]) - 1]

            props = {
                "account_code": acct_code,
                "account_name": f"科目{acct_code}",
                "account_type": acct_type,
                "parent_account": acct_code[1:] if len(acct_code) > 2 else None,
                "level": len(acct_code) - 1,
                "is_leaf": random.random() > 0.2,
                "currency": "CNY",
                "status": "ACTIVE",
                "org_id": 1000,
                "dept_id": 1000,
                "data_scope": "FULL",
                "created_at": DATA_START_DATE,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            acct_vid = vid(VID_PREFIX_GL_ACCOUNT, acct_code)
            self.writer.write_vertex("GLAccount", acct_vid, props)
            self.registry.gl_accounts.append(acct_vid)

            # v2.0: PARENT_ACCOUNT edge (for non-root accounts)
            if i > 4 and len(self.registry.gl_accounts) > 5:
                parent_idx = i % 5  # First 5 are parent accounts
                parent_vid = self.registry.gl_accounts[parent_idx]
                self.writer.write_edge(
                    "PARENT_ACCOUNT",
                    acct_vid,
                    parent_vid,
                    {"org_id": 1000, "dept_id": 1000}
                )

    def _generate_currencies(self):
        """Generate currencies."""
        currencies = [
            ("CNY", "人民币", "¥", 2, True),
            ("USD", "美元", "$", 2, False),
            ("EUR", "欧元", "€", 2, False),
            ("GBP", "英镑", "£", 2, False),
            ("JPY", "日元", "¥", 0, False),
            ("HKD", "港币", "HK$", 2, False),
            ("SGD", "新加坡元", "S$", 2, False),
            ("KRW", "韩元", "₩", 0, False),
            ("AUD", "澳元", "A$", 2, False),
            ("CAD", "加元", "C$", 2, False),
            ("CHF", "瑞士法郎", "CHF", 2, False),
            ("CNY_USD", "美元离岸", "¥", 2, False),
            ("RMB_HKD", "人民币港币", "HK$", 2, False),
            ("CNY_EUR", "欧元跨境", "€", 2, False),
            ("CNY_JPY", "日元跨境", "¥", 2, False),
        ]

        for code, name, symbol, decimals, is_base in currencies[:NUM_CURRENCIES]:
            props = {
                "currency_code": code,
                "currency_name": name,
                "symbol": symbol,
                "decimal_places": decimals,
                "is_base_currency": is_base,
                "org_id": 1000,
                "dept_id": 1000,
                "data_scope": "FULL",
                "created_at": DATA_START_DATE,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            cur_vid = vid(VID_PREFIX_CURRENCY, code)
            self.writer.write_vertex("Currency", cur_vid, props)
            self.registry.currencies.append(cur_vid)

    def _generate_uoms(self):
        """Generate UOMs."""
        uom_data = [
            ("EA", "个", "数量", None, 1.0),
            ("PCS", "件", "数量", "EA", 1.0),
            ("KG", "千克", "重量", None, 1.0),
            ("G", "克", "重量", "KG", 0.001),
            ("LB", "磅", "重量", "KG", 0.453592),
            ("TON", "吨", "重量", "KG", 1000.0),
            ("M", "米", "长度", None, 1.0),
            ("CM", "厘米", "长度", "M", 0.01),
            ("MM", "毫米", "长度", "M", 0.001),
            ("FT", "英尺", "长度", "M", 0.3048),
            ("IN", "英寸", "长度", "M", 0.0254),
            ("SQM", "平方米", "面积", None, 1.0),
            ("SQFT", "平方英尺", "面积", "SQM", 0.0929),
            ("CBM", "立方米", "体积", None, 1.0),
            ("CBFT", "立方英尺", "体积", "CBM", 0.0283),
            ("L", "升", "体积", None, 1.0),
            ("ML", "毫升", "体积", "L", 0.001),
            ("GAL", "加仑", "体积", "L", 3.78541),
            ("BOX", "盒", "包装", "EA", 100.0),
            ("CTN", "箱", "包装", "EA", 50.0),
            ("PAL", "托盘", "包装", "EA", 200.0),
            ("SET", "套", "数量", "EA", 1.0),
            ("KIT", "kit", "数量", "EA", 1.0),
            ("ROLL", "卷", "包装", "EA", 100.0),
            ("DRUM", "桶", "包装", "EA", 200.0),
            ("BAG", "袋", "包装", "EA", 50.0),
            ("HR", "小时", "时间", None, 1.0),
            ("DAY", "天", "时间", "HR", 24.0),
            ("WK", "周", "时间", "DAY", 7.0),
            ("MON", "月", "时间", "DAY", 30.0),
        ]

        for code, name, uom_class, base, rate in uom_data[:NUM_UOMS]:
            props = {
                "uom_code": code,
                "uom_name": name,
                "uom_class": uom_class,
                "base_uom": base,
                "conversion_rate": rate,
                "org_id": 1000,
                "dept_id": 1000,
                "data_scope": "FULL",
                "created_at": DATA_START_DATE,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            uom_vid = vid(VID_PREFIX_UOM, code)
            self.writer.write_vertex("UOM", uom_vid, props)
            self.registry.uoms.append(uom_vid)

    def _generate_suppliers(self):
        """Generate suppliers with qualifications."""
        for i in range(NUM_SUPPLIERS):
            sup_number = f"SUP{str(i+1).zfill(5)}"
            city_info = random.choice(CITIES)
            # Pattern 3: Force specific suppliers to BLOCKED status
            if sup_number in BLOCKED_SUPPLIER_NUMBERS:
                status = "BLOCKED"
            else:
                status = random.choice(["ACTIVE", "ACTIVE", "ACTIVE", "ACTIVE", "INACTIVE", "SUSPENDED"])
            has_expired_qual = random.random() < EXPIRED_QUALIFICATION_RATE

            reg_date = random_date(DATA_START_DATE - timedelta(days=365*10), DATA_START_DATE - timedelta(days=30))
            qual_expiry = random_date(DATA_END_DATE, DATA_END_DATE + timedelta(days=365)) if not has_expired_qual else random_date(DATA_START_DATE - timedelta(days=180), DATA_START_DATE)

            props = {
                "supplier_number": sup_number,
                "supplier_name": random_company_name(),
                "supplier_type": random.choice(["MANUFACTURER", "DISTRIBUTOR", "TRADER", "SERVICE"]),
                "status": status,
                "country": "中国",
                "city": city_info[0],
                "address": f"{city_info[0]}{city_info[1]}区{random.randint(1, 999)}号",
                "contact_person": random_person_name(),
                "contact_phone": random_phone(),
                "contact_email": f"contact@{sup_number.lower()}.com",
                "bank_account": generate_bank_account(),
                "bank_name": random.choice(["中国工商银行", "中国建设银行", "中国农业银行", "中国银行", "招商银行"]),
                "tax_id": generate_tax_id(),
                "currency": random.choice(["CNY", "CNY", "CNY", "USD", "EUR"]),
                "payment_terms": random.choice(["NET30", "NET45", "NET60", "NET90", "COD"]),
                "credit_rating": random.choice(["AAA", "AA", "A", "BBB", "BB", "B"]),
                "registration_date": reg_date,
                "qualification_expiry": qual_expiry,
                "org_id": 1000 + random.randint(0, NUM_ORGANIZATIONS-1),
                "dept_id": 1000 + random.randint(0, 119),
                "data_scope": "FULL",
                "created_at": reg_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": status == "ACTIVE",
            }

            sup_vid = vid(VID_PREFIX_SUPPLIER, sup_number)
            self.writer.write_vertex("Supplier", sup_vid, props)
            self.registry.suppliers.append(sup_vid)

            # Generate supplier qualifications
            self._generate_supplier_qualification(sup_vid, sup_number, reg_date)

            # Generate approved supplier list (ASL) - link some items to this supplier
            if random.random() > 0.3:  # 70% of suppliers have ASL entries
                num_items = random.randint(10, 100)
                for _ in range(num_items):
                    item = random.choice(self.registry.items)
                    item_number = item.split(":")[1]
                    self.writer.write_edge(
                        "SUPPLIES_ITEM",
                        sup_vid,
                        item,
                        {
                            "priority": random.randint(1, 3),
                            "unit_price": round(random.uniform(10, 10000), 2),
                            "lead_time_days": random.randint(1, 90),
                            "status": "ACTIVE",
                            "effective_from": reg_date,
                            "effective_to": None,
                            "org_id": props["org_id"],
                            "dept_id": props["dept_id"],
                        }
                    )

    def _generate_supplier_qualification(self, sup_vid: str, sup_number: str, issue_date: datetime):
        """Generate qualifications for a supplier."""
        qual_types = ["ISO9001", "ISO14001", "ISO45001", "IATF16949", "CE", "UL", "RoHS", "REACH"]
        for qual_type in random.sample(qual_types, random.randint(2, 5)):
            qual_id = f"SQ{self.etl_batch_id[-6:]}{sup_number[3:]}{qual_type[:3]}"
            issue = issue_date + timedelta(days=random.randint(0, 365))
            expiry = issue + timedelta(days=random.randint(365, 1095))

            props = {
                "qualification_id": qual_id,
                "qualification_type": qual_type,
                "status": "VALID" if expiry > datetime.now() else "EXPIRED",
                "issue_date": issue,
                "expiry_date": expiry,
                "issuing_body": random.choice(["TUV", "SGS", "BV", "DNV", "LR", "ABS"]),
                "scope": "供应商质量管理",
                "org_id": 1000 + random.randint(0, NUM_ORGANIZATIONS-1),
                "dept_id": 1000 + random.randint(0, 119),
                "data_scope": "FULL",
                "created_at": issue,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            qual_vid = vid(VID_PREFIX_QUALIFICATION, qual_id)
            self.writer.write_vertex("SupplierQualification", qual_vid, props)

            self.writer.write_edge(
                "HAS_QUALIFICATION",
                sup_vid,
                qual_vid,
                {"org_id": props["org_id"], "dept_id": props["dept_id"]}
            )

    def _generate_customers(self):
        """Generate customers."""
        for i in range(NUM_CUSTOMERS):
            cus_number = f"CUS{str(i+1).zfill(5)}"
            city_info = random.choice(CITIES)
            status = random.choice(["ACTIVE", "ACTIVE", "ACTIVE", "INACTIVE"])

            props = {
                "customer_number": cus_number,
                "customer_name": random_company_name(),
                "customer_type": random.choice(["CORPORATE", "GOVERNMENT", "INDIVIDUAL", "INTERCOMPANY"]),
                "status": status,
                "country": "中国",
                "city": city_info[0],
                "address": f"{city_info[0]}{city_info[1]}区{random.randint(1, 999)}号",
                "contact_person": random_person_name(),
                "contact_phone": random_phone(),
                "contact_email": f"contact@{cus_number.lower()}.com",
                "credit_limit": random.randint(100000, 10000000),
                "payment_terms": random.choice(["NET30", "NET45", "NET60", "NET90", "COD", "PREPAID"]),
                "tax_id": generate_tax_id(),
                "currency": random.choice(["CNY", "CNY", "CNY", "USD", "EUR"]),
                "sales_region": random.choice(["华北", "华东", "华南", "华中", "西南", "西北", "东北"]),
                "org_id": 1000 + random.randint(0, NUM_ORGANIZATIONS-1),
                "dept_id": 1000 + random.randint(0, 119),
                "data_scope": "FULL",
                "created_at": random_date(DATA_START_DATE, DATA_END_DATE),
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": status == "ACTIVE",
            }

            cus_vid = vid(VID_PREFIX_CUSTOMER, cus_number)
            self.writer.write_vertex("Customer", cus_vid, props)
            self.registry.customers.append(cus_vid)

    def _generate_items(self):
        """Generate items with categories."""
        for i in range(NUM_ITEMS):
            item_number = f"ITM{str(i+1).zfill(6)}"
            category = random.choice(ITEM_CATEGORIES)
            item_type = random.choice(ITEM_TYPES)

            props = {
                "item_number": item_number,
                "item_name": random_item_name(category),
                "item_description": f"{category} - {item_type}",
                "item_type": item_type,
                "category": category,
                "uom": random.choice(["EA", "KG", "M", "L", "BOX", "ROLL"]),
                "standard_cost": round(random.uniform(10, 50000), 2),
                "list_price": round(random.uniform(20, 60000), 2),
                "weight": round(random.uniform(0.1, 1000), 2),
                "weight_uom": random.choice(["KG", "G", "LB"]),
                "lead_time_days": random.randint(1, 90),
                "safety_stock": round(random.uniform(10, 1000), 2),
                "min_order_qty": round(random.uniform(1, 100), 2),
                "status": "ACTIVE",
                "abc_class": random.choice(["A", "A", "B", "B", "B", "C"]),
                "org_id": 1000 + random.randint(0, NUM_ORGANIZATIONS-1),
                "dept_id": 1000 + random.randint(0, 119),
                "data_scope": "FULL",
                "created_at": random_date(DATA_START_DATE, DATA_END_DATE),
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            item_vid = vid(VID_PREFIX_ITEM, item_number)
            self.writer.write_vertex("Item", item_vid, props)
            self.registry.items.append(item_vid)

    def _generate_boms(self):
        """Generate BOMs with components."""
        finished_goods = [it for it in self.registry.items if it.split(":")[1].startswith("ITM")]

        for i in range(NUM_BOMS):
            bom_number = f"BOM{str(i+1).zfill(6)}"
            parent_item = random.choice(finished_goods) if finished_goods else random.choice(self.registry.items)

            effective_from = random_date(DATA_START_DATE, DATA_END_DATE - timedelta(days=180))
            effective_to = effective_from + timedelta(days=random.randint(180, 1095))

            props = {
                "bom_number": bom_number,
                "bom_name": f"BOM-{bom_number}",
                "bom_type": "MANUFACTURING",
                "effective_from": effective_from,
                "effective_to": effective_to,
                "quantity": 1.0,
                "uom": "EA",
                "status": "ACTIVE",
                "org_id": 1000 + random.randint(0, NUM_ORGANIZATIONS-1),
                "dept_id": 1000 + random.randint(0, 119),
                "data_scope": "FULL",
                "created_at": effective_from,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            bom_vid = vid(VID_PREFIX_BOM, bom_number)
            self.writer.write_vertex("BOM", bom_vid, props)
            self.registry.boms.append(bom_vid)

            # Write BOM_FOR edge (BOM -> Item)
            self.writer.write_edge(
                "BOM_FOR",
                bom_vid,
                parent_item,
                {"org_id": props["org_id"], "dept_id": props["dept_id"]}
            )

            # Generate BOM components
            num_components = random.randint(2, 10)
            for j in range(num_components):
                comp_seq = j + 1
                component_item = random.choice(self.registry.items)
                qty_per = round(random.uniform(0.1, 50), 4)

                comp_props = {
                    "component_seq": comp_seq,
                    "quantity_per": qty_per,
                    "uom": random.choice(["EA", "KG", "M", "L"]),
                    "effective_from": effective_from,
                    "effective_to": effective_to,
                    "yield_rate": round(random.uniform(0.9, 1.0), 4),
                    "wip_supply_type": random.choice(["PULL", "PUSH", "Phantom", "BETWEEN"]),
                    "org_id": props["org_id"],
                    "dept_id": props["dept_id"],
                    "data_scope": "FULL",
                    "created_at": effective_from,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }

                comp_vid = vid(VID_PREFIX_BOM_COMP, f"{bom_number}-{comp_seq:03d}")
                self.writer.write_vertex("BOMComponent", comp_vid, comp_props)

                # Write USES_COMPONENT edge (Component -> Item)
                self.writer.write_edge(
                    "USES_COMPONENT",
                    comp_vid,
                    component_item,
                    {"quantity_per": qty_per, "org_id": props["org_id"], "dept_id": props["dept_id"]}
                )

    def _generate_contracts(self):
        """Generate contracts."""
        for i in range(NUM_CONTRACTS):
            contract_number = f"CNT{str(i+1).zfill(6)}"
            start_date = random_date(DATA_START_DATE, DATA_END_DATE - timedelta(days=180))
            end_date = start_date + timedelta(days=random.randint(180, 1095))

            # Contract with supplier or customer
            is_supplier = random.random() > 0.3
            party_vid = random.choice(self.registry.suppliers) if is_supplier else random.choice(self.registry.customers)

            props = {
                "contract_number": contract_number,
                "contract_type": random.choice(["框架协议", "采购合同", "销售合同", "服务合同"]),
                "contract_name": f"合同-{contract_number}",
                "status": "ACTIVE" if end_date > datetime.now() else "EXPIRED",
                "start_date": start_date,
                "end_date": end_date,
                "total_amount": round(random.uniform(100000, 10000000), 2),
                "currency": random.choice(["CNY", "USD", "EUR"]),
                "description": f"合同编号: {contract_number}",
                "org_id": 1000 + random.randint(0, NUM_ORGANIZATIONS-1),
                "dept_id": 1000 + random.randint(0, 119),
                "data_scope": "FULL",
                "created_at": start_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            contract_vid = vid(VID_PREFIX_CONTRACT, contract_number)
            self.writer.write_vertex("Contract", contract_vid, props)
            self.registry.contracts.append(contract_vid)

            # Write CONTRACT_WITH edge
            self.writer.write_edge(
                "CONTRACT_WITH",
                contract_vid,
                party_vid,
                {"party_type": "SUPPLIER" if is_supplier else "CUSTOMER", "org_id": props["org_id"], "dept_id": props["dept_id"]}
            )

    def _generate_purchase_requisitions(self):
        """Generate purchase requisitions."""
        for i in range(NUM_PURCHASE_REQUISITIONS):
            pr_number = f"PR{str(i+1).zfill(8)}"
            request_date = random_date(DATA_START_DATE, DATA_END_DATE - timedelta(days=30))
            need_by_date = request_date + timedelta(days=random.randint(7, 90))

            requester = random.choice(self.registry.employees)
            requester_number = requester.split(":")[1]

            # Generate PR lines
            num_lines = random.randint(1, 5)
            total_amount = 0
            pr_lines = []

            for j in range(num_lines):
                line_number = j + 1
                quantity = round(random.uniform(10, 1000), 2)
                unit_price = round(random.uniform(10, 5000), 2)
                amount = quantity * unit_price
                total_amount += amount

                line_props = {
                    "line_number": line_number,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "amount": amount,
                    "uom": random.choice(["EA", "KG", "M", "L", "BOX"]),
                    "need_by_date": need_by_date,
                    "suggested_vendor": random.choice(self.registry.suppliers).split(":")[1] if random.random() > 0.3 else None,
                    "status": "APPROVED",
                    "org_id": 1000 + random.randint(0, NUM_ORGANIZATIONS-1),
                    "dept_id": 1000 + random.randint(0, 119),
                    "data_scope": "FULL",
                    "created_at": request_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }

                line_vid = vid(VID_PREFIX_PR_LINE, f"{pr_number}-{line_number}")
                self.writer.write_vertex("PurchaseRequisitionLine", line_vid, line_props)
                pr_lines.append(line_vid)

            props = {
                "pr_number": pr_number,
                "pr_type": random.choice(["PURCHASE", "SERVICES", "EXPENSE"]),
                "description": f"采购申请 {pr_number}",
                "status": "APPROVED",
                "requester": requester_number,
                "request_date": request_date,
                "need_by_date": need_by_date,
                "total_amount": round(total_amount, 2),
                "currency": "CNY",
                "approval_date": request_date + timedelta(days=random.randint(1, 7)),
                "approver": random.choice(self.registry.employees).split(":")[1],
                "org_id": 1000 + random.randint(0, NUM_ORGANIZATIONS-1),
                "dept_id": 1000 + random.randint(0, 119),
                "data_scope": "FULL",
                "created_at": request_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            pr_vid = vid(VID_PREFIX_PR, pr_number)
            self.writer.write_vertex("PurchaseRequisition", pr_vid, props)
            self.registry.purchase_requisitions.append(pr_vid)

            # Write HAS_PR_LINE edges
            for line_vid in pr_lines:
                self.writer.write_edge(
                    "HAS_PR_LINE",
                    pr_vid,
                    line_vid,
                    {"org_id": props["org_id"], "dept_id": props["dept_id"]}
                )

    def _generate_purchase_orders(self):
        """Generate purchase orders with lines."""
        for i in range(NUM_PURCHASE_ORDERS):
            po_number = f"PO{str(i+1).zfill(8)}"
            order_date = random_date(DATA_START_DATE, DATA_END_DATE - timedelta(days=7))
            approved_date = order_date + timedelta(hours=random.randint(1, 48))

            supplier = random.choice(self.registry.suppliers)
            supplier_number = supplier.split(":")[1]
            buyer = random.choice(self.registry.employees)
            buyer_number = buyer.split(":")[1]
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS-1)
            dept_id = 1000 + random.randint(0, 119)

            # Generate PO lines
            num_lines = random.randint(1, 8)
            total_amount = 0
            po_lines = []
            line_items_data = []

            for j in range(num_lines):
                self._po_line_counter += 1
                line_number = j + 1
                quantity = round(random.uniform(10, 5000), 2)
                unit_price = round(random.uniform(10, 10000), 2)
                amount = quantity * unit_price
                total_amount += amount
                tax_rate = random.choice([0, 0.06, 0.09, 0.13])

                line_props = {
                    "line_number": line_number,
                    "line_type": random.choice(["GOODS", "SERVICES"]),
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "amount": round(amount * (1 + tax_rate), 2),
                    "uom": random.choice(["EA", "KG", "M", "L", "BOX", "TON"]),
                    "need_by_date": order_date + timedelta(days=random.randint(30, 180)),
                    "promised_date": order_date + timedelta(days=random.randint(14, 90)),
                    "received_quantity": 0,
                    "invoiced_quantity": 0,
                    "status": "OPEN",
                    "tax_code": f"TAX{str(int(tax_rate * 100)).zfill(2)}",
                    "tax_rate": tax_rate,
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": order_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }

                line_vid = vid(VID_PREFIX_PO_LINE, f"{po_number}-{line_number}")
                self.writer.write_vertex("PurchaseOrderLine", line_vid, line_props)
                po_lines.append(line_vid)

                # Track for three-way matching
                po_line_key = f"{po_number}-{line_number}"
                self.registry.invoice_amount_by_po_line[po_line_key] = line_props["amount"]

                # Pick an item
                item_vid = random.choice(self.registry.items)
                line_items_data.append((line_vid, item_vid, quantity, unit_price))

                # v2.0: Generate POShipment (PO_LINE_LOCATIONS_ALL) for each PO line
                shipment_num = 1
                ship_qty = quantity
                ship_to = random.choice(self.registry.warehouses).split(":")[1] if self.registry.warehouses else "WH00001"

                posh_props = {
                    "shipment_number": shipment_num,
                    "shipment_type": "STANDARD",
                    "quantity": ship_qty,
                    "quantity_received": 0,
                    "quantity_billed": 0,
                    "quantity_cancelled": 0,
                    "need_by_date": line_props["need_by_date"],
                    "promised_date": line_props["promised_date"],
                    "ship_to_location": ship_to,
                    "receiving_routing": random.choice(["STANDARD", "DIRECT", "INSPECT"]),
                    "match_option": random.choice(["R", "P"]),  # R=receipt match, P=PO match
                    "price_override": None,
                    "amount": line_props["amount"],
                    "status": "OPEN",
                    "accrue_on_receipt_flag": random.choice(["Y", "Y", "N"]),
                    "inspection_required_flag": random.choice(["N", "N", "Y"]),
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": order_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }

                posh_vid = vid(VID_PREFIX_PO_SHIPMENT, f"{po_number}-{line_number}-{shipment_num}")
                self.writer.write_vertex("POShipment", posh_vid, posh_props)
                self.registry.po_shipments.append(posh_vid)
                self.registry.po_line_to_shipments.setdefault(po_line_key, []).append(posh_vid)

                # HAS_PO_SHIPMENT edge
                self.writer.write_edge(
                    "HAS_PO_SHIPMENT",
                    line_vid,
                    posh_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

            props = {
                "po_number": po_number,
                "po_type": random.choice(["STANDARD", "BLANKET", "CONTRACT"]),
                "description": f"采购订单 {po_number}",
                "status": "APPROVED",
                "buyer": buyer_number,
                "order_date": order_date,
                "approved_date": approved_date,
                "total_amount": round(total_amount, 2),
                "currency": random.choice(["CNY", "USD", "EUR"]),
                "exchange_rate": 1.0 if random.random() > 0.1 else round(random.uniform(0.8, 1.2), 4),
                "payment_terms": random.choice(["NET30", "NET45", "NET60", "NET90", "COD"]),
                "freight_terms": random.choice(["FOB", "CIF", "EXW", "DDP"]),
                "ship_to_location": random.choice(self.registry.warehouses).split(":")[1],
                "bill_to_location": f"ORG{str(org_id % 1000 + 1).zfill(5)}",
                "close_date": None,
                "cancel_reason": None,
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": order_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            po_vid = vid(VID_PREFIX_PO, po_number)
            self.writer.write_vertex("PurchaseOrder", po_vid, props)
            self.registry.purchase_orders.append(po_vid)

            # Track PO -> supplier and buyer mapping
            self.registry.po_to_supplier[po_number] = supplier_number
            self.registry.po_to_employee[po_number] = buyer_number
            self.registry.po_order_dates[po_number] = order_date
            self.registry.po_amounts[po_number] = round(total_amount, 2)

            # Write edges
            self.writer.write_edge(
                "PLACED_WITH",
                po_vid,
                supplier,
                {"order_date": order_date, "org_id": org_id, "dept_id": dept_id}
            )

            self.writer.write_edge(
                "ORDERED_BY",
                po_vid,
                buyer,
                {"org_id": org_id, "dept_id": dept_id}
            )

            for line_vid, item_vid, qty, price in line_items_data:
                self.writer.write_edge(
                    "HAS_PO_LINE",
                    po_vid,
                    line_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

                self.writer.write_edge(
                    "ORDERS_ITEM",
                    line_vid,
                    item_vid,
                    {"quantity": qty, "unit_price": price, "org_id": org_id, "dept_id": dept_id}
                )

            # v2.0: SHIP_TO_SITE edge (PO -> SupplierSite)
            supplier_sites = self.registry.supplier_to_sites.get(supplier_number, [])
            if supplier_sites:
                site_vid = random.choice(supplier_sites)
                self.writer.write_edge(
                    "SHIP_TO_SITE",
                    po_vid,
                    site_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

            # Some POs convert from PRs
            if random.random() > 0.7 and self.registry.purchase_requisitions:
                pr_vid = random.choice(self.registry.purchase_requisitions)
                pr_number = pr_vid.split(":")[1]
                self.writer.write_edge(
                    "CONVERTS_TO_PO",
                    pr_vid,
                    po_vid,
                    {"conversion_date": order_date, "org_id": org_id, "dept_id": dept_id}
                )

    def _generate_receipts(self):
        """Generate receipts linked to POs."""
        for i in range(NUM_RECEIPTS):
            receipt_number = f"RCV{str(i+1).zfill(8)}"
            receipt_date = random_date(DATA_START_DATE + timedelta(days=30), DATA_END_DATE)

            # Link to a random PO
            po_number = random.choice(self.registry.purchase_orders).split(":")[1]
            po_vid = vid(VID_PREFIX_PO, po_number)
            warehouse = random.choice(self.registry.warehouses)
            warehouse_code = warehouse.split(":")[1]
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS-1)
            dept_id = 1000 + random.randint(0, 119)

            # Generate receipt lines
            num_lines = random.randint(1, 5)
            total_quantity = 0
            receipt_lines = []

            for j in range(num_lines):
                self._receipt_line_counter += 1
                line_number = j + 1
                received_qty = round(random.uniform(50, 2000), 2)
                accepted_qty = received_qty * random.uniform(0.95, 1.0)
                rejected_qty = received_qty - accepted_qty
                total_quantity += received_qty

                line_props = {
                    "line_number": line_number,
                    "received_quantity": received_qty,
                    "accepted_quantity": round(accepted_qty, 2),
                    "rejected_quantity": round(rejected_qty, 2),
                    "uom": random.choice(["EA", "KG", "M", "L", "BOX"]),
                    "inspection_status": random.choice(["PASSED", "PASSED", "PASSED", "FAILED"]),
                    "lot_number": f"LOT{receipt_date.strftime('%Y%m%d')}{random.randint(1000, 9999)}",
                    "sublocation": f"SL{random.randint(1, 50):02d}",
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": receipt_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }

                line_vid = vid(VID_PREFIX_RECEIPT_LINE, f"{receipt_number}-{line_number}")
                self.writer.write_vertex("ReceiptLine", line_vid, line_props)
                receipt_lines.append(line_vid)

                # Track for three-way matching
                po_line_key = f"{po_number}-{line_number}"
                self.registry.receipt_amount_by_po_line[po_line_key] = received_qty

                # v2.0: Generate ReceivingTransaction (RECEIVE) for each receipt line
                rcv_txn_id = f"RCVT-{receipt_number}-{line_number}"
                rcv_txn_props = {
                    "transaction_id": rcv_txn_id,
                    "transaction_type": "RECEIVE",
                    "transaction_date": receipt_date,
                    "quantity": received_qty,
                    "uom": line_props["uom"],
                    "parent_transaction_id": "",
                    "source_doc_type": "PO",
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": receipt_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }
                rcv_txn_vid = vid(VID_PREFIX_RCV_TXN, rcv_txn_id)
                self.writer.write_vertex("ReceivingTransaction", rcv_txn_vid, rcv_txn_props)
                self.registry.receiving_transactions.append(rcv_txn_vid)

                # HAS_RCV_TRANSACTION edge
                self.writer.write_edge(
                    "HAS_RCV_TRANSACTION",
                    line_vid,
                    rcv_txn_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

                # RECEIVES_SHIPMENT edge (link to POShipment)
                po_shipments = self.registry.po_line_to_shipments.get(po_line_key, [])
                if po_shipments:
                    posh_vid = random.choice(po_shipments)
                    self.writer.write_edge(
                        "RECEIVES_SHIPMENT",
                        rcv_txn_vid,
                        posh_vid,
                        {"org_id": org_id, "dept_id": dept_id}
                    )

                # DELIVER transaction (child of RECEIVE)
                if random.random() > 0.2:
                    deliver_txn_id = f"RCVT-{receipt_number}-{line_number}-D"
                    deliver_props = {
                        "transaction_id": deliver_txn_id,
                        "transaction_type": "DELIVER",
                        "transaction_date": receipt_date + timedelta(hours=random.randint(1, 24)),
                        "quantity": round(accepted_qty, 2),
                        "uom": line_props["uom"],
                        "parent_transaction_id": rcv_txn_id,
                        "source_doc_type": "PO",
                        "org_id": org_id,
                        "dept_id": dept_id,
                        "data_scope": "FULL",
                        "created_at": receipt_date,
                        "updated_at": datetime.now(),
                        "etl_batch_id": self.etl_batch_id,
                        "source_system": self.source_system,
                        "is_active": True,
                    }
                    deliver_vid = vid(VID_PREFIX_RCV_TXN, deliver_txn_id)
                    self.writer.write_vertex("ReceivingTransaction", deliver_vid, deliver_props)
                    self.registry.receiving_transactions.append(deliver_vid)

                    # RCV_PARENT edge
                    self.writer.write_edge(
                        "RCV_PARENT",
                        deliver_vid,
                        rcv_txn_vid,
                        {"org_id": org_id, "dept_id": dept_id}
                    )

            props = {
                "receipt_number": receipt_number,
                "receipt_type": random.choice(["PO_RECEIPT", "RETURN", "MISC"]),
                "receipt_date": receipt_date,
                "status": "COMPLETED",
                "receiver": random.choice(self.registry.employees).split(":")[1],
                "total_quantity": round(total_quantity, 2),
                "warehouse": warehouse_code,
                "comments": "",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": receipt_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            receipt_vid = vid(VID_PREFIX_RECEIPT, receipt_number)
            self.writer.write_vertex("Receipt", receipt_vid, props)
            self.registry.receipts.append(receipt_vid)

            # Track receipt -> PO mapping
            self.registry.receipt_to_po[receipt_number] = po_number
            # Track receipt date for temporal violation detection (Pattern 4)
            self.registry.po_to_receipt_date[po_number] = receipt_date

            # Write edges
            self.writer.write_edge(
                "HAS_RECEIPT",
                po_vid,
                receipt_vid,
                {"org_id": org_id, "dept_id": dept_id}
            )

            self.writer.write_edge(
                "HAS_RECEIPT_LINE",
                receipt_vid,
                line_vid,
                {"org_id": org_id, "dept_id": dept_id}
            )

            self.writer.write_edge(
                "RECEIVED_AT",
                receipt_vid,
                warehouse,
                {"org_id": org_id, "dept_id": dept_id}
            )

    def _generate_invoices(self):
        """Generate invoices with intentional three-way match failures."""
        for i in range(NUM_INVOICES):
            invoice_number = f"INV{str(i+1).zfill(8)}"
            invoice_date = random_date(DATA_START_DATE + timedelta(days=45), DATA_END_DATE)
            due_date = invoice_date + timedelta(days=random.randint(30, 90))
            is_temporal_violation = False

            # Link to a PO
            po_number = random.choice(self.registry.purchase_orders).split(":")[1]
            po_vid = vid(VID_PREFIX_PO, po_number)
            supplier = vid(VID_PREFIX_SUPPLIER, self.registry.po_to_supplier[po_number])
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS-1)
            dept_id = 1000 + random.randint(0, 119)

            # Pattern 4: Temporal violation — invoice date before receipt date (3%)
            if random.random() < TEMPORAL_VIOLATION_RATE:
                receipt_date_for_po = self.registry.po_to_receipt_date.get(po_number)
                if receipt_date_for_po:
                    invoice_date = receipt_date_for_po - timedelta(days=random.randint(5, 30))
                    due_date = invoice_date + timedelta(days=random.randint(30, 90))
                    is_temporal_violation = True

            # Determine if this invoice has a three-way match failure (5% rate)
            is_mismatch = random.random() < THREE_WAY_MATCH_FAILURE_RATE

            # Check for duplicate invoice (1% rate)
            is_duplicate = random.random() < DUPLICATE_INVOICE_RATE
            if is_duplicate and i > 100:
                # Reference a previous invoice's number
                prev_invoice_idx = random.randint(max(0, i - 100), i - 1)
                invoice_number = self.registry.invoices[prev_invoice_idx].split(":")[1] if self.registry.invoices else invoice_number

            # Generate invoice lines
            num_lines = random.randint(1, 5)
            total_amount = 0
            invoice_lines = []

            for j in range(num_lines):
                self._invoice_line_counter += 1
                line_number = j + 1

                # Base calculation from PO line
                po_line_key = f"{po_number}-{line_number}"
                base_amount = self.registry.invoice_amount_by_po_line.get(po_line_key, 1000)

                # Apply mismatch if needed
                if is_mismatch:
                    # Amount deviation > 10%
                    deviation = random.uniform(0.11, 0.30)
                    amount = base_amount * (1 + deviation if random.random() > 0.5 else 1 - deviation)
                else:
                    amount = base_amount * random.uniform(0.98, 1.02)

                total_amount += amount
                tax_rate = random.choice([0.06, 0.09, 0.13])

                line_props = {
                    "line_number": line_number,
                    "line_type": random.choice(["GOODS", "SERVICES"]),
                    "quantity": round(random.uniform(10, 500), 2),
                    "unit_price": round(amount / random.uniform(10, 500), 2),
                    "amount": round(amount, 2),
                    "tax_code": f"TAX{str(int(tax_rate * 100)).zfill(2)}",
                    "tax_rate": tax_rate,
                    "description": f"发票行 {invoice_number}-{line_number}",
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": invoice_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }

                line_vid = vid(VID_PREFIX_INVOICE_LINE, f"{invoice_number}-{line_number}")
                self.writer.write_vertex("InvoiceLine", line_vid, line_props)
                invoice_lines.append(line_vid)

            # Determine match status
            if is_mismatch:
                match_status = "UNMATCHED" if random.random() > 0.5 else "PARTIAL"
            else:
                match_status = "MATCHED"

            props = {
                "invoice_number": invoice_number,
                "invoice_type": random.choice(["STANDARD", "CREDIT_NOTE", "DEBIT_NOTE"]),
                "invoice_date": invoice_date,
                "due_date": due_date,
                "status": "APPROVED",
                "total_amount": round(total_amount, 2),
                "tax_amount": round(total_amount * 0.1, 2),  # Approximate
                "currency": random.choice(["CNY", "USD"]),
                "exchange_rate": 1.0,
                "payment_method": random.choice(["BANK_TRANSFER", "CHECK", "CREDIT"]),
                "description": f"[ANOMALY:TEMPORAL_VIOLATION] 供应商发票 {invoice_number}" if is_temporal_violation else f"供应商发票 {invoice_number}",
                "gl_date": invoice_date,
                "pay_group": random.choice(["STANDARD", "PRIORITY", "HOLD", "EMPLOYEE"]),
                "source": random.choice(["ERS", "MANUAL", "SelfService", "XML GATEWAY", "ISP"]),
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": invoice_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            inv_vid = vid(VID_PREFIX_INVOICE, invoice_number)
            self.writer.write_vertex("Invoice", inv_vid, props)
            self.registry.invoices.append(inv_vid)

            # Track invoice -> PO mapping
            self.registry.invoice_to_po[invoice_number] = po_number
            self.registry.invoice_dates[invoice_number] = invoice_date

            # Write edges
            self.writer.write_edge(
                "HAS_INVOICE",
                po_vid,
                inv_vid,
                {"match_status": match_status, "match_date": invoice_date, "org_id": org_id, "dept_id": dept_id}
            )

            self.writer.write_edge(
                "INVOICED_BY",
                inv_vid,
                supplier,
                {"org_id": org_id, "dept_id": dept_id}
            )

            for idx, line_vid in enumerate(invoice_lines):
                self.writer.write_edge(
                    "HAS_INVOICE_LINE",
                    inv_vid,
                    line_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

                # v2.0: Generate InvoiceDistribution for each line
                dist_id = f"IDIST-{invoice_number}-{idx+1}"
                line_amount = round(total_amount / len(invoice_lines), 2)
                dist_props = {
                    "distribution_id": dist_id,
                    "distribution_line_number": idx + 1,
                    "line_type": "ITEM",
                    "amount": line_amount,
                    "base_amount": line_amount,
                    "accounting_date": invoice_date,
                    "accrual_posted_flag": "N",
                    "posted_flag": random.choice(["Y", "Y", "N"]),
                    "match_status": match_status,
                    "reversal_flag": "N",
                    "parent_reversal_id": "",
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": invoice_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }
                dist_vid = vid(VID_PREFIX_INV_DIST, dist_id)
                self.writer.write_vertex("InvoiceDistribution", dist_vid, dist_props)
                self.registry.invoice_distributions.append(dist_vid)

                # HAS_INVOICE_DIST edge
                self.writer.write_edge(
                    "HAS_INVOICE_DIST",
                    line_vid,
                    dist_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

                # DIST_TO_ACCOUNT edge (to GLCodeCombination)
                if self.registry.gl_code_combinations:
                    ccid_vid = random.choice(self.registry.gl_code_combinations)
                    self.writer.write_edge(
                        "DIST_TO_ACCOUNT",
                        dist_vid,
                        ccid_vid,
                        {"org_id": org_id, "dept_id": dept_id}
                    )

                # MATCHES_SHIPMENT edge (distribution -> POShipment)
                po_line_key = f"{po_number}-{idx+1}"
                po_shipments = self.registry.po_line_to_shipments.get(po_line_key, [])
                if po_shipments:
                    posh_vid = random.choice(po_shipments)
                    self.writer.write_edge(
                        "MATCHES_SHIPMENT",
                        dist_vid,
                        posh_vid,
                        {"org_id": org_id, "dept_id": dept_id}
                    )

            # v2.0: REMIT_TO_SITE edge
            supplier_number_key = self.registry.po_to_supplier.get(po_number, "")
            remit_sites = self.registry.supplier_to_sites.get(supplier_number_key, [])
            if remit_sites:
                site_vid = random.choice(remit_sites)
                self.writer.write_edge(
                    "REMIT_TO_SITE",
                    inv_vid,
                    site_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

            # v2.0: Generate InvoiceHold (for mismatched invoices)
            if is_mismatch:
                hold_id = f"HOLD-{invoice_number}"
                hold_date = invoice_date + timedelta(days=random.randint(1, 5))
                is_released = random.random() > 0.4
                release_date = hold_date + timedelta(days=random.randint(1, 30)) if is_released else None

                hold_props = {
                    "hold_id": hold_id,
                    "hold_type": random.choice(["QTY_REC", "QTY_ORD", "PRICE", "TAX_DIFFERENCE", "AMOUNT"]),
                    "hold_reason": "三单匹配差异" if match_status == "UNMATCHED" else "部分匹配",
                    "hold_date": hold_date,
                    "release_date": release_date,
                    "release_reason": "手动释放" if is_released else None,
                    "held_by": "SYSTEM",
                    "released_by": random.choice(self.registry.employees).split(":")[1] if is_released else None,
                    "status": "RELEASED" if is_released else "HELD",
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": hold_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }
                hold_vid = vid(VID_PREFIX_INV_HOLD, hold_id)
                self.writer.write_vertex("InvoiceHold", hold_vid, hold_props)
                self.registry.invoice_holds.append(hold_vid)

                # HAS_HOLD edge
                self.writer.write_edge(
                    "HAS_HOLD",
                    inv_vid,
                    hold_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

                # HOLD_RELEASED_BY edge
                if is_released:
                    releaser = random.choice(self.registry.employees)
                    self.writer.write_edge(
                        "HOLD_RELEASED_BY",
                        hold_vid,
                        releaser,
                        {"org_id": org_id, "dept_id": dept_id}
                    )

            # v2.0: Generate PaymentSchedule
            num_installments = random.choice([1, 1, 1, 2, 3])
            for inst_num in range(1, num_installments + 1):
                sched_id = f"PS-{invoice_number}-{inst_num}"
                inst_amount = round(total_amount / num_installments, 2)
                inst_due = due_date + timedelta(days=30 * (inst_num - 1))

                sched_props = {
                    "schedule_id": sched_id,
                    "installment_number": inst_num,
                    "due_date": inst_due,
                    "gross_amount": inst_amount,
                    "amount_remaining": inst_amount if random.random() > 0.5 else 0,
                    "payment_status": random.choice(["FULL", "FULL", "NOT_PAID", "PARTIAL"]),
                    "discount_date": inst_due - timedelta(days=10) if random.random() > 0.5 else None,
                    "discount_amount_available": round(inst_amount * 0.02, 2) if random.random() > 0.5 else 0,
                    "second_discount_date": None,
                    "second_discount_amount": 0,
                    "third_discount_date": None,
                    "third_discount_amount": 0,
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": invoice_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }
                sched_vid = vid(VID_PREFIX_PAY_SCHEDULE, sched_id)
                self.writer.write_vertex("PaymentSchedule", sched_vid, sched_props)
                self.registry.payment_schedules.append(sched_vid)

                # HAS_PAYMENT_SCHEDULE edge
                self.writer.write_edge(
                    "HAS_PAYMENT_SCHEDULE",
                    inv_vid,
                    sched_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

    def _generate_payments(self):
        """Generate payments linked to invoices."""
        for i in range(NUM_PAYMENTS):
            payment_number = f"PAY{str(i+1).zfill(8)}"
            payment_date = random_date(DATA_START_DATE + timedelta(days=60), DATA_END_DATE)
            is_payment_temporal_violation = False

            # Link to an invoice
            invoice_vid = random.choice(self.registry.invoices)
            invoice_number = invoice_vid.split(":")[1]
            invoice_po = self.registry.invoice_to_po.get(invoice_number, "")
            supplier_number = self.registry.po_to_supplier.get(invoice_po, "SUP00001")
            supplier_vid = vid(VID_PREFIX_SUPPLIER, supplier_number)
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS-1)
            dept_id = 1000 + random.randint(0, 119)

            # Pattern 4: Temporal violation — payment before invoice date (3%)
            if random.random() < TEMPORAL_VIOLATION_RATE:
                inv_date = self.registry.invoice_dates.get(invoice_number)
                if inv_date:
                    payment_date = inv_date - timedelta(days=random.randint(10, 60))
                    is_payment_temporal_violation = True

            # Some payments cover multiple invoices
            num_invoices = random.randint(1, 3) if random.random() > 0.7 else 1
            linked_invoices = [invoice_vid]
            total_amount = 0

            if num_invoices > 1 and len(self.registry.invoices) > 1:
                for _ in range(num_invoices - 1):
                    other_inv = random.choice(self.registry.invoices)
                    if other_inv != invoice_vid:
                        linked_invoices.append(other_inv)

            # Track for payment -> invoice mapping
            self.registry.payment_to_invoice[payment_number] = [inv.split(":")[1] for inv in linked_invoices]

            props = {
                "payment_number": payment_number,
                "payment_type": random.choice(["NORMAL", "ADVANCE", "RETRO", "PREPAY"]),
                "payment_date": payment_date,
                "amount": round(random.uniform(1000, 500000), 2),
                "currency": random.choice(["CNY", "USD"]),
                "exchange_rate": 1.0,
                "status": "CLEARED",
                "bank_account": generate_bank_account(),
                "payment_method": random.choice(["BANK_TRANSFER", "CHECK", "CREDIT"]),
                "check_number": f"CHK{random.randint(100000, 999999)}" if random.random() > 0.5 else None,
                "cleared_date": payment_date + timedelta(days=random.randint(1, 5)),
                "void_date": None,
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": payment_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            pay_vid = vid(VID_PREFIX_PAYMENT, payment_number)
            self.writer.write_vertex("Payment", pay_vid, props)
            self.registry.payments.append(pay_vid)
            self.registry.payment_details.append(
                (pay_vid, payment_date, org_id, props["amount"], props["currency"])
            )

            # Write edges
            self.writer.write_edge(
                "PAID_TO",
                pay_vid,
                supplier_vid,
                {"org_id": org_id, "dept_id": dept_id}
            )

            for inv_vid in linked_invoices:
                self.writer.write_edge(
                    "PAYS_INVOICE",
                    pay_vid,
                    inv_vid,
                    {"paid_amount": round(props["amount"] / len(linked_invoices), 2), "org_id": org_id, "dept_id": dept_id}
                )

            # v2.0: PAID_TO_SITE edge (Payment -> SupplierSite)
            supplier_sites = self.registry.supplier_to_sites.get(supplier_number, [])
            if supplier_sites:
                site_vid = random.choice(supplier_sites)
                self.writer.write_edge(
                    "PAID_TO_SITE",
                    pay_vid,
                    site_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

            # v2.0: PAID_FROM_ACCOUNT edge (Payment -> BankAccount)
            if self.registry.bank_accounts:
                ba_vid = random.choice(self.registry.bank_accounts)
                self.writer.write_edge(
                    "PAID_FROM_ACCOUNT",
                    pay_vid,
                    ba_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

    def _generate_payment_batches(self):
        """Generate payment batches by grouping payments by (week, org_id, currency)."""
        from collections import defaultdict

        # Group payments by (iso_week, org_id, currency)
        groups = defaultdict(list)
        for pay_vid, pay_date, org_id, amount, currency in self.registry.payment_details:
            week_key = pay_date.strftime("%Y-W%W")
            groups[(week_key, org_id, currency)].append((pay_vid, amount))

        batch_num = 0
        for (week_key, org_id, currency), pay_list in sorted(groups.items()):
            batch_num += 1
            batch_number = f"PB{str(batch_num).zfill(6)}"
            total_amount = sum(amt for _, amt in pay_list)
            dept_id = 1000 + random.randint(0, 119)

            # Parse week_key back to a date for batch_date
            year, week = week_key.split("-W")
            batch_date = datetime.strptime(f"{year} {week} 1", "%Y %W %w")

            props = {
                "batch_number": batch_number,
                "batch_date": batch_date,
                "total_amount": round(total_amount, 2),
                "payment_count": len(pay_list),
                "status": "COMPLETED",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": batch_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            batch_vid = vid(VID_PREFIX_PAYMENT_BATCH, batch_number)
            self.writer.write_vertex("PaymentBatch", batch_vid, props)
            self.registry.payment_batches.append(batch_vid)

            # Write CONTAINS_PAYMENT edges
            for pay_vid, _ in pay_list:
                self.writer.write_edge(
                    "CONTAINS_PAYMENT",
                    batch_vid,
                    pay_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

    def _generate_sales_orders(self):
        """Generate sales orders with lines."""
        for i in range(NUM_SALES_ORDERS):
            so_number = f"SO{str(i+1).zfill(8)}"
            order_date = random_date(DATA_START_DATE, DATA_END_DATE - timedelta(days=7))

            customer = random.choice(self.registry.customers)
            customer_number = customer.split(":")[1]
            salesperson = random.choice(self.registry.employees)
            salesperson_number = salesperson.split(":")[1]
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS-1)
            dept_id = 1000 + random.randint(0, 119)

            # Generate SO lines
            num_lines = random.randint(1, 10)
            total_amount = 0
            so_lines = []
            line_items_data = []

            for j in range(num_lines):
                self._so_line_counter += 1
                line_number = j + 1
                quantity = round(random.uniform(1, 500), 2)
                unit_price = round(random.uniform(10, 5000), 2)
                amount = quantity * unit_price
                total_amount += amount
                tax_rate = random.choice([0, 0.06, 0.09, 0.13])

                line_props = {
                    "line_number": line_number,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "amount": round(amount * (1 + tax_rate), 2),
                    "uom": random.choice(["EA", "KG", "M", "L", "BOX"]),
                    "shipped_quantity": 0,
                    "invoiced_quantity": 0,
                    "status": "BOOKED",
                    "tax_code": f"TAX{str(int(tax_rate * 100)).zfill(2)}",
                    "tax_rate": tax_rate,
                    "scheduled_ship_date": order_date + timedelta(days=random.randint(7, 30)),
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": order_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }

                line_vid = vid(VID_PREFIX_SO_LINE, f"{so_number}-{line_number}")
                self.writer.write_vertex("SalesOrderLine", line_vid, line_props)
                so_lines.append(line_vid)

                # Track SO line quantities for ghost shipment detection
                self.registry.so_line_quantities[f"{so_number}-{line_number}"] = quantity

                # Pick an item
                item_vid = random.choice(self.registry.items)
                line_items_data.append((line_vid, item_vid, quantity, unit_price))

            props = {
                "so_number": so_number,
                "order_type": random.choice([" STANDARD", "BLANKET", "RUSH"]),
                "order_date": order_date,
                "status": "BOOKED",
                "total_amount": round(total_amount, 2),
                "currency": random.choice(["CNY", "USD", "EUR"]),
                "exchange_rate": 1.0 if random.random() > 0.1 else round(random.uniform(0.8, 1.2), 4),
                "payment_terms": random.choice(["NET30", "NET45", "NET60", "PREPAID"]),
                "ship_to_address": f"{random.choice(['北京', '上海', '广州', '深圳'])}市{random.choice(['朝阳', '海淀', '浦东', '南山'])}区",
                "bill_to_address": f"{random.choice(['北京', '上海', '广州', '深圳'])}市{random.choice(['朝阳', '海淀', '浦东', '南山'])}区",
                "salesperson": salesperson_number,
                "requested_date": order_date + timedelta(days=random.randint(7, 45)),
                "scheduled_date": order_date + timedelta(days=random.randint(14, 60)),
                "cancel_reason": None,
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": order_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            so_vid = vid(VID_PREFIX_SO, so_number)
            self.writer.write_vertex("SalesOrder", so_vid, props)
            self.registry.sales_orders.append(so_vid)

            # Track SO -> customer mapping
            self.registry.so_to_customer[so_number] = customer_number

            # Write edges
            self.writer.write_edge(
                "SOLD_TO",
                so_vid,
                customer,
                {"order_date": order_date, "org_id": org_id, "dept_id": dept_id}
            )

            for line_vid, item_vid, qty, price in line_items_data:
                self.writer.write_edge(
                    "HAS_SO_LINE",
                    so_vid,
                    line_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

                self.writer.write_edge(
                    "SELLS_ITEM",
                    line_vid,
                    item_vid,
                    {"quantity": qty, "unit_price": price, "org_id": org_id, "dept_id": dept_id}
                )

            # v2.0: BILL_TO_SITE edge (SalesOrder -> CustomerSite)
            customer_sites = self.registry.customer_to_sites.get(customer_number, [])
            if customer_sites:
                bill_site = random.choice(customer_sites)
                self.writer.write_edge(
                    "BILL_TO_SITE",
                    so_vid,
                    bill_site,
                    {"org_id": org_id, "dept_id": dept_id}
                )

    def _generate_shipments(self):
        """Generate shipments linked to SOs."""
        for i in range(NUM_SHIPMENTS):
            shipment_number = f"SHP{str(i+1).zfill(8)}"
            shipment_date = random_date(DATA_START_DATE + timedelta(days=30), DATA_END_DATE)

            # Link to a SO
            so_number = random.choice(self.registry.sales_orders).split(":")[1]
            so_vid = vid(VID_PREFIX_SO, so_number)
            warehouse = random.choice(self.registry.warehouses)
            warehouse_code = warehouse.split(":")[1]
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS-1)
            dept_id = 1000 + random.randint(0, 119)

            # Generate shipment lines
            num_lines = random.randint(1, 5)
            total_quantity = 0
            shipment_lines = []

            for j in range(num_lines):
                self._shipment_line_counter += 1
                line_number = j + 1
                shipped_qty = round(random.uniform(10, 500), 2)
                total_quantity += shipped_qty

                line_props = {
                    "line_number": line_number,
                    "shipped_quantity": shipped_qty,
                    "uom": random.choice(["EA", "KG", "M", "L", "BOX"]),
                    "lot_number": f"LOT{shipment_date.strftime('%Y%m%d')}{random.randint(1000, 9999)}",
                    "serial_number": f"SN{random.randint(100000000, 999999999)}" if random.random() > 0.5 else None,
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": shipment_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }

                line_vid = vid(VID_PREFIX_SHIPMENT_LINE, f"{shipment_number}-{line_number}")
                self.writer.write_vertex("ShipmentLine", line_vid, line_props)
                shipment_lines.append(line_vid)

            props = {
                "shipment_number": shipment_number,
                "shipment_date": shipment_date,
                "status": "SHIPPED",
                "carrier": random.choice(["顺丰", "中通", "韵达", "圆通", "德邦", "安能"]),
                "tracking_number": f"SF{random.randint(100000000000, 999999999999)}",
                "total_quantity": round(total_quantity, 2),
                "warehouse": warehouse_code,
                "delivery_date": shipment_date + timedelta(days=random.randint(1, 7)),
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": shipment_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            shp_vid = vid(VID_PREFIX_SHIPMENT, shipment_number)
            self.writer.write_vertex("Shipment", shp_vid, props)
            self.registry.shipments.append(shp_vid)

            # Track shipment -> SO mapping
            self.registry.shipment_to_so[shipment_number] = so_number
            # Track SO -> shipment date for premature revenue detection
            self.registry.so_to_shipment_date[so_number] = shipment_date

            # Write edges
            self.writer.write_edge(
                "HAS_SHIPMENT",
                so_vid,
                shp_vid,
                {"org_id": org_id, "dept_id": dept_id}
            )

            for line_vid in shipment_lines:
                self.writer.write_edge(
                    "HAS_SHIPMENT_LINE",
                    shp_vid,
                    line_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

            self.writer.write_edge(
                "SHIPPED_FROM",
                shp_vid,
                warehouse,
                {"org_id": org_id, "dept_id": dept_id}
            )

    def _generate_ar_invoices(self):
        """Generate AR invoices linked to SOs."""
        for i in range(NUM_AR_INVOICES):
            invoice_number = f"ARI{str(i+1).zfill(8)}"
            invoice_date = random_date(DATA_START_DATE + timedelta(days=30), DATA_END_DATE)
            due_date = invoice_date + timedelta(days=random.randint(30, 90))

            # Link to a SO
            so_number = random.choice(self.registry.sales_orders).split(":")[1]
            so_vid = vid(VID_PREFIX_SO, so_number)
            customer = vid(VID_PREFIX_CUSTOMER, self.registry.so_to_customer[so_number])
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS-1)
            dept_id = 1000 + random.randint(0, 119)

            # Some AR invoices are standalone (not linked to SO)
            if random.random() > 0.8:
                so_vid = None
                so_number = None

            # Pattern 8: Premature Revenue Recognition — invoice date before shipment date
            premature_revenue = False
            if so_number and random.random() < TEMPORAL_VIOLATION_RATE:
                shipment_date = self.registry.so_to_shipment_date.get(so_number)
                if shipment_date:
                    invoice_date = shipment_date - timedelta(days=random.randint(15, 45))
                    due_date = invoice_date + timedelta(days=random.randint(30, 90))
                    premature_revenue = True

            props = {
                "invoice_number": invoice_number,
                "invoice_type": random.choice(["AR_INVOICE", "CREDIT_MEMO", "DEBIT_MEMO"]),
                "invoice_date": invoice_date,
                "due_date": due_date,
                "status": "OPEN",
                "total_amount": round(random.uniform(1000, 500000), 2),
                "tax_amount": round(random.uniform(60, 50000), 2),
                "currency": random.choice(["CNY", "USD", "EUR"]),
                "exchange_rate": 1.0,
                "payment_terms": random.choice(["NET30", "NET45", "NET60"]),
                "gl_date": invoice_date,
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": invoice_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            ari_vid = vid(VID_PREFIX_AR_INVOICE, invoice_number)
            self.writer.write_vertex("ARInvoice", ari_vid, props)
            self.registry.ar_invoices.append(ari_vid)

            # Track AR invoice -> SO mapping
            if so_number:
                self.registry.ar_invoice_to_so[invoice_number] = so_number

            # Write edge to SO if linked
            if so_vid:
                self.writer.write_edge(
                    "HAS_AR_INVOICE",
                    so_vid,
                    ari_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

            # v2.0: Generate ARInvoiceLine for each AR invoice
            num_ar_lines = random.randint(1, 5)
            for j in range(num_ar_lines):
                line_num = j + 1
                line_qty = round(random.uniform(1, 200), 2)
                line_price = round(random.uniform(10, 5000), 2)
                line_amount = round(line_qty * line_price, 2)
                tax_rate = random.choice([0.06, 0.09, 0.13])

                ar_line_props = {
                    "line_number": line_num,
                    "line_type": random.choice(["LINE", "TAX", "FREIGHT"]),
                    "quantity": line_qty,
                    "unit_selling_price": line_price,
                    "amount": line_amount,
                    "tax_code": f"TAX{str(int(tax_rate * 100)).zfill(2)}",
                    "tax_rate": tax_rate,
                    "description": f"{'[ANOMALY:PREMATURE_REVENUE] ' if premature_revenue else ''}AR发票行 {invoice_number}-{line_num}",
                    "revenue_amount": round(line_amount * 0.87, 2),
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": invoice_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }

                ar_line_vid = vid(VID_PREFIX_ARI_LINE, f"{invoice_number}-{line_num}")
                self.writer.write_vertex("ARInvoiceLine", ar_line_vid, ar_line_props)
                self.registry.ar_invoice_lines.append(ar_line_vid)

                # HAS_AR_INVOICE_LINE edge
                self.writer.write_edge(
                    "HAS_AR_INVOICE_LINE",
                    ari_vid,
                    ar_line_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

                # AR_LINE_FOR_ITEM edge
                if self.registry.items:
                    item_vid = random.choice(self.registry.items)
                    self.writer.write_edge(
                        "AR_LINE_FOR_ITEM",
                        ar_line_vid,
                        item_vid,
                        {"org_id": org_id, "dept_id": dept_id}
                    )

            # v2.0: BILL_TO_SITE edge (ARInvoice -> CustomerSite)
            customer_number = customer.split(":")[1]
            customer_sites = self.registry.customer_to_sites.get(customer_number, [])
            if customer_sites:
                bill_to_site = random.choice(customer_sites)
                self.writer.write_edge(
                    "BILL_TO_SITE",
                    ari_vid,
                    bill_to_site,
                    {"org_id": org_id, "dept_id": dept_id}
                )

    def _generate_ar_receipts(self):
        """Generate AR receipts linked to AR invoices."""
        for i in range(NUM_AR_RECEIPTS):
            receipt_number = f"ARR{str(i+1).zfill(8)}"
            receipt_date = random_date(DATA_START_DATE + timedelta(days=60), DATA_END_DATE)

            # Link to an AR invoice
            ar_invoice_vid = random.choice(self.registry.ar_invoices)
            ar_invoice_number = ar_invoice_vid.split(":")[1]
            ar_invoice_so = self.registry.ar_invoice_to_so.get(ar_invoice_number, "")
            customer_number = self.registry.so_to_customer.get(ar_invoice_so, "CUS00001")
            customer_vid = vid(VID_PREFIX_CUSTOMER, customer_number)
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS-1)
            dept_id = 1000 + random.randint(0, 119)

            # Some receipts apply to multiple AR invoices
            num_invoices = random.randint(1, 3) if random.random() > 0.7 else 1
            linked_ar_invoices = [ar_invoice_vid]

            if num_invoices > 1 and len(self.registry.ar_invoices) > 1:
                for _ in range(num_invoices - 1):
                    other_ari = random.choice(self.registry.ar_invoices)
                    if other_ari != ar_invoice_vid:
                        linked_ar_invoices.append(other_ari)

            # Track for AR receipt -> AR invoice mapping
            self.registry.ar_receipt_to_ar_invoice[receipt_number] = [inv.split(":")[1] for inv in linked_ar_invoices]

            total_amount = 0
            applied_amounts = []

            for _ in range(len(linked_ar_invoices)):
                applied = round(random.uniform(1000, 200000), 2)
                total_amount += applied
                applied_amounts.append(applied)

            props = {
                "receipt_number": receipt_number,
                "receipt_type": random.choice(["CASH", "CHECK", "WIRE", "CARD"]),
                "receipt_date": receipt_date,
                "amount": total_amount,
                "currency": random.choice(["CNY", "USD"]),
                "status": "APPLIED",
                "payment_method": random.choice(["CASH", "CHECK", "WIRE_TRANSFER", "CREDIT_CARD"]),
                "bank_account": generate_bank_account(),
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": receipt_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            arr_vid = vid(VID_PREFIX_AR_RECEIPT, receipt_number)
            self.writer.write_vertex("ARReceipt", arr_vid, props)
            self.registry.ar_receipts.append(arr_vid)

            # Track for credit memo fraud injection
            self.registry.ar_receipt_details.append(
                (arr_vid, total_amount, receipt_date, customer_number)
            )

            # Write edges
            self.writer.write_edge(
                "RECEIVED_FROM",
                arr_vid,
                customer_vid,
                {"org_id": org_id, "dept_id": dept_id}
            )

            for idx, inv_vid in enumerate(linked_ar_invoices):
                self.writer.write_edge(
                    "APPLIES_TO",
                    arr_vid,
                    inv_vid,
                    {"applied_amount": applied_amounts[idx], "org_id": org_id, "dept_id": dept_id}
                )

            # v2.0: RECEIVED_TO_ACCOUNT edge (ARReceipt -> BankAccount)
            if self.registry.bank_accounts:
                ba_vid = random.choice(self.registry.bank_accounts)
                self.writer.write_edge(
                    "RECEIVED_TO_ACCOUNT",
                    arr_vid,
                    ba_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

    def _generate_gl_journal_entries(self):
        """Generate GL journal entries with lines."""
        for i in range(NUM_GL_JOURNAL_ENTRIES):
            journal_number = f"JLE{str(i+1).zfill(8)}"
            gl_date = random_date(DATA_START_DATE, DATA_END_DATE)

            # Determine period
            period_name = gl_date.strftime("%Y-%m")

            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS-1)
            dept_id = 1000 + random.randint(0, 119)

            # Generate journal lines (debit/credit entries)
            num_lines = random.randint(2, 8)
            total_debit = 0
            total_credit = 0
            journal_lines = []

            for j in range(num_lines):
                self._journal_line_counter += 1
                line_number = j + 1

                if j == num_lines - 1:
                    # Last line is balancing line
                    amount = abs(total_debit - total_credit)
                    if total_debit > total_credit:
                        debit = 0
                        credit = amount
                    else:
                        debit = amount
                        credit = 0
                else:
                    amount = round(random.uniform(100, 100000), 2)
                    if random.random() > 0.5:
                        debit = amount
                        credit = 0
                        total_debit += amount
                    else:
                        debit = 0
                        credit = amount
                        total_credit += amount

                # Pick a GL account
                gl_account = random.choice(self.registry.gl_accounts)
                gl_account_code = gl_account.split(":")[1]

                line_props = {
                    "line_number": line_number,
                    "debit_amount": round(debit, 2),
                    "credit_amount": round(credit, 2),
                    "description": f"分录 {journal_number}-{line_number}",
                    "reference": f"REF{gl_date.strftime('%Y%m')}{random.randint(1000, 9999)}",
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": gl_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }

                line_vid = vid(VID_PREFIX_JOURNAL_LINE, f"{journal_number}-{line_number}")
                self.writer.write_vertex("GLJournalLine", line_vid, line_props)
                journal_lines.append((line_vid, gl_account, credit))

            # Ensure debits == credits for journal entry
            imbalance = total_debit - total_credit
            if imbalance != 0 and journal_lines:
                # Adjust the last line to balance
                last_line_vid, last_gl_account, last_credit = journal_lines[-1]
                if imbalance > 0:
                    # Increase credit to balance
                    new_credit = round(last_credit + imbalance, 2)
                    line_props["credit_amount"] = new_credit
                    line_props["debit_amount"] = 0
                    self.writer.write_vertex("GLJournalLine", last_line_vid, line_props)

            props = {
                "journal_number": journal_number,
                "journal_name": f"日记账-{journal_number}",
                "journal_source": random.choice(["PO", "SO", "RECEIPT", "MANUAL", "INTERFACE"]),
                "journal_category": random.choice(["Purchase", "Sales", "Cash", "General", "Adjustment"]),
                "period_name": period_name,
                "gl_date": gl_date,
                "status": "POSTED",
                "total_debit": round(total_debit, 2),
                "total_credit": round(total_credit, 2),
                "description": f"凭证 {journal_number}",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": gl_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            jle_vid = vid(VID_PREFIX_JOURNAL, journal_number)
            self.writer.write_vertex("GLJournalEntry", jle_vid, props)
            self.registry.gl_journal_entries.append(jle_vid)

            # Write edges
            for line_vid, gl_account, _credit in journal_lines:
                self.writer.write_edge(
                    "HAS_JOURNAL_LINE",
                    jle_vid,
                    line_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

                self.writer.write_edge(
                    "POSTED_TO",
                    line_vid,
                    gl_account,
                    {"org_id": org_id, "dept_id": dept_id}
                )

            # v2.0: IN_LEDGER edge
            if self.registry.ledgers:
                ledger_vid = random.choice(self.registry.ledgers)
                self.writer.write_edge(
                    "IN_LEDGER",
                    jle_vid,
                    ledger_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

            # v2.0: IN_PERIOD edge
            period_vid = vid(VID_PREFIX_GL_PERIOD, period_name)
            if period_vid in self.registry.gl_periods:
                self.writer.write_edge(
                    "IN_PERIOD",
                    jle_vid,
                    period_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

            # v2.0: IN_BATCH edge
            if self.registry.gl_journal_batches:
                batch_vid = random.choice(self.registry.gl_journal_batches)
                self.writer.write_edge(
                    "IN_BATCH",
                    jle_vid,
                    batch_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

    def _generate_xla_events(self):
        """Generate XLA accounting events."""
        for i in range(NUM_XLA_EVENTS):
            event_id = f"XLA{str(i+1).zfill(10)}"
            event_date = random_date(DATA_START_DATE, DATA_END_DATE)

            # Determine source document type
            doc_types = ["PO", "SO", "RECEIPT", "INVOICE", "PAYMENT", "AR_RECEIPT"]
            doc_type = random.choice(doc_types)

            # Generate source doc ID based on type
            if doc_type == "PO":
                source_doc_id = random.choice(self.registry.purchase_orders).split(":")[1]
            elif doc_type == "SO":
                source_doc_id = random.choice(self.registry.sales_orders).split(":")[1]
            elif doc_type == "RECEIPT":
                source_doc_id = random.choice(self.registry.receipts).split(":")[1]
            elif doc_type == "INVOICE":
                source_doc_id = random.choice(self.registry.invoices).split(":")[1]
            elif doc_type == "PAYMENT":
                source_doc_id = random.choice(self.registry.payments).split(":")[1]
            else:
                source_doc_id = random.choice(self.registry.ar_receipts).split(":")[1]

            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS-1)
            dept_id = 1000 + random.randint(0, 119)

            props = {
                "event_id": event_id,
                "event_class": random.choice(["AP", "AR", "GL", "FA", "INV"]),
                "event_type": random.choice(["CREATE", "UPDATE", "VALIDATE", "ACCOUNT"]),
                "event_date": event_date,
                "accounting_date": event_date + timedelta(days=random.randint(0, 2)),
                "status": "ACCOUNTED",
                "source_doc_type": doc_type,
                "source_doc_id": source_doc_id,
                "description": f"XLA事件 {event_id}",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": event_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            xla_vid = vid(VID_PREFIX_XLA_EVENT, event_id)
            self.writer.write_vertex("XLAEvent", xla_vid, props)
            self.registry.xla_events.append(xla_vid)

            # Write edge to source document
            source_vid = self._get_source_doc_vid(doc_type, source_doc_id)
            if source_vid:
                self.writer.write_edge(
                    "ACCOUNTING_FOR",
                    xla_vid,
                    source_vid,
                    {"event_class": props["event_class"], "org_id": org_id, "dept_id": dept_id}
                )

            # Generate accounting distributions
            self._generate_accounting_distributions(xla_vid, org_id, dept_id, event_date)

            # v2.0: Generate XLAJournalEntry (XLA_AE_HEADERS)
            ae_header_id = f"AEH-{event_id}"
            accounting_date = event_date + timedelta(days=random.randint(0, 2))
            period_name = accounting_date.strftime("%Y-%m")

            xla_je_props = {
                "ae_header_id": ae_header_id,
                "accounting_entry_status": "F",  # Final
                "accounting_date": accounting_date,
                "period_name": period_name,
                "je_category": random.choice(["Purchase Invoices", "Sales Invoices", "Receipts", "Payments"]),
                "gl_transfer_status": random.choice(["Y", "Y", "N"]),
                "description": f"XLA分录 {ae_header_id}",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": event_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            xla_je_vid = vid(VID_PREFIX_XLA_JOURNAL, ae_header_id)
            self.writer.write_vertex("XLAJournalEntry", xla_je_vid, xla_je_props)
            self.registry.xla_journal_entries.append(xla_je_vid)

            # GENERATES_ENTRY edge (XLAEvent -> XLAJournalEntry)
            self.writer.write_edge(
                "GENERATES_ENTRY",
                xla_vid,
                xla_je_vid,
                {"org_id": org_id, "dept_id": dept_id}
            )

            # TRANSFERRED_TO_GL edge (XLAJournalEntry -> GLJournalEntry)
            if xla_je_props["gl_transfer_status"] == "Y" and self.registry.gl_journal_entries:
                gl_je_vid = random.choice(self.registry.gl_journal_entries)
                self.writer.write_edge(
                    "TRANSFERRED_TO_GL",
                    xla_je_vid,
                    gl_je_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

            # v2.0: Generate XLAJournalLine(s) (XLA_AE_LINES)
            num_xla_lines = random.randint(2, 4)
            for lnum in range(num_xla_lines):
                xla_line_id = f"AEL-{event_id}-{lnum+1}"
                xla_amount = round(random.uniform(100, 50000), 2)

                xla_line_props = {
                    "ae_line_num": lnum + 1,
                    "accounting_class": random.choice(["ACCRUAL", "ITEM_EXPENSE", "ASSET", "LIABILITY", "REVENUE"]),
                    "entered_dr": xla_amount if lnum % 2 == 0 else 0,
                    "entered_cr": 0 if lnum % 2 == 0 else xla_amount,
                    "accounted_dr": xla_amount if lnum % 2 == 0 else 0,
                    "accounted_cr": 0 if lnum % 2 == 0 else xla_amount,
                    "currency_code": "CNY",
                    "currency_conversion_rate": 1.0,
                    "description": f"XLA行 {xla_line_id}",
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": event_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }

                xla_line_vid = vid(VID_PREFIX_XLA_LINE, xla_line_id)
                self.writer.write_vertex("XLAJournalLine", xla_line_vid, xla_line_props)
                self.registry.xla_journal_lines.append(xla_line_vid)

                # HAS_XLA_LINE edge
                self.writer.write_edge(
                    "HAS_XLA_LINE",
                    xla_je_vid,
                    xla_line_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

                # XLA_LINE_TO_ACCOUNT edge (to GLCodeCombination)
                if self.registry.gl_code_combinations:
                    ccid_vid = random.choice(self.registry.gl_code_combinations)
                    self.writer.write_edge(
                        "XLA_LINE_TO_ACCOUNT",
                        xla_line_vid,
                        ccid_vid,
                        {"org_id": org_id, "dept_id": dept_id}
                    )

                # v2.0: Generate XLADistributionLink
                link_id = f"XLDL-{event_id}-{lnum+1}"
                link_props = {
                    "link_id": link_id,
                    "source_distribution_type": random.choice(["AP_INV_DIST", "AP_PMT_DIST", "RCV_RECEIVING_SUB_LEDGER"]),
                    "source_distribution_id": f"DIST-{random.randint(10000,99999)}",
                    "applied_to_dist_id": "",
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": event_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }

                link_vid = vid(VID_PREFIX_XLA_DIST_LINK, link_id)
                self.writer.write_vertex("XLADistributionLink", link_vid, link_props)
                self.registry.xla_dist_links.append(link_vid)

                # XLA_DIST_LINK edge
                self.writer.write_edge(
                    "XLA_DIST_LINK",
                    xla_line_vid,
                    link_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

                # LINKS_TO_SOURCE_DIST edge (to InvoiceDistribution if available)
                if self.registry.invoice_distributions:
                    source_dist = random.choice(self.registry.invoice_distributions)
                    self.writer.write_edge(
                        "LINKS_TO_SOURCE_DIST",
                        link_vid,
                        source_dist,
                        {"org_id": org_id, "dept_id": dept_id}
                    )

    def _generate_accounting_distributions(self, xla_vid: str, org_id: int, dept_id: int, event_date: datetime):
        """Generate accounting distributions for an XLA event."""
        num_distributions = random.randint(2, 5)
        total_debit = 0
        total_credit = 0

        for j in range(num_distributions):
            dist_id = f"ACD{xla_vid[3:]}{str(j+1).zfill(2)}"
            amount = round(random.uniform(100, 50000), 2)

            if j == num_distributions - 1:
                # Balancing line
                if total_debit > total_credit:
                    credit = total_debit - total_credit
                    debit = 0
                else:
                    debit = total_credit - total_debit
                    credit = 0
            else:
                if random.random() > 0.5:
                    debit = amount
                    credit = 0
                    total_debit += amount
                else:
                    debit = 0
                    credit = amount
                    total_credit += amount

            gl_account = random.choice(self.registry.gl_accounts)
            gl_account_code = gl_account.split(":")[1]

            dist_props = {
                "distribution_id": dist_id,
                "line_number": j + 1,
                "debit_amount": round(debit, 2),
                "credit_amount": round(credit, 2),
                "currency": "CNY",
                "accounting_class": random.choice(["PREPAID", "ACCRUAL", "ASSET", "LIABILITY", "EXPENSE", "REVENUE"]),
                "posted_flag": True,
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": event_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            dist_vid = vid(VID_PREFIX_ACCT_DIST, dist_id)
            self.writer.write_vertex("AccountingDistribution", dist_vid, dist_props)

            self.writer.write_edge(
                "DISTRIBUTED_TO",
                dist_vid,
                gl_account,
                {"org_id": org_id, "dept_id": dept_id}
            )

    # =================================================================
    # v2.0 Generation Methods — New Entities & Edges
    # =================================================================

    def _generate_supplier_sites(self):
        """Generate supplier sites (AP_SUPPLIER_SITES_ALL)."""
        for i in range(NUM_SUPPLIER_SITES):
            site_code = f"SITE{str(i+1).zfill(6)}"
            supplier_vid = random.choice(self.registry.suppliers)
            supplier_number = supplier_vid.split(":")[1]
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS - 1)
            dept_id = 1000 + random.randint(0, 119)
            city_info = random.choice(CITIES)

            props = {
                "site_code": site_code,
                "site_name": f"{city_info[0]}站点-{site_code}",
                "address": f"{city_info[0]}市{random.choice(['朝阳', '海淀', '浦东', '南山'])}区{random.randint(1,999)}号",
                "city": city_info[0],
                "country": "CN",
                "phone": f"1{random.choice(['3','5','7','8','9'])}{random.randint(100000000,999999999)}",
                "fax": f"0{random.randint(10,99)}-{random.randint(10000000,99999999)}",
                "pay_site_flag": random.choice(["Y", "Y", "Y", "N"]),
                "purchasing_site_flag": random.choice(["Y", "Y", "Y", "N"]),
                "rfq_site_flag": random.choice(["N", "N", "Y"]),
                "bank_account_name": f"{random.choice(['中国银行','工商银行','建设银行','农业银行','招商银行'])}",
                "bank_account_number": generate_bank_account(),
                "bank_name": random.choice(["中国银行", "工商银行", "建设银行", "农业银行", "招商银行"]),
                "payment_method": random.choice(["WIRE", "CHECK", "EFT", "DRAFT"]),
                "payment_terms": random.choice(["NET30", "NET45", "NET60", "IMMEDIATE"]),
                "pay_group": random.choice(["STANDARD", "PRIORITY", "HOLD"]),
                "status": "ACTIVE",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": random_date(DATA_START_DATE, DATA_END_DATE),
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            site_vid = vid(VID_PREFIX_SUPPLIER_SITE, site_code)
            self.writer.write_vertex("SupplierSite", site_vid, props)
            self.registry.supplier_sites.append(site_vid)

            # Track supplier -> sites mapping
            self.registry.supplier_to_sites.setdefault(supplier_number, []).append(site_vid)

            # Edge: Supplier -> SupplierSite
            self.writer.write_edge(
                "HAS_SUPPLIER_SITE",
                supplier_vid,
                site_vid,
                {"org_id": org_id, "dept_id": dept_id}
            )

    def _generate_customer_sites(self):
        """Generate customer sites (HZ_CUST_ACCT_SITES_ALL)."""
        for i in range(NUM_CUSTOMER_SITES):
            site_number = f"CSITE{str(i+1).zfill(6)}"
            customer_vid = random.choice(self.registry.customers)
            customer_number = customer_vid.split(":")[1]
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS - 1)
            dept_id = 1000 + random.randint(0, 119)
            city_info = random.choice(CITIES)

            props = {
                "site_number": site_number,
                "site_name": f"{city_info[0]}客户站点-{site_number}",
                "address": f"{city_info[0]}市{random.choice(['朝阳', '海淀', '浦东', '南山'])}区{random.randint(1,999)}号",
                "city": city_info[0],
                "country": "CN",
                "site_use_code": random.choice(["BILL_TO", "SHIP_TO", "BILL_TO", "SHIP_TO", "DELIVER_TO"]),
                "primary_flag": "Y" if i % 3 == 0 else "N",
                "status": "ACTIVE",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": random_date(DATA_START_DATE, DATA_END_DATE),
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            site_vid = vid(VID_PREFIX_CUSTOMER_SITE, site_number)
            self.writer.write_vertex("CustomerSite", site_vid, props)
            self.registry.customer_sites.append(site_vid)

            # Track customer -> sites mapping
            self.registry.customer_to_sites.setdefault(customer_number, []).append(site_vid)

            # Edge: Customer -> CustomerSite
            self.writer.write_edge(
                "HAS_CUSTOMER_SITE",
                customer_vid,
                site_vid,
                {"org_id": org_id, "dept_id": dept_id}
            )

    def _generate_item_categories(self):
        """Generate item categories (MTL_CATEGORIES_B)."""
        parent_categories = []
        for i in range(NUM_ITEM_CATEGORIES):
            cat_id = f"CAT{str(i+1).zfill(6)}"
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS - 1)
            dept_id = 1000 + random.randint(0, 119)

            # First 5 are top-level
            is_top_level = i < 5
            cat_name = ITEM_CATEGORIES[i % len(ITEM_CATEGORIES)]

            props = {
                "category_id": cat_id,
                "category_set_name": "DEFAULT",
                "segment1": cat_name.split("-")[0] if "-" in cat_name else cat_name,
                "segment2": cat_name.split("-")[1] if "-" in cat_name else "",
                "description": f"物料类别-{cat_name}",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": DATA_START_DATE,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            cat_vid = vid(VID_PREFIX_ITEM_CAT, cat_id)
            self.writer.write_vertex("ItemCategory", cat_vid, props)
            self.registry.item_categories.append(cat_vid)

            if is_top_level:
                parent_categories.append(cat_vid)
            elif parent_categories:
                # PARENT_CATEGORY edge
                parent_vid = random.choice(parent_categories)
                self.writer.write_edge(
                    "PARENT_CATEGORY",
                    cat_vid,
                    parent_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

        # ITEM_IN_CATEGORY edges for existing items
        if self.registry.item_categories:
            for item_vid in self.registry.items:
                cat_vid = random.choice(self.registry.item_categories)
                org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS - 1)
                dept_id = 1000 + random.randint(0, 119)
                self.writer.write_edge(
                    "ITEM_IN_CATEGORY",
                    item_vid,
                    cat_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )
                # Track for supplier concentration pattern (Pattern 6)
                self.registry.item_to_category[item_vid] = cat_vid

    def _generate_ledgers(self):
        """Generate ledgers (GL_LEDGERS)."""
        ledger_names = ["主账套-CNY", "美元账套-USD", "合并账套-CONS"]
        currencies = ["CNY", "USD", "CNY"]
        for i in range(NUM_LEDGERS):
            ledger_id = f"LDG{str(i+1).zfill(4)}"
            org_id = 1000 + i
            dept_id = 1000

            props = {
                "ledger_id": ledger_id,
                "ledger_name": ledger_names[i] if i < len(ledger_names) else f"账套-{ledger_id}",
                "short_name": f"L{i+1}",
                "chart_of_accounts_id": f"COA{str(i+1).zfill(4)}",
                "currency_code": currencies[i] if i < len(currencies) else "CNY",
                "period_set_name": "MONTHLY",
                "period_type": "Month",
                "description": f"账套 {ledger_id}",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": DATA_START_DATE,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            ldg_vid = vid(VID_PREFIX_LEDGER, ledger_id)
            self.writer.write_vertex("Ledger", ldg_vid, props)
            self.registry.ledgers.append(ldg_vid)

    def _generate_gl_periods(self):
        """Generate GL periods (GL_PERIOD_STATUSES)."""
        current = DATA_START_DATE
        for i in range(NUM_GL_PERIODS):
            period_name = current.strftime("%Y-%m")
            period_year = current.year
            period_num = current.month
            start_date = current.replace(day=1)
            # End of month
            if current.month == 12:
                end_date = current.replace(year=current.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                end_date = current.replace(month=current.month + 1, day=1) - timedelta(days=1)

            org_id = 1000
            dept_id = 1000

            # Older periods are closed, recent ones open
            months_ago = (DATA_END_DATE.year - current.year) * 12 + (DATA_END_DATE.month - current.month)
            if months_ago > 2:
                closing_status = "C"  # Closed
            elif months_ago > 0:
                closing_status = "O"  # Open
            else:
                closing_status = "F"  # Future

            props = {
                "period_name": period_name,
                "period_year": period_year,
                "period_num": period_num,
                "start_date": start_date,
                "end_date": end_date,
                "closing_status": closing_status,
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": DATA_START_DATE,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            period_vid = vid(VID_PREFIX_GL_PERIOD, period_name)
            self.writer.write_vertex("GLPeriod", period_vid, props)
            self.registry.gl_periods.append(period_vid)

            # Advance to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

    def _generate_gl_code_combinations(self):
        """Generate GL code combinations / CCIDs (GL_CODE_COMBINATIONS)."""
        account_types = ["A", "L", "E", "R", "O"]  # Asset, Liability, Expense, Revenue, Other
        segments1 = ["01", "02", "03", "04", "05"]  # Company
        segments2 = ["100", "200", "300", "400", "500"]  # Department
        segments3 = ["1100", "1200", "2100", "2200", "3100", "3200", "4100", "4200", "5100", "5200",
                     "6100", "6200", "6300", "7100", "7200", "8100", "8200", "9100", "9200", "9900"]  # Natural Account

        for i in range(NUM_GL_CODE_COMBINATIONS):
            ccid = f"CCID{str(i+1).zfill(6)}"
            s1 = segments1[i % len(segments1)]
            s2 = segments2[(i // len(segments1)) % len(segments2)]
            s3 = segments3[i % len(segments3)]
            s4 = "000"
            s5 = "000"
            concatenated = f"{s1}-{s2}-{s3}-{s4}-{s5}"
            org_id = 1000
            dept_id = 1000

            props = {
                "code_combination_id": ccid,
                "segment1": s1,
                "segment2": s2,
                "segment3": s3,
                "segment4": s4,
                "segment5": s5,
                "concatenated_segments": concatenated,
                "enabled_flag": "Y",
                "summary_flag": "N",
                "account_type": account_types[i % len(account_types)],
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": DATA_START_DATE,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            ccid_vid = vid(VID_PREFIX_CCID, ccid)
            self.writer.write_vertex("GLCodeCombination", ccid_vid, props)
            self.registry.gl_code_combinations.append(ccid_vid)

            # ACCOUNT_IN_COA: link CCID to a GLAccount
            if self.registry.gl_accounts:
                gl_account = random.choice(self.registry.gl_accounts)
                self.writer.write_edge(
                    "ACCOUNT_IN_COA",
                    ccid_vid,
                    gl_account,
                    {"org_id": org_id, "dept_id": dept_id}
                )

    def _generate_currency_rates(self):
        """Generate currency exchange rates (GL_DAILY_RATES)."""
        currency_pairs = [("USD", "CNY"), ("EUR", "CNY"), ("GBP", "CNY"), ("JPY", "CNY"),
                          ("CNY", "USD"), ("CNY", "EUR"), ("USD", "EUR"), ("EUR", "USD")]
        base_rates = {"USD-CNY": 7.2, "EUR-CNY": 7.8, "GBP-CNY": 9.0, "JPY-CNY": 0.048,
                      "CNY-USD": 0.139, "CNY-EUR": 0.128, "USD-EUR": 0.92, "EUR-USD": 1.09}

        for i in range(NUM_CURRENCY_RATES):
            pair = currency_pairs[i % len(currency_pairs)]
            rate_key = f"{pair[0]}-{pair[1]}"
            base_rate = base_rates.get(rate_key, 1.0)
            conversion_date = random_date(DATA_START_DATE, DATA_END_DATE)
            # Add slight daily fluctuation
            rate = round(base_rate * random.uniform(0.97, 1.03), 6)

            org_id = 1000
            dept_id = 1000

            props = {
                "from_currency": pair[0],
                "to_currency": pair[1],
                "conversion_date": conversion_date,
                "conversion_type": random.choice(["Spot", "Corporate", "User"]),
                "conversion_rate": rate,
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": conversion_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            rate_vid = vid(VID_PREFIX_CURRENCY_RATE, f"{rate_key}-{conversion_date.strftime('%Y%m%d')}-{i}")
            self.writer.write_vertex("CurrencyRate", rate_vid, props)
            self.registry.currency_rates.append(rate_vid)

    def _generate_bank_accounts(self):
        """Generate bank accounts (CE_BANK_ACCOUNTS)."""
        bank_names = ["中国银行", "工商银行", "建设银行", "农业银行", "招商银行",
                       "交通银行", "中信银行", "光大银行", "浦发银行", "民生银行"]
        for i in range(NUM_BANK_ACCOUNTS):
            acct_id = f"BA{str(i+1).zfill(6)}"
            bank_name = bank_names[i % len(bank_names)]
            org_id = 1000 + (i % NUM_ORGANIZATIONS)
            dept_id = 1000

            props = {
                "bank_account_id": acct_id,
                "bank_account_name": f"{bank_name}基本户-{org_id}",
                "bank_account_number": generate_bank_account(),
                "bank_name": bank_name,
                "branch_name": f"{random.choice(CITIES)[0]}分行",
                "currency_code": random.choice(["CNY", "CNY", "CNY", "USD"]),
                "account_type": random.choice(["INTERNAL", "INTERNAL", "SUPPLIER", "CUSTOMER"]),
                "status": "ACTIVE",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": DATA_START_DATE,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            ba_vid = vid(VID_PREFIX_BANK_ACCT, acct_id)
            self.writer.write_vertex("BankAccount", ba_vid, props)
            self.registry.bank_accounts.append(ba_vid)

    def _generate_expense_reports(self):
        """Generate expense reports (AP_EXPENSE_REPORTS_ALL)."""
        purposes = ["出差费用报销", "交通费报销", "招待费报销", "办公用品采购", "培训费报销",
                     "通讯费报销", "住宿费报销", "会议费报销", "差旅补贴"]
        for i in range(NUM_EXPENSE_REPORTS):
            report_number = f"ER{str(i+1).zfill(8)}"
            report_date = random_date(DATA_START_DATE, DATA_END_DATE)
            employee = random.choice(self.registry.employees)
            employee_number = employee.split(":")[1]
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS - 1)
            dept_id = 1000 + random.randint(0, 119)
            total_amount = round(random.uniform(200, 50000), 2)

            submitted_date = report_date + timedelta(days=random.randint(0, 3))
            approved_date = submitted_date + timedelta(days=random.randint(1, 7))
            paid_date = approved_date + timedelta(days=random.randint(3, 15))

            props = {
                "report_number": report_number,
                "report_date": report_date,
                "employee_id": employee_number,
                "total_amount": total_amount,
                "currency": "CNY",
                "status": random.choice(["APPROVED", "APPROVED", "PAID", "PAID", "SUBMITTED", "REJECTED"]),
                "purpose": random.choice(purposes),
                "submitted_date": submitted_date,
                "approved_date": approved_date,
                "paid_date": paid_date if random.random() > 0.3 else None,
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": report_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            exp_vid = vid(VID_PREFIX_EXPENSE, report_number)
            self.writer.write_vertex("ExpenseReport", exp_vid, props)
            self.registry.expense_reports.append(exp_vid)

            # EXPENSE_BY edge
            self.writer.write_edge(
                "EXPENSE_BY",
                exp_vid,
                employee,
                {"org_id": org_id, "dept_id": dept_id}
            )

            # EXPENSE_TO_INVOICE edge (some expense reports generate AP invoices)
            if random.random() > 0.5 and self.registry.invoices:
                invoice_vid = random.choice(self.registry.invoices)
                self.writer.write_edge(
                    "EXPENSE_TO_INVOICE",
                    exp_vid,
                    invoice_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

    def _generate_gl_journal_batches(self):
        """Generate GL journal batches (GL_JE_BATCHES)."""
        for i in range(NUM_GL_JOURNAL_BATCHES):
            batch_id = f"JB{str(i+1).zfill(8)}"
            batch_date = random_date(DATA_START_DATE, DATA_END_DATE)
            period_name = batch_date.strftime("%Y-%m")
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS - 1)
            dept_id = 1000

            props = {
                "batch_id": batch_id,
                "batch_name": f"批次-{batch_id}",
                "status": random.choice(["POSTED", "POSTED", "POSTED", "UNPOSTED", "ERROR"]),
                "default_period_name": period_name,
                "posted_date": batch_date + timedelta(days=random.randint(0, 3)),
                "description": f"日记账批次 {batch_id}",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": batch_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            batch_vid = vid(VID_PREFIX_GL_BATCH, batch_id)
            self.writer.write_vertex("GLJournalBatch", batch_vid, props)
            self.registry.gl_journal_batches.append(batch_vid)

    def _generate_gl_balances(self):
        """Generate GL balances (GL_BALANCES)."""
        if not self.registry.gl_code_combinations or not self.registry.gl_periods:
            return

        # Generate balances for a subset of CCID-Period combinations
        for ccid_vid in random.sample(self.registry.gl_code_combinations,
                                       min(30, len(self.registry.gl_code_combinations))):
            for period_vid in self.registry.gl_periods:
                period_name = period_vid.split(":")[1]
                org_id = 1000
                dept_id = 1000

                net_dr = round(random.uniform(0, 500000), 2)
                net_cr = round(random.uniform(0, 500000), 2)
                begin_dr = round(random.uniform(0, 1000000), 2)
                begin_cr = round(random.uniform(0, 1000000), 2)

                props = {
                    "period_name": period_name,
                    "currency_code": "CNY",
                    "period_net_dr": net_dr,
                    "period_net_cr": net_cr,
                    "begin_balance_dr": begin_dr,
                    "begin_balance_cr": begin_cr,
                    "translated_flag": "N",
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": DATA_START_DATE,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }

                bal_id = f"{ccid_vid.split(':')[1]}-{period_name}"
                bal_vid = vid(VID_PREFIX_GL_BALANCE, bal_id)
                self.writer.write_vertex("GLBalance", bal_vid, props)
                self.registry.gl_balances.append(bal_vid)

                # BALANCE_FOR edge
                self.writer.write_edge(
                    "BALANCE_FOR",
                    bal_vid,
                    ccid_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

                # BALANCE_IN_PERIOD edge
                self.writer.write_edge(
                    "BALANCE_IN_PERIOD",
                    bal_vid,
                    period_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

    def _generate_inventory_transactions(self):
        """Generate inventory transactions (MTL_MATERIAL_TRANSACTIONS)."""
        txn_types = ["RECEIPT", "ISSUE", "TRANSFER", "SUBINVENTORY_TRANSFER",
                     "CYCLE_COUNT", "MISCELLANEOUS_RECEIPT", "MISCELLANEOUS_ISSUE",
                     "RETURN_TO_VENDOR", "DELIVERY"]
        for i in range(NUM_INVENTORY_TXNS):
            txn_id = f"MTXN{str(i+1).zfill(8)}"
            txn_date = random_date(DATA_START_DATE, DATA_END_DATE)
            txn_type = random.choice(txn_types)
            item_vid = random.choice(self.registry.items)
            warehouse = random.choice(self.registry.warehouses)
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS - 1)
            dept_id = 1000 + random.randint(0, 119)

            # Determine source
            source_type = None
            source_id = None
            source_vid = None
            if txn_type == "RECEIPT" and self.registry.receipts:
                source_type = "RECEIVING"
                source_vid = random.choice(self.registry.receipts)
                source_id = source_vid.split(":")[1]
            elif txn_type == "DELIVERY" and self.registry.shipments:
                source_type = "SHIPPING"
                source_vid = random.choice(self.registry.shipments)
                source_id = source_vid.split(":")[1]
            elif txn_type == "RETURN_TO_VENDOR" and self.registry.purchase_orders:
                source_type = "PO"
                source_vid = random.choice(self.registry.purchase_orders)
                source_id = source_vid.split(":")[1]

            qty = round(random.uniform(1, 1000), 2)
            if txn_type in ("ISSUE", "MISCELLANEOUS_ISSUE", "RETURN_TO_VENDOR"):
                qty = -qty  # Negative for outbound

            props = {
                "transaction_id": txn_id,
                "transaction_type": txn_type,
                "transaction_date": txn_date,
                "quantity": qty,
                "uom": random.choice(["EA", "KG", "M", "L", "BOX"]),
                "transaction_cost": round(abs(qty) * random.uniform(5, 500), 2),
                "source_type": source_type or "",
                "source_id": source_id or "",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": txn_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            txn_vid = vid(VID_PREFIX_INV_TXN, txn_id)
            self.writer.write_vertex("InventoryTransaction", txn_vid, props)
            self.registry.inventory_transactions.append(txn_vid)

            # INV_TXN_FOR_ITEM edge
            self.writer.write_edge(
                "INV_TXN_FOR_ITEM",
                txn_vid,
                item_vid,
                {"org_id": org_id, "dept_id": dept_id}
            )

            # INV_TXN_AT edge
            self.writer.write_edge(
                "INV_TXN_AT",
                txn_vid,
                warehouse,
                {"org_id": org_id, "dept_id": dept_id}
            )

            # INV_TXN_SOURCE edge
            if source_vid:
                self.writer.write_edge(
                    "INV_TXN_SOURCE",
                    txn_vid,
                    source_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

    def _generate_bank_statements(self):
        """Generate bank statements and statement lines (CE_STATEMENT_HEADERS/LINES)."""
        line_counter = 0
        for i in range(NUM_BANK_STATEMENTS):
            stmt_id = f"BS{str(i+1).zfill(8)}"
            stmt_date = random_date(DATA_START_DATE, DATA_END_DATE)
            bank_account = random.choice(self.registry.bank_accounts)
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS - 1)
            dept_id = 1000

            opening = round(random.uniform(100000, 5000000), 2)
            closing = round(opening + random.uniform(-200000, 200000), 2)

            props = {
                "statement_id": stmt_id,
                "statement_number": f"STMT-{stmt_date.strftime('%Y%m%d')}-{i+1}",
                "statement_date": stmt_date,
                "opening_balance": opening,
                "closing_balance": closing,
                "status": random.choice(["RECONCILED", "RECONCILED", "UNRECONCILED", "PARTIALLY"]),
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": stmt_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            stmt_vid = vid(VID_PREFIX_BANK_STMT, stmt_id)
            self.writer.write_vertex("BankStatement", stmt_vid, props)
            self.registry.bank_statements.append(stmt_vid)

            # STATEMENT_FOR_ACCOUNT edge
            self.writer.write_edge(
                "STATEMENT_FOR_ACCOUNT",
                stmt_vid,
                bank_account,
                {"org_id": org_id, "dept_id": dept_id}
            )

            # Generate statement lines
            num_lines = random.randint(3, 15)
            for j in range(num_lines):
                line_counter += 1
                line_num = j + 1
                trx_date = stmt_date + timedelta(days=random.randint(0, 1))
                amount = round(random.uniform(-100000, 100000), 2)

                line_props = {
                    "line_number": line_num,
                    "trx_date": trx_date,
                    "trx_type": random.choice(["DEBIT", "CREDIT", "SWEEP", "FEE", "INTEREST"]),
                    "amount": amount,
                    "bank_trx_number": f"BTX{random.randint(100000000, 999999999)}",
                    "status": random.choice(["RECONCILED", "RECONCILED", "UNRECONCILED"]),
                    "reconciled_flag": "Y" if random.random() > 0.3 else "N",
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": trx_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }

                line_vid = vid(VID_PREFIX_BANK_STMT_LINE, f"{stmt_id}-{line_num}")
                self.writer.write_vertex("BankStatementLine", line_vid, line_props)
                self.registry.bank_statement_lines.append(line_vid)

                # HAS_STATEMENT_LINE edge
                self.writer.write_edge(
                    "HAS_STATEMENT_LINE",
                    stmt_vid,
                    line_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

                # RECONCILES_PAYMENT edge (some lines match payments)
                if amount < 0 and random.random() > 0.5 and self.registry.payments:
                    pay_vid = random.choice(self.registry.payments)
                    self.writer.write_edge(
                        "RECONCILES_PAYMENT",
                        line_vid,
                        pay_vid,
                        {"org_id": org_id, "dept_id": dept_id}
                    )

                # RECONCILES_RECEIPT edge (some lines match AR receipts)
                if amount > 0 and random.random() > 0.5 and self.registry.ar_receipts:
                    arr_vid = random.choice(self.registry.ar_receipts)
                    self.writer.write_edge(
                        "RECONCILES_RECEIPT",
                        line_vid,
                        arr_vid,
                        {"org_id": org_id, "dept_id": dept_id}
                    )

    def _get_source_doc_vid(self, doc_type: str, doc_id: str) -> Optional[str]:
        """Get the VID for a source document."""
        prefix_map = {
            "PO": VID_PREFIX_PO,
            "SO": VID_PREFIX_SO,
            "RECEIPT": VID_PREFIX_RECEIPT,
            "INVOICE": VID_PREFIX_INVOICE,
            "PAYMENT": VID_PREFIX_PAYMENT,
            "AR_RECEIPT": VID_PREFIX_AR_RECEIPT,
        }
        prefix = prefix_map.get(doc_type)
        if prefix:
            return vid(prefix, doc_id)
        return None

    def _generate_approval_records(self):
        """Generate approval records for various documents."""
        for i in range(NUM_APPROVAL_RECORDS):
            approval_id = f"APR{str(i+1).zfill(10)}"
            approval_date = random_date(DATA_START_DATE, DATA_END_DATE)

            # Determine document type
            doc_types = ["PO", "PR", "INVOICE", "SO", "CONTRACT"]
            doc_type = random.choice(doc_types)

            # Generate document number based on type
            if doc_type == "PO":
                doc_vid = random.choice(self.registry.purchase_orders) if self.registry.purchase_orders else None
            elif doc_type == "PR":
                doc_vid = random.choice(self.registry.purchase_requisitions) if self.registry.purchase_requisitions else None
            elif doc_type == "INVOICE":
                doc_vid = random.choice(self.registry.invoices) if self.registry.invoices else None
            elif doc_type == "SO":
                doc_vid = random.choice(self.registry.sales_orders) if self.registry.sales_orders else None
            else:
                doc_vid = random.choice(self.registry.contracts) if self.registry.contracts else None

            if not doc_vid:
                continue

            doc_number = doc_vid.split(":")[1]
            approver = random.choice(self.registry.employees)
            approver_number = approver.split(":")[1]
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS-1)
            dept_id = 1000 + random.randint(0, 119)

            props = {
                "approval_id": approval_id,
                "doc_type": doc_type,
                "doc_number": doc_number,
                "approval_action": random.choice(["APPROVE", "APPROVE", "APPROVE", "REJECT", "RETURN"]),
                "approver": approver_number,
                "approval_date": approval_date,
                "comments": random.choice(["同意", "通过", "请加快处理", "符合要求", ""]),
                "approval_level": random.randint(1, 5),
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": approval_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }

            apr_vid = vid(VID_PREFIX_APPROVAL, approval_id)
            self.writer.write_vertex("ApprovalRecord", apr_vid, props)
            self.registry.approvals.append(apr_vid)

            # Write edges
            self.writer.write_edge(
                "APPROVED_BY",
                apr_vid,
                approver,
                {"org_id": org_id, "dept_id": dept_id}
            )

            self.writer.write_edge(
                "APPROVAL_FOR",
                apr_vid,
                doc_vid,
                {"doc_type": doc_type, "org_id": org_id, "dept_id": dept_id}
            )

    # =========================================================================
    # Anomaly Pattern Injection Methods
    # =========================================================================

    def _inject_circular_trading(self):
        """Pattern 1: Inject circular trading — suppliers that are also customers
        with matching PO/SO pairs forming a money loop."""
        groups = [
            ["SUP00001", "SUP00002", "SUP00003"],
            ["SUP00004", "SUP00005", "SUP00006"],
        ]
        total_customers = 0
        total_sos = 0
        total_pos = 0

        for group_idx, sup_numbers in enumerate(groups[:NUM_CIRCULAR_TRADING_GROUPS]):
            shared_bank_account = generate_bank_account()

            for idx, sup_number in enumerate(sup_numbers):
                sup_vid = vid(VID_PREFIX_SUPPLIER, sup_number)

                # Create a matching Customer with same name pattern
                cus_number = f"CUS-CT{group_idx+1}{idx+1:02d}"
                cus_vid = vid(VID_PREFIX_CUSTOMER, cus_number)
                city_info = random.choice(CITIES)
                org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS - 1)
                dept_id = 1000 + random.randint(0, 119)

                cus_props = {
                    "customer_number": cus_number,
                    "customer_name": f"[ANOMALY:CIRCULAR_TRADING] 关联客户-{sup_number}",
                    "customer_type": "CORPORATE",
                    "status": "ACTIVE",
                    "country": "中国",
                    "city": city_info[0],
                    "address": f"{city_info[0]}{city_info[1]}区888号",
                    "contact_person": random_person_name(),
                    "contact_phone": random_phone(),
                    "contact_email": f"contact@circular-{cus_number.lower()}.com",
                    "credit_limit": 5000000,
                    "payment_terms": "NET30",
                    "tax_id": generate_tax_id(),
                    "currency": "CNY",
                    "sales_region": "华东",
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": DATA_END_DATE - timedelta(days=60),
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }
                self.writer.write_vertex("Customer", cus_vid, cus_props)
                self.registry.customers.append(cus_vid)
                total_customers += 1

                # Create the circular PO+SO pair:
                # PO: buy from this supplier
                # SO: sell to the NEXT supplier (as customer)
                next_idx = (idx + 1) % len(sup_numbers)
                next_cus_number = f"CUS-CT{group_idx+1}{next_idx+1:02d}"
                next_cus_vid = vid(VID_PREFIX_CUSTOMER, next_cus_number)

                base_amount = round(random.uniform(200000, 800000), 2)
                base_date = DATA_END_DATE - timedelta(days=random.randint(30, 90))
                item_vid = random.choice(self.registry.items)
                buyer = random.choice(self.registry.employees)

                # -- Create PO (buy from supplier) --
                po_number = f"PO-CT{group_idx+1}{idx+1:02d}01"
                po_vid_str = vid(VID_PREFIX_PO, po_number)
                po_props = {
                    "po_number": po_number,
                    "po_type": "STANDARD",
                    "description": f"[ANOMALY:CIRCULAR_TRADING] 循环交易采购单 G{group_idx+1}",
                    "status": "APPROVED",
                    "buyer": buyer.split(":")[1],
                    "order_date": base_date,
                    "approved_date": base_date + timedelta(hours=2),
                    "total_amount": base_amount,
                    "currency": "CNY",
                    "exchange_rate": 1.0,
                    "payment_terms": "NET30",
                    "freight_terms": "FOB",
                    "ship_to_location": random.choice(self.registry.warehouses).split(":")[1],
                    "bill_to_location": f"ORG{str(org_id % 1000 + 1).zfill(5)}",
                    "close_date": None,
                    "cancel_reason": None,
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": base_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }
                self.writer.write_vertex("PurchaseOrder", po_vid_str, po_props)
                self.registry.purchase_orders.append(po_vid_str)
                self.writer.write_edge("PLACED_WITH", po_vid_str, sup_vid,
                    {"order_date": base_date, "org_id": org_id, "dept_id": dept_id})
                self.writer.write_edge("ORDERED_BY", po_vid_str, buyer,
                    {"org_id": org_id, "dept_id": dept_id})

                # PO line
                pol_vid = vid(VID_PREFIX_PO_LINE, f"{po_number}-1")
                pol_props = {
                    "line_number": 1,
                    "line_type": "GOODS",
                    "quantity": round(base_amount / 100, 2),
                    "unit_price": 100.0,
                    "amount": base_amount,
                    "uom": "EA",
                    "need_by_date": base_date + timedelta(days=30),
                    "promised_date": base_date + timedelta(days=14),
                    "received_quantity": 0,
                    "invoiced_quantity": 0,
                    "status": "OPEN",
                    "tax_code": "TAX13",
                    "tax_rate": 0.13,
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": base_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }
                self.writer.write_vertex("PurchaseOrderLine", pol_vid, pol_props)
                self.writer.write_edge("HAS_PO_LINE", po_vid_str, pol_vid,
                    {"org_id": org_id, "dept_id": dept_id})
                self.writer.write_edge("ORDERS_ITEM", pol_vid, item_vid,
                    {"quantity": pol_props["quantity"], "unit_price": 100.0, "org_id": org_id, "dept_id": dept_id})
                total_pos += 1

                # -- Create SO (sell to next supplier's customer identity) --
                so_number = f"SO-CT{group_idx+1}{idx+1:02d}01"
                so_vid_str = vid(VID_PREFIX_SO, so_number)
                so_amount = base_amount * random.uniform(0.95, 1.05)  # similar amount
                so_date = base_date + timedelta(days=random.randint(-3, 3))
                salesperson = random.choice(self.registry.employees)

                so_props = {
                    "so_number": so_number,
                    "order_type": "STANDARD",
                    "order_date": so_date,
                    "status": "BOOKED",
                    "total_amount": round(so_amount, 2),
                    "currency": "CNY",
                    "exchange_rate": 1.0,
                    "payment_terms": "NET30",
                    "ship_to_address": f"{city_info[0]}市{city_info[1]}区888号",
                    "bill_to_address": f"{city_info[0]}市{city_info[1]}区888号",
                    "salesperson": salesperson.split(":")[1],
                    "requested_date": so_date + timedelta(days=14),
                    "scheduled_date": so_date + timedelta(days=21),
                    "cancel_reason": None,
                    "description": f"[ANOMALY:CIRCULAR_TRADING] 循环交易销售单 G{group_idx+1}",
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": so_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }
                self.writer.write_vertex("SalesOrder", so_vid_str, so_props)
                self.registry.sales_orders.append(so_vid_str)
                self.writer.write_edge("SOLD_TO", so_vid_str, next_cus_vid,
                    {"order_date": so_date, "org_id": org_id, "dept_id": dept_id})

                # SO line
                sol_vid = vid(VID_PREFIX_SO_LINE, f"{so_number}-1")
                sol_props = {
                    "line_number": 1,
                    "quantity": round(so_amount / 100, 2),
                    "unit_price": 100.0,
                    "amount": round(so_amount, 2),
                    "uom": "EA",
                    "shipped_quantity": 0,
                    "invoiced_quantity": 0,
                    "status": "BOOKED",
                    "tax_code": "TAX13",
                    "tax_rate": 0.13,
                    "scheduled_ship_date": so_date + timedelta(days=14),
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": so_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }
                self.writer.write_vertex("SalesOrderLine", sol_vid, sol_props)
                self.writer.write_edge("HAS_SO_LINE", so_vid_str, sol_vid,
                    {"org_id": org_id, "dept_id": dept_id})
                self.writer.write_edge("SELLS_ITEM", sol_vid, item_vid,
                    {"quantity": sol_props["quantity"], "unit_price": 100.0, "org_id": org_id, "dept_id": dept_id})
                total_sos += 1

        print(f"  -> Circular trading: {total_customers} customers, {total_pos} POs, {total_sos} SOs in {NUM_CIRCULAR_TRADING_GROUPS} groups")

    def _inject_split_pos(self):
        """Pattern 2: Inject split POs — multiple POs just below approval threshold
        from same supplier/buyer on same or consecutive days."""
        total_pos = 0

        for group_idx in range(NUM_SPLIT_PO_GROUPS):
            supplier_vid = self.registry.suppliers[10 + group_idx]  # SUP00011, SUP00012, SUP00013
            supplier_number = supplier_vid.split(":")[1]
            buyer = self.registry.employees[group_idx]
            buyer_number = buyer.split(":")[1]
            org_id = 1001
            dept_id = 1001
            base_date = DATA_END_DATE - timedelta(days=random.randint(14, 60))
            num_splits = random.randint(4, 5)

            for split_idx in range(num_splits):
                # Amount just below threshold: 450K-490K
                amount = round(random.uniform(450000, 490000), 2)
                order_date = base_date + timedelta(days=random.randint(0, 1))

                po_number = f"PO-SP{group_idx+1:02d}{split_idx+1:02d}"
                po_vid_str = vid(VID_PREFIX_PO, po_number)

                po_props = {
                    "po_number": po_number,
                    "po_type": "STANDARD",
                    "description": f"[ANOMALY:SPLIT_PO] 拆单规避审批 G{group_idx+1} #{split_idx+1}，合计远超{APPROVAL_THRESHOLD}",
                    "status": "APPROVED",
                    "buyer": buyer_number,
                    "order_date": order_date,
                    "approved_date": order_date + timedelta(hours=1),
                    "total_amount": amount,
                    "currency": "CNY",
                    "exchange_rate": 1.0,
                    "payment_terms": "NET30",
                    "freight_terms": "FOB",
                    "ship_to_location": random.choice(self.registry.warehouses).split(":")[1],
                    "bill_to_location": f"ORG{str(org_id % 1000 + 1).zfill(5)}",
                    "close_date": None,
                    "cancel_reason": None,
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": order_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }
                self.writer.write_vertex("PurchaseOrder", po_vid_str, po_props)
                self.registry.purchase_orders.append(po_vid_str)
                self.writer.write_edge("PLACED_WITH", po_vid_str, supplier_vid,
                    {"order_date": order_date, "org_id": org_id, "dept_id": dept_id})
                self.writer.write_edge("ORDERED_BY", po_vid_str, buyer,
                    {"org_id": org_id, "dept_id": dept_id})

                # PO line
                item_vid = random.choice(self.registry.items)
                qty = round(amount / random.uniform(50, 200), 2)
                unit_price = round(amount / qty, 2)
                pol_vid = vid(VID_PREFIX_PO_LINE, f"{po_number}-1")
                pol_props = {
                    "line_number": 1,
                    "line_type": "GOODS",
                    "quantity": qty,
                    "unit_price": unit_price,
                    "amount": amount,
                    "uom": "EA",
                    "need_by_date": order_date + timedelta(days=30),
                    "promised_date": order_date + timedelta(days=14),
                    "received_quantity": 0,
                    "invoiced_quantity": 0,
                    "status": "OPEN",
                    "tax_code": "TAX13",
                    "tax_rate": 0.13,
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": order_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }
                self.writer.write_vertex("PurchaseOrderLine", pol_vid, pol_props)
                self.writer.write_edge("HAS_PO_LINE", po_vid_str, pol_vid,
                    {"org_id": org_id, "dept_id": dept_id})
                self.writer.write_edge("ORDERS_ITEM", pol_vid, item_vid,
                    {"quantity": qty, "unit_price": unit_price, "org_id": org_id, "dept_id": dept_id})
                total_pos += 1

        print(f"  -> Split POs: {total_pos} POs in {NUM_SPLIT_PO_GROUPS} groups (threshold={APPROVAL_THRESHOLD})")

    def _inject_blocked_supplier_pos(self):
        """Pattern 3: Inject POs to blocked/suspended suppliers."""
        total_pos = 0
        blocked_sup_vids = [vid(VID_PREFIX_SUPPLIER, s) for s in BLOCKED_SUPPLIER_NUMBERS]

        for i in range(NUM_BLOCKED_SUPPLIER_POS):
            supplier_vid = blocked_sup_vids[i % len(blocked_sup_vids)]
            supplier_number = supplier_vid.split(":")[1]
            buyer = random.choice(self.registry.employees)
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS - 1)
            dept_id = 1000 + random.randint(0, 119)

            # Recent date (last 90 days)
            order_date = DATA_END_DATE - timedelta(days=random.randint(1, 90))
            amount = round(random.uniform(50000, 500000), 2)

            po_number = f"PO-BLK{str(i+1).zfill(3)}"
            po_vid_str = vid(VID_PREFIX_PO, po_number)

            po_props = {
                "po_number": po_number,
                "po_type": "STANDARD",
                "description": f"[ANOMALY:BLOCKED_SUPPLIER] 向已停用供应商{supplier_number}采购",
                "status": "APPROVED",
                "buyer": buyer.split(":")[1],
                "order_date": order_date,
                "approved_date": order_date + timedelta(hours=3),
                "total_amount": amount,
                "currency": "CNY",
                "exchange_rate": 1.0,
                "payment_terms": "NET30",
                "freight_terms": "FOB",
                "ship_to_location": random.choice(self.registry.warehouses).split(":")[1],
                "bill_to_location": f"ORG{str(org_id % 1000 + 1).zfill(5)}",
                "close_date": None,
                "cancel_reason": None,
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": order_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("PurchaseOrder", po_vid_str, po_props)
            self.registry.purchase_orders.append(po_vid_str)
            self.writer.write_edge("PLACED_WITH", po_vid_str, supplier_vid,
                {"order_date": order_date, "org_id": org_id, "dept_id": dept_id})
            self.writer.write_edge("ORDERED_BY", po_vid_str, buyer,
                {"org_id": org_id, "dept_id": dept_id})

            # PO line
            item_vid = random.choice(self.registry.items)
            qty = round(amount / random.uniform(50, 500), 2)
            unit_price = round(amount / qty, 2)
            pol_vid = vid(VID_PREFIX_PO_LINE, f"{po_number}-1")
            pol_props = {
                "line_number": 1,
                "line_type": "GOODS",
                "quantity": qty,
                "unit_price": unit_price,
                "amount": amount,
                "uom": "EA",
                "need_by_date": order_date + timedelta(days=30),
                "promised_date": order_date + timedelta(days=14),
                "received_quantity": 0,
                "invoiced_quantity": 0,
                "status": "OPEN",
                "tax_code": "TAX13",
                "tax_rate": 0.13,
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": order_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("PurchaseOrderLine", pol_vid, pol_props)
            self.writer.write_edge("HAS_PO_LINE", po_vid_str, pol_vid,
                {"org_id": org_id, "dept_id": dept_id})
            self.writer.write_edge("ORDERS_ITEM", pol_vid, item_vid,
                {"quantity": qty, "unit_price": unit_price, "org_id": org_id, "dept_id": dept_id})
            total_pos += 1

        print(f"  -> Blocked supplier POs: {total_pos} POs to {len(BLOCKED_SUPPLIER_NUMBERS)} blocked suppliers")

    def _inject_suspicious_bank_changes(self):
        """Pattern 5: Inject suspicious bank account changes before large payments."""
        total_sites = 0
        total_edges = 0

        # Find suppliers with large payments
        supplier_payment_map = {}  # supplier_number -> [(pay_vid, amount, date)]
        for pay_vid, pay_date, org_id, amount, currency in self.registry.payment_details:
            pay_number = pay_vid.split(":")[1]
            inv_numbers = self.registry.payment_to_invoice.get(pay_number, [])
            for inv_num in inv_numbers:
                po_num = self.registry.invoice_to_po.get(inv_num, "")
                sup_num = self.registry.po_to_supplier.get(po_num, "")
                if sup_num and amount > 200000:  # large payment
                    supplier_payment_map.setdefault(sup_num, []).append((pay_vid, amount, pay_date, org_id))

        # Pick suppliers with large payments
        eligible = [(k, v) for k, v in supplier_payment_map.items() if v]
        selected = random.sample(eligible, min(NUM_SUSPICIOUS_BANK_CHANGES, len(eligible)))

        for sup_number, payments in selected:
            # Pick the largest payment
            payments.sort(key=lambda x: x[1], reverse=True)
            pay_vid, pay_amount, pay_date, pay_org_id = payments[0]
            dept_id = 1000 + random.randint(0, 119)

            # Create a new SupplierSite with a new bank account, created 3-7 days before the payment
            site_code = f"SITE-BC{sup_number[3:]}"
            site_vid_str = vid(VID_PREFIX_SUPPLIER_SITE, site_code)
            created_at = pay_date - timedelta(days=random.randint(3, 7))

            site_props = {
                "site_code": site_code,
                "site_name": f"[ANOMALY:BANK_CHANGE] 新银行账户站点-{sup_number}",
                "address": f"新地址-异常变更-{random.randint(1, 999)}号",
                "city": random.choice(CITIES)[0],
                "country": "CN",
                "phone": random_phone(),
                "fax": "",
                "pay_site_flag": "Y",
                "purchasing_site_flag": "N",
                "rfq_site_flag": "N",
                "bank_account_name": "新银行账户",
                "bank_account_number": generate_bank_account(),
                "bank_name": random.choice(["中国银行", "工商银行", "建设银行", "农业银行", "招商银行"]),
                "payment_method": "WIRE",
                "payment_terms": "IMMEDIATE",
                "pay_group": "PRIORITY",
                "status": "ACTIVE",
                "org_id": pay_org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": created_at,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("SupplierSite", site_vid_str, site_props)
            self.registry.supplier_sites.append(site_vid_str)
            total_sites += 1

            # HAS_SUPPLIER_SITE edge
            sup_vid = vid(VID_PREFIX_SUPPLIER, sup_number)
            self.writer.write_edge("HAS_SUPPLIER_SITE", sup_vid, site_vid_str,
                {"org_id": pay_org_id, "dept_id": dept_id})
            total_edges += 1

            # PAID_TO_SITE edge (payment -> new suspicious site)
            self.writer.write_edge("PAID_TO_SITE", pay_vid, site_vid_str,
                {"org_id": pay_org_id, "dept_id": dept_id})
            total_edges += 1

        print(f"  -> Suspicious bank changes: {total_sites} new sites, {total_edges} edges")

    def _inject_supplier_concentration(self):
        """Pattern 6: Inject supplier concentration risk — one supplier dominates
        a category with >60% of supply relationships and POs."""
        total_edges = 0
        total_pos = 0

        if not self.registry.item_categories or not self.registry.item_to_category:
            print("  -> Supplier concentration: skipped (no item categories)")
            return

        # Group items by category
        from collections import defaultdict
        category_items = defaultdict(list)
        for item_vid, cat_vid in self.registry.item_to_category.items():
            category_items[cat_vid].append(item_vid)

        # Pick 2 categories with enough items
        eligible_cats = [(cat, items) for cat, items in category_items.items() if len(items) >= 10]
        if len(eligible_cats) < 2:
            print("  -> Supplier concentration: skipped (not enough eligible categories)")
            return

        selected_cats = random.sample(eligible_cats, 2)

        for cat_vid, cat_items in selected_cats:
            # Pick one dominant supplier
            dominant_supplier = random.choice(self.registry.suppliers[:20])  # from first 20
            dominant_sup_number = dominant_supplier.split(":")[1]
            org_id = 1001
            dept_id = 1001

            # Create concentrated SUPPLIES_ITEM edges — 70-80% of items in this category
            concentrate_count = int(len(cat_items) * random.uniform(0.70, 0.80))
            concentrated_items = random.sample(cat_items, min(concentrate_count, len(cat_items)))

            for item_vid in concentrated_items:
                self.writer.write_edge(
                    "SUPPLIES_ITEM",
                    dominant_supplier,
                    item_vid,
                    {
                        "priority": 1,
                        "unit_price": round(random.uniform(100, 5000), 2),
                        "lead_time_days": random.randint(3, 30),
                        "status": "ACTIVE",
                        "effective_from": DATA_START_DATE,
                        "effective_to": None,
                        "org_id": org_id,
                        "dept_id": dept_id,
                    }
                )
                total_edges += 1

            # Create 15-20 POs to the dominant supplier for items in this category
            num_concentration_pos = random.randint(15, 20)
            buyer = random.choice(self.registry.employees)
            buyer_number = buyer.split(":")[1]

            for po_idx in range(num_concentration_pos):
                item_vid = random.choice(concentrated_items)
                order_date = random_date(DATA_START_DATE + timedelta(days=90), DATA_END_DATE - timedelta(days=7))
                amount = round(random.uniform(50000, 300000), 2)

                po_number = f"PO-SC{cat_vid.split(':')[1][-3:]}{po_idx+1:03d}"
                po_vid_str = vid(VID_PREFIX_PO, po_number)

                po_props = {
                    "po_number": po_number,
                    "po_type": "STANDARD",
                    "description": f"[ANOMALY:SUPPLIER_CONCENTRATION] 品类集中采购-{dominant_sup_number}",
                    "status": "APPROVED",
                    "buyer": buyer_number,
                    "order_date": order_date,
                    "approved_date": order_date + timedelta(hours=2),
                    "total_amount": amount,
                    "currency": "CNY",
                    "exchange_rate": 1.0,
                    "payment_terms": "NET30",
                    "freight_terms": "FOB",
                    "ship_to_location": random.choice(self.registry.warehouses).split(":")[1],
                    "bill_to_location": f"ORG{str(org_id % 1000 + 1).zfill(5)}",
                    "close_date": None,
                    "cancel_reason": None,
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": order_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }
                self.writer.write_vertex("PurchaseOrder", po_vid_str, po_props)
                self.registry.purchase_orders.append(po_vid_str)
                self.writer.write_edge("PLACED_WITH", po_vid_str, dominant_supplier,
                    {"order_date": order_date, "org_id": org_id, "dept_id": dept_id})
                self.writer.write_edge("ORDERED_BY", po_vid_str, buyer,
                    {"org_id": org_id, "dept_id": dept_id})

                # PO line
                qty = round(amount / random.uniform(50, 500), 2)
                unit_price = round(amount / qty, 2)
                pol_vid = vid(VID_PREFIX_PO_LINE, f"{po_number}-1")
                pol_props = {
                    "line_number": 1,
                    "line_type": "GOODS",
                    "quantity": qty,
                    "unit_price": unit_price,
                    "amount": amount,
                    "uom": "EA",
                    "need_by_date": order_date + timedelta(days=30),
                    "promised_date": order_date + timedelta(days=14),
                    "received_quantity": 0,
                    "invoiced_quantity": 0,
                    "status": "OPEN",
                    "tax_code": "TAX13",
                    "tax_rate": 0.13,
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": order_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }
                self.writer.write_vertex("PurchaseOrderLine", pol_vid, pol_props)
                self.writer.write_edge("HAS_PO_LINE", po_vid_str, pol_vid,
                    {"org_id": org_id, "dept_id": dept_id})
                self.writer.write_edge("ORDERS_ITEM", pol_vid, item_vid,
                    {"quantity": qty, "unit_price": unit_price, "org_id": org_id, "dept_id": dept_id})
                total_pos += 1

        print(f"  -> Supplier concentration: {total_edges} SUPPLIES_ITEM edges, {total_pos} POs across 2 categories")

    # =========================================================================
    # OTC Anomaly Patterns (7-9)
    # =========================================================================

    def _inject_ghost_shipments(self):
        """Pattern 7: Channel Stuffing / Ghost Shipments — shipped_quantity far exceeds
        SO line quantity (5-10x), plus shipments with no SO link at all.
        Inspired by Bristol-Myers Squibb $1.5B channel stuffing."""
        total_shipments = 0
        total_lines = 0

        # Pick existing SOs with known line quantities
        so_with_lines = {}
        for key, qty in self.registry.so_line_quantities.items():
            so_number = key.rsplit("-", 1)[0]
            so_with_lines.setdefault(so_number, []).append((key, qty))

        eligible_sos = [s for s in so_with_lines if len(so_with_lines[s]) >= 1]
        selected_sos = random.sample(eligible_sos, min(NUM_GHOST_SHIPMENTS, len(eligible_sos)))

        for idx, so_number in enumerate(selected_sos):
            so_vid = vid(VID_PREFIX_SO, so_number)
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS - 1)
            dept_id = 1000 + random.randint(0, 119)
            shipment_date = random_date(DATA_END_DATE - timedelta(days=90), DATA_END_DATE)
            warehouse = random.choice(self.registry.warehouses)

            shipment_number = f"SHP-GS{str(idx+1).zfill(3)}"
            shp_vid = vid(VID_PREFIX_SHIPMENT, shipment_number)

            # Inflate quantity: 5-10x the SO line quantity
            so_lines = so_with_lines[so_number]
            total_qty = 0
            lines = []
            for line_idx, (line_key, so_qty) in enumerate(so_lines[:3]):
                self._shipment_line_counter += 1
                inflate_factor = random.uniform(5, 10)
                shipped_qty = round(so_qty * inflate_factor, 2)
                total_qty += shipped_qty

                line_props = {
                    "line_number": line_idx + 1,
                    "shipped_quantity": shipped_qty,
                    "uom": "EA",
                    "lot_number": f"LOT{shipment_date.strftime('%Y%m%d')}{random.randint(1000, 9999)}",
                    "serial_number": None,
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": shipment_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }
                line_vid = vid(VID_PREFIX_SHIPMENT_LINE, f"{shipment_number}-{line_idx+1}")
                self.writer.write_vertex("ShipmentLine", line_vid, line_props)
                lines.append(line_vid)
                total_lines += 1

            shp_props = {
                "shipment_number": shipment_number,
                "shipment_date": shipment_date,
                "status": "SHIPPED",
                "carrier": random.choice(["顺丰", "中通", "韵达", "圆通", "德邦"]),
                "tracking_number": f"SF{random.randint(100000000000, 999999999999)}",
                "total_quantity": round(total_qty, 2),
                "warehouse": warehouse.split(":")[1],
                "delivery_date": shipment_date + timedelta(days=random.randint(1, 5)),
                "description": f"[ANOMALY:GHOST_SHIPMENT] 渠道填塞-发货量为订单量的5-10倍",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": shipment_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("Shipment", shp_vid, shp_props)
            self.registry.shipments.append(shp_vid)
            total_shipments += 1

            # Edges
            self.writer.write_edge("HAS_SHIPMENT", so_vid, shp_vid,
                {"org_id": org_id, "dept_id": dept_id})
            for lv in lines:
                self.writer.write_edge("HAS_SHIPMENT_LINE", shp_vid, lv,
                    {"org_id": org_id, "dept_id": dept_id})
            self.writer.write_edge("SHIPPED_FROM", shp_vid, warehouse,
                {"org_id": org_id, "dept_id": dept_id})

        # Create 2 ghost shipments with NO SO link (phantom shipments)
        for ghost_idx in range(2):
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS - 1)
            dept_id = 1000 + random.randint(0, 119)
            shipment_date = random_date(DATA_END_DATE - timedelta(days=60), DATA_END_DATE)
            warehouse = random.choice(self.registry.warehouses)

            shipment_number = f"SHP-PH{str(ghost_idx+1).zfill(3)}"
            shp_vid = vid(VID_PREFIX_SHIPMENT, shipment_number)

            ghost_qty = round(random.uniform(500, 5000), 2)
            self._shipment_line_counter += 1
            line_props = {
                "line_number": 1,
                "shipped_quantity": ghost_qty,
                "uom": "EA",
                "lot_number": f"LOT{shipment_date.strftime('%Y%m%d')}{random.randint(1000, 9999)}",
                "serial_number": None,
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": shipment_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            line_vid = vid(VID_PREFIX_SHIPMENT_LINE, f"{shipment_number}-1")
            self.writer.write_vertex("ShipmentLine", line_vid, line_props)
            total_lines += 1

            shp_props = {
                "shipment_number": shipment_number,
                "shipment_date": shipment_date,
                "status": "SHIPPED",
                "carrier": random.choice(["顺丰", "德邦", "安能"]),
                "tracking_number": f"SF{random.randint(100000000000, 999999999999)}",
                "total_quantity": ghost_qty,
                "warehouse": warehouse.split(":")[1],
                "delivery_date": shipment_date + timedelta(days=random.randint(1, 3)),
                "description": f"[ANOMALY:GHOST_SHIPMENT] 幽灵发货-无关联销售订单",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": shipment_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("Shipment", shp_vid, shp_props)
            self.registry.shipments.append(shp_vid)
            total_shipments += 1

            # Only warehouse edge, NO SO edge (that's the anomaly)
            self.writer.write_edge("HAS_SHIPMENT_LINE", shp_vid, line_vid,
                {"org_id": org_id, "dept_id": dept_id})
            self.writer.write_edge("SHIPPED_FROM", shp_vid, warehouse,
                {"org_id": org_id, "dept_id": dept_id})

        print(f"  -> Ghost shipments: {total_shipments} shipments, {total_lines} lines (including 2 phantom)")

    def _inject_credit_memo_fraud(self):
        """Pattern 9: Credit Memo Fraud — large AR receipt followed by near-equal
        credit memo to same customer within 3-7 days. Cash is pocketed."""
        total_invoices = 0
        total_lines = 0

        if len(self.registry.ar_receipt_details) < NUM_CREDIT_MEMO_FRAUDS:
            print("  -> Credit memo fraud: skipped (not enough AR receipts)")
            return

        # Pick the largest AR receipts
        sorted_receipts = sorted(self.registry.ar_receipt_details, key=lambda x: x[1], reverse=True)
        selected = sorted_receipts[:NUM_CREDIT_MEMO_FRAUDS]

        for idx, (arr_vid, receipt_amount, receipt_date, customer_number) in enumerate(selected):
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS - 1)
            dept_id = 1000 + random.randint(0, 119)

            # Credit memo amount close to receipt amount (85-95%)
            cm_amount = round(receipt_amount * random.uniform(0.85, 0.95), 2)
            cm_date = receipt_date + timedelta(days=random.randint(3, 7))
            invoice_number = f"ARI-CM{str(idx+1).zfill(3)}"
            ari_vid = vid(VID_PREFIX_AR_INVOICE, invoice_number)
            customer_vid = vid(VID_PREFIX_CUSTOMER, customer_number)

            ari_props = {
                "invoice_number": invoice_number,
                "invoice_type": "CREDIT_MEMO",
                "invoice_date": cm_date,
                "due_date": cm_date + timedelta(days=30),
                "status": "OPEN",
                "total_amount": cm_amount,
                "tax_amount": round(cm_amount * 0.13, 2),
                "currency": "CNY",
                "exchange_rate": 1.0,
                "payment_terms": "IMMEDIATE",
                "gl_date": cm_date,
                "description": f"[ANOMALY:CREDIT_MEMO_FRAUD] 收款后{(cm_date - receipt_date).days}天开具贷方凭证-金额{cm_amount:.2f}",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": cm_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("ARInvoice", ari_vid, ari_props)
            self.registry.ar_invoices.append(ari_vid)
            total_invoices += 1

            # AR invoice line
            ar_line_vid = vid(VID_PREFIX_ARI_LINE, f"{invoice_number}-1")
            ar_line_props = {
                "line_number": 1,
                "line_type": "LINE",
                "quantity": 1,
                "unit_selling_price": cm_amount,
                "amount": cm_amount,
                "tax_code": "TAX13",
                "tax_rate": 0.13,
                "description": f"[ANOMALY:CREDIT_MEMO_FRAUD] 贷方凭证行",
                "revenue_amount": round(cm_amount * 0.87, 2),
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": cm_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("ARInvoiceLine", ar_line_vid, ar_line_props)
            self.registry.ar_invoice_lines.append(ar_line_vid)
            total_lines += 1

            # Edges
            self.writer.write_edge("HAS_AR_INVOICE_LINE", ari_vid, ar_line_vid,
                {"org_id": org_id, "dept_id": dept_id})
            # Link credit memo to same customer via BILL_TO edge pattern
            customer_sites = self.registry.customer_to_sites.get(customer_number, [])
            if customer_sites:
                self.writer.write_edge("BILL_TO_SITE", ari_vid, random.choice(customer_sites),
                    {"org_id": org_id, "dept_id": dept_id})

        print(f"  -> Credit memo fraud: {total_invoices} CREDIT_MEMOs, {total_lines} lines")

    # =========================================================================
    # PTP+OTC Cross-Process Fraud Patterns (10-12)
    # =========================================================================

    def _inject_round_tripping(self):
        """Pattern 10: Round-Tripping — buy from supplier A, sell to customer B,
        where A and B share the same bank account/address/phone (same entity).
        Inspired by Autonomy/HP $8.8B write-down, Enron energy trading."""
        total_customers = 0
        total_pos = 0
        total_sos = 0

        # Select suppliers for round-tripping (use SUP00021, SUP00022)
        rt_suppliers = ["SUP00021", "SUP00022"][:NUM_ROUND_TRIP_PAIRS]

        for idx, sup_number in enumerate(rt_suppliers):
            sup_vid = vid(VID_PREFIX_SUPPLIER, sup_number)

            # Get supplier's contact info to create a "hidden" matching customer
            # We need to look up the supplier's properties — use a deterministic approach
            # based on the supplier number to create matching data
            shared_bank_account = generate_bank_account()
            shared_phone = random_phone()
            city_info = random.choice(CITIES)
            shared_address = f"{city_info[0]}{city_info[1]}区{random.randint(100, 999)}号"

            # Update the supplier's bank account to match (write a SupplierSite with this bank account)
            site_code = f"SITE-RT{sup_number[3:]}"
            site_vid = vid(VID_PREFIX_SUPPLIER_SITE, site_code)
            site_props = {
                "site_code": site_code,
                "site_name": f"主营业务站点-{sup_number}",
                "address": shared_address,
                "city": city_info[0],
                "country": "CN",
                "phone": shared_phone,
                "fax": "",
                "pay_site_flag": "Y",
                "purchasing_site_flag": "Y",
                "rfq_site_flag": "N",
                "bank_account_name": "对公账户",
                "bank_account_number": shared_bank_account,
                "bank_name": random.choice(["中国银行", "工商银行", "建设银行"]),
                "payment_method": "WIRE",
                "payment_terms": "NET30",
                "pay_group": "STANDARD",
                "status": "ACTIVE",
                "org_id": 1001,
                "dept_id": 1001,
                "data_scope": "FULL",
                "created_at": DATA_START_DATE,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("SupplierSite", site_vid, site_props)
            self.registry.supplier_sites.append(site_vid)
            self.writer.write_edge("HAS_SUPPLIER_SITE", sup_vid, site_vid,
                {"org_id": 1001, "dept_id": 1001})

            # Create a customer with SAME bank account, phone, address but DIFFERENT name
            # Name is a variant (e.g. "上海XX贸易有限公司" -> "XX商贸（上海）有限公司")
            name_variants = [
                (f"鑫达商贸（{city_info[0]}）有限公司", f"RT-CUS{idx+1:02d}"),
                (f"恒通实业（{city_info[0]}）有限公司", f"RT-CUS{idx+1:02d}"),
            ]
            cus_name, cus_suffix = name_variants[idx % len(name_variants)]
            cus_number = f"CUS-RT{str(idx+1).zfill(3)}"
            cus_vid = vid(VID_PREFIX_CUSTOMER, cus_number)
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS - 1)
            dept_id = 1000 + random.randint(0, 119)

            cus_props = {
                "customer_number": cus_number,
                "customer_name": cus_name,  # Different name, same entity
                "customer_type": "CORPORATE",
                "status": "ACTIVE",
                "country": "中国",
                "city": city_info[0],
                "address": shared_address,           # SAME address as supplier
                "contact_person": random_person_name(),
                "contact_phone": shared_phone,       # SAME phone as supplier
                "contact_email": f"contact@{cus_number.lower()}.com",
                "credit_limit": 5000000,
                "payment_terms": "NET30",
                "tax_id": generate_tax_id(),
                "currency": "CNY",
                "bank_account": shared_bank_account,  # SAME bank account as supplier
                "sales_region": "华东",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": DATA_START_DATE + timedelta(days=random.randint(30, 180)),
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("Customer", cus_vid, cus_props)
            self.registry.customers.append(cus_vid)
            total_customers += 1

            # Create CustomerSite with same bank account
            cs_code = f"CUSS-RT{str(idx+1).zfill(3)}"
            cs_vid = vid(VID_PREFIX_CUSTOMER_SITE, cs_code)
            cs_props = {
                "site_code": cs_code,
                "site_name": f"主营业务站点",
                "site_use": "BILL_TO",
                "address": shared_address,
                "city": city_info[0],
                "country": "CN",
                "phone": shared_phone,
                "bank_account_name": "对公账户",
                "bank_account_number": shared_bank_account,
                "status": "ACTIVE",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": DATA_START_DATE,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("CustomerSite", cs_vid, cs_props)
            self.registry.customer_sites.append(cs_vid)
            self.writer.write_edge("HAS_CUSTOMER_SITE", cus_vid, cs_vid,
                {"org_id": org_id, "dept_id": dept_id})

            # Create PO (buy from supplier) and SO (sell to related customer)
            item_vid = random.choice(self.registry.items)
            buyer = random.choice(self.registry.employees)
            salesperson = random.choice(self.registry.employees)
            base_amount = round(random.uniform(300000, 800000), 2)
            base_date = DATA_END_DATE - timedelta(days=random.randint(30, 90))

            # -- PO: buy item from supplier --
            po_number = f"PO-RT{str(idx+1).zfill(3)}"
            po_vid_str = vid(VID_PREFIX_PO, po_number)
            qty = round(base_amount / random.uniform(100, 500), 2)
            unit_price = round(base_amount / qty, 2)

            po_props = {
                "po_number": po_number,
                "po_type": "STANDARD",
                "description": f"[ANOMALY:ROUND_TRIPPING] 对倒交易采购-{sup_number}",
                "status": "APPROVED",
                "buyer": buyer.split(":")[1],
                "order_date": base_date,
                "approved_date": base_date + timedelta(hours=2),
                "total_amount": base_amount,
                "currency": "CNY",
                "exchange_rate": 1.0,
                "payment_terms": "NET30",
                "freight_terms": "FOB",
                "ship_to_location": random.choice(self.registry.warehouses).split(":")[1],
                "bill_to_location": f"ORG{str(org_id % 1000 + 1).zfill(5)}",
                "close_date": None,
                "cancel_reason": None,
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": base_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("PurchaseOrder", po_vid_str, po_props)
            self.registry.purchase_orders.append(po_vid_str)
            self.writer.write_edge("PLACED_WITH", po_vid_str, sup_vid,
                {"order_date": base_date, "org_id": org_id, "dept_id": dept_id})
            self.writer.write_edge("ORDERED_BY", po_vid_str, buyer,
                {"org_id": org_id, "dept_id": dept_id})

            pol_vid = vid(VID_PREFIX_PO_LINE, f"{po_number}-1")
            pol_props = {
                "line_number": 1, "line_type": "GOODS",
                "quantity": qty, "unit_price": unit_price, "amount": base_amount,
                "uom": "EA", "need_by_date": base_date + timedelta(days=30),
                "promised_date": base_date + timedelta(days=14),
                "received_quantity": 0, "invoiced_quantity": 0, "status": "OPEN",
                "tax_code": "TAX13", "tax_rate": 0.13,
                "org_id": org_id, "dept_id": dept_id, "data_scope": "FULL",
                "created_at": base_date, "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id, "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("PurchaseOrderLine", pol_vid, pol_props)
            self.writer.write_edge("HAS_PO_LINE", po_vid_str, pol_vid,
                {"org_id": org_id, "dept_id": dept_id})
            self.writer.write_edge("ORDERS_ITEM", pol_vid, item_vid,
                {"quantity": qty, "unit_price": unit_price, "org_id": org_id, "dept_id": dept_id})
            total_pos += 1

            # -- SO: sell same item to related customer, similar amount, 3-10 days later --
            so_number = f"SO-RT{str(idx+1).zfill(3)}"
            so_vid_str = vid(VID_PREFIX_SO, so_number)
            so_amount = round(base_amount * random.uniform(0.95, 1.05), 2)
            so_date = base_date + timedelta(days=random.randint(3, 10))

            so_props = {
                "so_number": so_number,
                "order_type": "STANDARD",
                "order_date": so_date,
                "status": "BOOKED",
                "total_amount": so_amount,
                "currency": "CNY",
                "exchange_rate": 1.0,
                "payment_terms": "NET30",
                "ship_to_address": shared_address,
                "bill_to_address": shared_address,
                "salesperson": salesperson.split(":")[1],
                "requested_date": so_date + timedelta(days=14),
                "scheduled_date": so_date + timedelta(days=21),
                "cancel_reason": None,
                "description": f"[ANOMALY:ROUND_TRIPPING] 对倒交易销售-关联客户{cus_number}",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": so_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("SalesOrder", so_vid_str, so_props)
            self.registry.sales_orders.append(so_vid_str)
            self.writer.write_edge("SOLD_TO", so_vid_str, cus_vid,
                {"order_date": so_date, "org_id": org_id, "dept_id": dept_id})

            sol_vid = vid(VID_PREFIX_SO_LINE, f"{so_number}-1")
            so_qty = round(so_amount / unit_price, 2)
            sol_props = {
                "line_number": 1,
                "quantity": so_qty, "unit_price": unit_price,
                "amount": so_amount, "uom": "EA",
                "shipped_quantity": 0, "invoiced_quantity": 0, "status": "BOOKED",
                "tax_code": "TAX13", "tax_rate": 0.13,
                "scheduled_ship_date": so_date + timedelta(days=14),
                "org_id": org_id, "dept_id": dept_id, "data_scope": "FULL",
                "created_at": so_date, "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id, "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("SalesOrderLine", sol_vid, sol_props)
            self.writer.write_edge("HAS_SO_LINE", so_vid_str, sol_vid,
                {"org_id": org_id, "dept_id": dept_id})
            self.writer.write_edge("SELLS_ITEM", sol_vid, item_vid,
                {"quantity": so_qty, "unit_price": unit_price, "org_id": org_id, "dept_id": dept_id})
            total_sos += 1

        print(f"  -> Round-tripping: {total_customers} customers, {total_pos} POs, {total_sos} SOs in {NUM_ROUND_TRIP_PAIRS} pairs")

    def _inject_transfer_pricing(self):
        """Pattern 11: Transfer Pricing (Buy High, Sell Low) — same item purchased at
        price P but sold at 0.5-0.65*P, profits flow to related parties.
        Inspired by Enron SPE transfer pricing, cross-border transfer pricing schemes."""
        total_pos = 0
        total_sos = 0

        selected_items = random.sample(self.registry.items, min(NUM_TRANSFER_PRICING_ITEMS, len(self.registry.items)))

        for item_idx, item_vid in enumerate(selected_items):
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS - 1)
            dept_id = 1000 + random.randint(0, 119)
            city_info = random.choice(CITIES)

            # Base purchase price (high)
            purchase_price = round(random.uniform(500, 5000), 2)
            # Sale price (much lower — 50-65% of purchase price)
            sale_price = round(purchase_price * random.uniform(0.50, 0.65), 2)

            # Create 2-3 POs at purchase_price
            num_po = random.randint(2, 3)
            for po_idx in range(num_po):
                buyer = random.choice(self.registry.employees)
                supplier = random.choice(self.registry.suppliers[:30])
                base_date = random_date(DATA_START_DATE + timedelta(days=90), DATA_END_DATE - timedelta(days=30))
                qty = round(random.uniform(50, 500), 2)
                amount = round(qty * purchase_price, 2)

                po_number = f"PO-TP{item_idx+1:02d}{po_idx+1:02d}"
                po_vid_str = vid(VID_PREFIX_PO, po_number)

                po_props = {
                    "po_number": po_number,
                    "po_type": "STANDARD",
                    "description": f"[ANOMALY:TRANSFER_PRICING] 高价采购-单价{purchase_price}",
                    "status": "APPROVED",
                    "buyer": buyer.split(":")[1],
                    "order_date": base_date,
                    "approved_date": base_date + timedelta(hours=2),
                    "total_amount": amount,
                    "currency": "CNY",
                    "exchange_rate": 1.0,
                    "payment_terms": "NET30",
                    "freight_terms": "FOB",
                    "ship_to_location": random.choice(self.registry.warehouses).split(":")[1],
                    "bill_to_location": f"ORG{str(org_id % 1000 + 1).zfill(5)}",
                    "close_date": None,
                    "cancel_reason": None,
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": base_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }
                self.writer.write_vertex("PurchaseOrder", po_vid_str, po_props)
                self.registry.purchase_orders.append(po_vid_str)
                self.writer.write_edge("PLACED_WITH", po_vid_str, supplier,
                    {"order_date": base_date, "org_id": org_id, "dept_id": dept_id})
                self.writer.write_edge("ORDERED_BY", po_vid_str, buyer,
                    {"org_id": org_id, "dept_id": dept_id})

                pol_vid = vid(VID_PREFIX_PO_LINE, f"{po_number}-1")
                pol_props = {
                    "line_number": 1, "line_type": "GOODS",
                    "quantity": qty, "unit_price": purchase_price, "amount": amount,
                    "uom": "EA", "need_by_date": base_date + timedelta(days=30),
                    "promised_date": base_date + timedelta(days=14),
                    "received_quantity": 0, "invoiced_quantity": 0, "status": "OPEN",
                    "tax_code": "TAX13", "tax_rate": 0.13,
                    "org_id": org_id, "dept_id": dept_id, "data_scope": "FULL",
                    "created_at": base_date, "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id, "source_system": self.source_system,
                    "is_active": True,
                }
                self.writer.write_vertex("PurchaseOrderLine", pol_vid, pol_props)
                self.writer.write_edge("HAS_PO_LINE", po_vid_str, pol_vid,
                    {"org_id": org_id, "dept_id": dept_id})
                self.writer.write_edge("ORDERS_ITEM", pol_vid, item_vid,
                    {"quantity": qty, "unit_price": purchase_price, "org_id": org_id, "dept_id": dept_id})
                total_pos += 1

            # Create 2-3 SOs at sale_price (much lower)
            num_so = random.randint(2, 3)
            for so_idx in range(num_so):
                salesperson = random.choice(self.registry.employees)
                customer = random.choice(self.registry.customers)
                customer_number = customer.split(":")[1]
                so_date = random_date(DATA_START_DATE + timedelta(days=120), DATA_END_DATE - timedelta(days=7))
                so_qty = round(random.uniform(50, 500), 2)
                so_amount = round(so_qty * sale_price, 2)

                so_number = f"SO-TP{item_idx+1:02d}{so_idx+1:02d}"
                so_vid_str = vid(VID_PREFIX_SO, so_number)

                so_props = {
                    "so_number": so_number,
                    "order_type": "STANDARD",
                    "order_date": so_date,
                    "status": "BOOKED",
                    "total_amount": so_amount,
                    "currency": "CNY",
                    "exchange_rate": 1.0,
                    "payment_terms": "NET30",
                    "ship_to_address": f"{city_info[0]}市{random.choice(['朝阳', '海淀', '浦东', '南山'])}区",
                    "bill_to_address": f"{city_info[0]}市{random.choice(['朝阳', '海淀', '浦东', '南山'])}区",
                    "salesperson": salesperson.split(":")[1],
                    "requested_date": so_date + timedelta(days=14),
                    "scheduled_date": so_date + timedelta(days=21),
                    "cancel_reason": None,
                    "description": f"[ANOMALY:TRANSFER_PRICING] 低价销售-单价{sale_price}(采购价{purchase_price})",
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "data_scope": "FULL",
                    "created_at": so_date,
                    "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id,
                    "source_system": self.source_system,
                    "is_active": True,
                }
                self.writer.write_vertex("SalesOrder", so_vid_str, so_props)
                self.registry.sales_orders.append(so_vid_str)
                self.writer.write_edge("SOLD_TO", so_vid_str, customer,
                    {"order_date": so_date, "org_id": org_id, "dept_id": dept_id})

                sol_vid = vid(VID_PREFIX_SO_LINE, f"{so_number}-1")
                sol_props = {
                    "line_number": 1,
                    "quantity": so_qty, "unit_price": sale_price,
                    "amount": so_amount, "uom": "EA",
                    "shipped_quantity": 0, "invoiced_quantity": 0, "status": "BOOKED",
                    "tax_code": "TAX13", "tax_rate": 0.13,
                    "scheduled_ship_date": so_date + timedelta(days=14),
                    "org_id": org_id, "dept_id": dept_id, "data_scope": "FULL",
                    "created_at": so_date, "updated_at": datetime.now(),
                    "etl_batch_id": self.etl_batch_id, "source_system": self.source_system,
                    "is_active": True,
                }
                self.writer.write_vertex("SalesOrderLine", sol_vid, sol_props)
                self.writer.write_edge("HAS_SO_LINE", so_vid_str, sol_vid,
                    {"org_id": org_id, "dept_id": dept_id})
                self.writer.write_edge("SELLS_ITEM", sol_vid, item_vid,
                    {"quantity": so_qty, "unit_price": sale_price, "org_id": org_id, "dept_id": dept_id})
                total_sos += 1

        print(f"  -> Transfer pricing: {total_pos} POs (buy high), {total_sos} SOs (sell low) across {NUM_TRANSFER_PRICING_ITEMS} items")

    def _inject_ship_before_receipt(self):
        """Pattern 12: Ship Before Receipt — items shipped to customers (OTC Shipment)
        before they were received from suppliers (PTP Receipt). Indicates phantom
        inventory or fraudulent transactions."""
        total_pos = 0
        total_sos = 0
        total_receipts = 0
        total_shipments = 0

        selected_items = random.sample(self.registry.items, min(NUM_SHIP_BEFORE_RECEIPT, len(self.registry.items)))

        for item_idx, item_vid in enumerate(selected_items):
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS - 1)
            dept_id = 1000 + random.randint(0, 119)

            # Receipt date is T (later)
            receipt_date = random_date(DATA_END_DATE - timedelta(days=60), DATA_END_DATE - timedelta(days=10))
            # Shipment date is T - 30~60 days (earlier — the anomaly)
            shipment_date = receipt_date - timedelta(days=random.randint(30, 60))

            # -- PO + Receipt (supplier side, received LATE) --
            supplier = random.choice(self.registry.suppliers[:30])
            buyer = random.choice(self.registry.employees)
            qty = round(random.uniform(50, 500), 2)
            unit_price = round(random.uniform(100, 2000), 2)
            amount = round(qty * unit_price, 2)
            po_date = receipt_date - timedelta(days=random.randint(30, 90))

            po_number = f"PO-SBR{str(item_idx+1).zfill(3)}"
            po_vid_str = vid(VID_PREFIX_PO, po_number)
            po_props = {
                "po_number": po_number,
                "po_type": "STANDARD",
                "description": f"[ANOMALY:SHIP_BEFORE_RECEIPT] 先发后收-采购单",
                "status": "APPROVED",
                "buyer": buyer.split(":")[1],
                "order_date": po_date,
                "approved_date": po_date + timedelta(hours=2),
                "total_amount": amount,
                "currency": "CNY",
                "exchange_rate": 1.0,
                "payment_terms": "NET30",
                "freight_terms": "FOB",
                "ship_to_location": random.choice(self.registry.warehouses).split(":")[1],
                "bill_to_location": f"ORG{str(org_id % 1000 + 1).zfill(5)}",
                "close_date": None,
                "cancel_reason": None,
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": po_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("PurchaseOrder", po_vid_str, po_props)
            self.registry.purchase_orders.append(po_vid_str)
            self.writer.write_edge("PLACED_WITH", po_vid_str, supplier,
                {"order_date": po_date, "org_id": org_id, "dept_id": dept_id})
            self.writer.write_edge("ORDERED_BY", po_vid_str, buyer,
                {"org_id": org_id, "dept_id": dept_id})

            pol_vid = vid(VID_PREFIX_PO_LINE, f"{po_number}-1")
            pol_props = {
                "line_number": 1, "line_type": "GOODS",
                "quantity": qty, "unit_price": unit_price, "amount": amount,
                "uom": "EA", "need_by_date": po_date + timedelta(days=60),
                "promised_date": po_date + timedelta(days=45),
                "received_quantity": qty, "invoiced_quantity": 0, "status": "CLOSED",
                "tax_code": "TAX13", "tax_rate": 0.13,
                "org_id": org_id, "dept_id": dept_id, "data_scope": "FULL",
                "created_at": po_date, "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id, "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("PurchaseOrderLine", pol_vid, pol_props)
            self.writer.write_edge("HAS_PO_LINE", po_vid_str, pol_vid,
                {"org_id": org_id, "dept_id": dept_id})
            self.writer.write_edge("ORDERS_ITEM", pol_vid, item_vid,
                {"quantity": qty, "unit_price": unit_price, "org_id": org_id, "dept_id": dept_id})
            total_pos += 1

            # Receipt (received LATE at receipt_date)
            warehouse = random.choice(self.registry.warehouses)
            rcv_number = f"RCV-SBR{str(item_idx+1).zfill(3)}"
            rcv_vid = vid(VID_PREFIX_RECEIPT, rcv_number)
            rcv_props = {
                "receipt_number": rcv_number,
                "receipt_type": "PO_RECEIPT",
                "receipt_date": receipt_date,
                "status": "COMPLETED",
                "receiver": random.choice(self.registry.employees).split(":")[1],
                "total_quantity": qty,
                "warehouse": warehouse.split(":")[1],
                "comments": f"[ANOMALY:SHIP_BEFORE_RECEIPT] 收货日期{receipt_date.strftime('%Y-%m-%d')}，但物料已在{shipment_date.strftime('%Y-%m-%d')}发给客户",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": receipt_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("Receipt", rcv_vid, rcv_props)
            self.registry.receipts.append(rcv_vid)
            self.writer.write_edge("HAS_RECEIPT", po_vid_str, rcv_vid,
                {"org_id": org_id, "dept_id": dept_id})
            self.writer.write_edge("RECEIVED_AT", rcv_vid, warehouse,
                {"org_id": org_id, "dept_id": dept_id})

            # Receipt line
            rcvl_vid = vid(VID_PREFIX_RECEIPT_LINE, f"{rcv_number}-1")
            rcvl_props = {
                "line_number": 1,
                "received_quantity": qty,
                "accepted_quantity": qty,
                "rejected_quantity": 0,
                "uom": "EA",
                "inspection_status": "PASSED",
                "lot_number": f"LOT{receipt_date.strftime('%Y%m%d')}{random.randint(1000, 9999)}",
                "sublocation": f"SL{random.randint(1, 50):02d}",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": receipt_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("ReceiptLine", rcvl_vid, rcvl_props)
            self.writer.write_edge("HAS_RECEIPT_LINE", rcv_vid, rcvl_vid,
                {"org_id": org_id, "dept_id": dept_id})
            total_receipts += 1

            # -- SO + Shipment (customer side, shipped EARLY — before receipt) --
            customer = random.choice(self.registry.customers)
            customer_number = customer.split(":")[1]
            salesperson = random.choice(self.registry.employees)
            so_date = shipment_date - timedelta(days=random.randint(7, 14))
            so_amount = round(qty * unit_price * random.uniform(1.1, 1.3), 2)

            so_number = f"SO-SBR{str(item_idx+1).zfill(3)}"
            so_vid_str = vid(VID_PREFIX_SO, so_number)
            so_props = {
                "so_number": so_number,
                "order_type": "STANDARD",
                "order_date": so_date,
                "status": "BOOKED",
                "total_amount": so_amount,
                "currency": "CNY",
                "exchange_rate": 1.0,
                "payment_terms": "NET30",
                "ship_to_address": f"{random.choice(['北京', '上海', '广州'])}市",
                "bill_to_address": f"{random.choice(['北京', '上海', '广州'])}市",
                "salesperson": salesperson.split(":")[1],
                "requested_date": so_date + timedelta(days=14),
                "scheduled_date": so_date + timedelta(days=21),
                "cancel_reason": None,
                "description": f"[ANOMALY:SHIP_BEFORE_RECEIPT] 先发后收-销售单",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": so_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("SalesOrder", so_vid_str, so_props)
            self.registry.sales_orders.append(so_vid_str)
            self.writer.write_edge("SOLD_TO", so_vid_str, customer,
                {"order_date": so_date, "org_id": org_id, "dept_id": dept_id})

            sol_vid = vid(VID_PREFIX_SO_LINE, f"{so_number}-1")
            sol_props = {
                "line_number": 1,
                "quantity": qty, "unit_price": round(so_amount / qty, 2),
                "amount": so_amount, "uom": "EA",
                "shipped_quantity": qty, "invoiced_quantity": 0, "status": "SHIPPED",
                "tax_code": "TAX13", "tax_rate": 0.13,
                "scheduled_ship_date": shipment_date,
                "org_id": org_id, "dept_id": dept_id, "data_scope": "FULL",
                "created_at": so_date, "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id, "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("SalesOrderLine", sol_vid, sol_props)
            self.writer.write_edge("HAS_SO_LINE", so_vid_str, sol_vid,
                {"org_id": org_id, "dept_id": dept_id})
            self.writer.write_edge("SELLS_ITEM", sol_vid, item_vid,
                {"quantity": qty, "unit_price": round(so_amount / qty, 2), "org_id": org_id, "dept_id": dept_id})
            total_sos += 1

            # Shipment (shipped EARLY at shipment_date — before receipt_date)
            shp_warehouse = random.choice(self.registry.warehouses)
            shp_number = f"SHP-SBR{str(item_idx+1).zfill(3)}"
            shp_vid = vid(VID_PREFIX_SHIPMENT, shp_number)
            shp_props = {
                "shipment_number": shp_number,
                "shipment_date": shipment_date,
                "status": "SHIPPED",
                "carrier": random.choice(["顺丰", "中通", "韵达", "德邦"]),
                "tracking_number": f"SF{random.randint(100000000000, 999999999999)}",
                "total_quantity": qty,
                "warehouse": shp_warehouse.split(":")[1],
                "delivery_date": shipment_date + timedelta(days=random.randint(1, 5)),
                "description": f"[ANOMALY:SHIP_BEFORE_RECEIPT] 发货日{shipment_date.strftime('%Y-%m-%d')}早于收货日{receipt_date.strftime('%Y-%m-%d')}",
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": shipment_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("Shipment", shp_vid, shp_props)
            self.registry.shipments.append(shp_vid)
            self.writer.write_edge("HAS_SHIPMENT", so_vid_str, shp_vid,
                {"org_id": org_id, "dept_id": dept_id})
            self.writer.write_edge("SHIPPED_FROM", shp_vid, shp_warehouse,
                {"org_id": org_id, "dept_id": dept_id})

            # Shipment line
            shpl_vid = vid(VID_PREFIX_SHIPMENT_LINE, f"{shp_number}-1")
            shpl_props = {
                "line_number": 1,
                "shipped_quantity": qty,
                "uom": "EA",
                "lot_number": f"LOT{shipment_date.strftime('%Y%m%d')}{random.randint(1000, 9999)}",
                "serial_number": None,
                "org_id": org_id,
                "dept_id": dept_id,
                "data_scope": "FULL",
                "created_at": shipment_date,
                "updated_at": datetime.now(),
                "etl_batch_id": self.etl_batch_id,
                "source_system": self.source_system,
                "is_active": True,
            }
            self.writer.write_vertex("ShipmentLine", shpl_vid, shpl_props)
            self.writer.write_edge("HAS_SHIPMENT_LINE", shp_vid, shpl_vid,
                {"org_id": org_id, "dept_id": dept_id})
            total_shipments += 1

        print(f"  -> Ship before receipt: {total_pos} POs, {total_receipts} Receipts, {total_sos} SOs, {total_shipments} Shipments across {NUM_SHIP_BEFORE_RECEIPT} items")


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    """Main entry point for test data generation."""
    parser = argparse.ArgumentParser(
        description="HoneyBadge Phase 1 Test Data Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/generate_test_data.py                          # Generate with defaults
  python scripts/generate_test_data.py --output-dir ./data      # Custom output directory
  python scripts/generate_test_data.py --seed 12345             # Custom random seed
        """
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "deploy" / "test-data",
        help="Output directory for CSV files (default: deploy/test-data)"
    )
    parser.add_argument(
        "--seed", "-s",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)"
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=BATCH_SIZE,
        help=f"Records per CSV file (default: {BATCH_SIZE})"
    )

    args = parser.parse_args()

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Generate data
    generator = TestDataGenerator(args.output_dir, seed=args.seed)
    generator.generate_all()
    generator.close()  # Flush remaining buffered records

    print(f"\nGeneration complete. Files written to: {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
