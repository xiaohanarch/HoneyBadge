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

# Scaled entity counts for 700K vertex / 1M edge target
NUM_SUPPLIERS = 400
NUM_CUSTOMERS = 320
NUM_ITEMS = 2000
NUM_ORGANIZATIONS = 40
NUM_EMPLOYEES = 200
NUM_WAREHOUSES = 20
NUM_GL_ACCOUNTS = 120
NUM_CURRENCIES = 32
NUM_UOMS = 60

# Transaction counts (further scaled to reach ~700K vertices / ~1M edges)
# Key boost: GL_JOURNAL_ENTRIES drives GLJournalLine which is the largest vertex pool
NUM_PURCHASE_REQUISITIONS = 4000
NUM_PURCHASE_ORDERS = 13000
NUM_RECEIPTS = 11000
NUM_INVOICES = 13000
NUM_PAYMENTS = 8000
NUM_SALES_ORDERS = 8000
NUM_SHIPMENTS = 7200
NUM_AR_INVOICES = 6000
NUM_AR_RECEIPTS = 4000
NUM_GL_JOURNAL_ENTRIES = 40000
NUM_XLA_EVENTS = 24000
NUM_APPROVAL_RECORDS = 20000
NUM_CONTRACTS = 800
NUM_BOMS = 200

# Anomaly rates (realistic noisy data)
THREE_WAY_MATCH_FAILURE_RATE = 0.05  # 5%
TEMPORAL_VIOLATION_RATE = 0.03  # 3%
DUPLICATE_INVOICE_RATE = 0.015  # 1.5%
EXPIRED_QUALIFICATION_RATE = 0.10  # 10% of suppliers

# Time range for data (24 months)
DATA_START_DATE = datetime(2024, 4, 1)
DATA_END_DATE = datetime(2026, 4, 1)

# Output configuration
BATCH_SIZE = 5000  # Increased from 50 for better I/O performance with large datasets

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

    # Three-way match tracking for anomaly injection
    invoice_amount_by_po_line: dict[str, float] = field(default_factory=dict)
    receipt_amount_by_po_line: dict[str, float] = field(default_factory=dict)


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

        print("[1/16] Generating master data (Organizations, Employees, Warehouses)...")
        self._generate_organizations()
        self._generate_employees()
        self._generate_warehouses()
        self._generate_gl_accounts()
        self._generate_currencies()
        self._generate_uoms()

        print("[2/16] Generating Items and BOMs...")
        self._generate_items()
        self._generate_boms()

        print("[3/16] Generating Suppliers...")
        self._generate_suppliers()

        print("[4/16] Generating Customers...")
        self._generate_customers()

        print("[5/16] Generating Contracts...")
        self._generate_contracts()

        print("[6/16] Generating Purchase Requisitions...")
        self._generate_purchase_requisitions()

        print("[7/16] Generating Purchase Orders...")
        self._generate_purchase_orders()

        print("[8/16] Generating Receipts...")
        self._generate_receipts()

        print("[9/16] Generating Invoices (with 5% three-way match failures)...")
        self._generate_invoices()

        print("[9/16] Generating Payments...")
        self._generate_payments()

        print("[10/16] Generating Payment Batches...")
        self._generate_payment_batches()

        print("[11/16] Generating Sales Orders...")
        self._generate_sales_orders()

        print("[12/16] Generating Shipments...")
        self._generate_shipments()

        print("[13/16] Generating AR Invoices...")
        self._generate_ar_invoices()

        print("[14/16] Generating AR Receipts...")
        self._generate_ar_receipts()

        print("[15/16] Generating GL Journal Entries and XLA Events...")
        self._generate_gl_journal_entries()
        self._generate_xla_events()

        print("[16/16] Generating Approval Records...")
        self._generate_approval_records()

        # Final flush
        self.writer.flush_all()

        print()
        print("=" * 60)
        print("Data Generation Summary")
        print("=" * 60)
        print(f"Suppliers:        {len(self.registry.suppliers)}")
        print(f"Customers:        {len(self.registry.customers)}")
        print(f"Items:            {len(self.registry.items)}")
        print(f"Organizations:    {len(self.registry.organizations)}")
        print(f"Employees:        {len(self.registry.employees)}")
        print(f"Warehouses:       {len(self.registry.warehouses)}")
        print(f"GL Accounts:      {len(self.registry.gl_accounts)}")
        print(f"BOMs:             {len(self.registry.boms)}")
        print(f"Contracts:        {len(self.registry.contracts)}")
        print(f"Purchase Reqs:    {len(self.registry.purchase_requisitions)}")
        print(f"Purchase Orders:  {len(self.registry.purchase_orders)}")
        print(f"Receipts:         {len(self.registry.receipts)}")
        print(f"Invoices:         {len(self.registry.invoices)}")
        print(f"Payments:         {len(self.registry.payments)}")
        print(f"Payment Batches:  {len(self.registry.payment_batches)}")
        print(f"Sales Orders:     {len(self.registry.sales_orders)}")
        print(f"Shipments:        {len(self.registry.shipments)}")
        print(f"AR Invoices:      {len(self.registry.ar_invoices)}")
        print(f"AR Receipts:      {len(self.registry.ar_receipts)}")
        print(f"GL Entries:       {len(self.registry.gl_journal_entries)}")
        print(f"XLA Events:       {len(self.registry.xla_events)}")
        print(f"Approval Records: {len(self.registry.approvals)}")
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

            # Link to a PO
            po_number = random.choice(self.registry.purchase_orders).split(":")[1]
            po_vid = vid(VID_PREFIX_PO, po_number)
            supplier = vid(VID_PREFIX_SUPPLIER, self.registry.po_to_supplier[po_number])
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS-1)
            dept_id = 1000 + random.randint(0, 119)

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
                "description": f"供应商发票 {invoice_number}",
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

            inv_vid = vid(VID_PREFIX_INVOICE, invoice_number)
            self.writer.write_vertex("Invoice", inv_vid, props)
            self.registry.invoices.append(inv_vid)

            # Track invoice -> PO mapping
            self.registry.invoice_to_po[invoice_number] = po_number

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

            for line_vid in invoice_lines:
                self.writer.write_edge(
                    "HAS_INVOICE_LINE",
                    inv_vid,
                    line_vid,
                    {"org_id": org_id, "dept_id": dept_id}
                )

    def _generate_payments(self):
        """Generate payments linked to invoices."""
        for i in range(NUM_PAYMENTS):
            payment_number = f"PAY{str(i+1).zfill(8)}"
            payment_date = random_date(DATA_START_DATE + timedelta(days=60), DATA_END_DATE)

            # Link to an invoice
            invoice_vid = random.choice(self.registry.invoices)
            invoice_number = invoice_vid.split(":")[1]
            invoice_po = self.registry.invoice_to_po.get(invoice_number, "")
            supplier_number = self.registry.po_to_supplier.get(invoice_po, "SUP00001")
            supplier_vid = vid(VID_PREFIX_SUPPLIER, supplier_number)
            org_id = 1000 + random.randint(0, NUM_ORGANIZATIONS-1)
            dept_id = 1000 + random.randint(0, 119)

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
