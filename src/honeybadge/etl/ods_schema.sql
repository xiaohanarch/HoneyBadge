-- ============================================================================
-- HoneyBadge ETL - ODS Layer DDL
-- Version: v1.0
-- Date: 2026-04-04
-- Description: ODS (Operational Data Store) table definitions for ETL pipeline
--              Data flows from ERP source systems to ODS, then through quality
--              checks and graph transformation into NebulaGraph.
-- ============================================================================

-- Standard ETL columns for all ODS tables
-- etl_batch_id    : ETL batch identifier (e.g., ETL-20260404-001)
-- etl_load_time   : Timestamp when ETL loaded this record
-- source_system   : Source ERP system (EBS / CUSTOM_ERP)
-- source_update_time: Last update time in source system
-- is_deleted      : Soft delete flag from source system
-- dq_status       : Data quality status (pending/passed/failed/quarantined)
-- dq_errors       : JSONB field for quality check error details

-- ============================================================================
-- ETL Metadata Tables
-- ============================================================================

-- ETL run log - tracks pipeline execution status
CREATE TABLE IF NOT EXISTS etl_run_log (
    id                  BIGSERIAL PRIMARY KEY,
    batch_id            VARCHAR(64) NOT NULL UNIQUE,
    status              VARCHAR(20) NOT NULL,  -- running/success/failed/partial
    load_mode           VARCHAR(10) NOT NULL,   -- full/incremental
    start_time          TIMESTAMP NOT NULL,
    end_time            TIMESTAMP,
    total_records       BIGINT,
    passed_records      BIGINT,
    failed_records      BIGINT,
    quarantined         BIGINT,
    import_duration_sec INTEGER,
    error_summary       JSONB,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_run_log_batch ON etl_run_log(batch_id);
CREATE INDEX IF NOT EXISTS idx_run_log_status ON etl_run_log(status);
CREATE INDEX IF NOT EXISTS idx_run_log_start ON etl_run_log(start_time DESC);

-- ETL quarantine - stores records that failed quality checks
CREATE TABLE IF NOT EXISTS etl_quarantine (
    id                  BIGSERIAL PRIMARY KEY,
    batch_id            VARCHAR(64) NOT NULL,
    source_table        VARCHAR(64) NOT NULL,
    source_id           VARCHAR(128),          -- Source record primary key
    error_type          VARCHAR(30) NOT NULL,  -- null_check/type_check/ref_integrity/business_rule
    error_detail        JSONB NOT NULL,
    severity            VARCHAR(10) NOT NULL,  -- warning/critical
    resolved            BOOLEAN DEFAULT false,
    resolved_by         VARCHAR(64),
    resolved_at         TIMESTAMP,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quarantine_batch ON etl_quarantine(batch_id);
CREATE INDEX IF NOT EXISTS idx_quarantine_unresolved ON etl_quarantine(resolved, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quarantine_source ON etl_quarantine(source_table, source_id);

-- ETL sync status - marks completion of source system sync (for polling mode)
CREATE TABLE IF NOT EXISTS etl_sync_status (
    id                  BIGSERIAL PRIMARY KEY,
    batch_id            VARCHAR(64) NOT NULL UNIQUE,
    tables              TEXT[] NOT NULL,        -- Array of synced table names
    source_system       VARCHAR(30) NOT NULL,
    sync_start_time     TIMESTAMP NOT NULL,
    sync_end_time       TIMESTAMP NOT NULL,
    record_counts       JSONB,                 -- {"ods_supplier": 1000, ...}
    status              VARCHAR(20) NOT NULL,  -- syncing/completed/failed
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sync_status_batch ON etl_sync_status(batch_id);
CREATE INDEX IF NOT EXISTS idx_sync_status_system ON etl_sync_status(source_system, status);

-- ============================================================================
-- Master Data ODS Tables
-- ============================================================================

-- Supplier (供应商)
CREATE TABLE IF NOT EXISTS ods_supplier (
    vendor_id           BIGINT NOT NULL,
    vendor_number       VARCHAR(50) NOT NULL,
    vendor_name         VARCHAR(200) NOT NULL,
    vendor_type         VARCHAR(30),           -- MANUFACTURER/DISTRIBUTOR/SERVICE_PROVIDER
    status              VARCHAR(20),           -- ACTIVE/INACTIVE/BLOCKED/PENDING
    country             VARCHAR(60),
    city                VARCHAR(60),
    address             VARCHAR(500),
    contact_person      VARCHAR(100),
    contact_phone       VARCHAR(50),
    contact_email       VARCHAR(100),
    bank_account        VARCHAR(50),
    bank_name           VARCHAR(100),
    vat_registration_num VARCHAR(50),         -- Tax ID
    payment_terms       VARCHAR(50),
    credit_rating       VARCHAR(10),
    start_date          TIMESTAMP,
    end_date            TIMESTAMP,
    org_id              BIGINT,

    -- Standard ETL columns
    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_supplier_batch ON ods_supplier(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_supplier_number ON ods_supplier(vendor_number);
CREATE INDEX IF NOT EXISTS idx_ods_supplier_dq ON ods_supplier(dq_status);
CREATE INDEX IF NOT EXISTS idx_ods_supplier_org ON ods_supplier(org_id);

-- Supplier Site (供应商地点)
CREATE TABLE IF NOT EXISTS ods_supplier_site (
    vendor_site_id      BIGINT NOT NULL,
    vendor_id           BIGINT NOT NULL,
    site_code           VARCHAR(50) NOT NULL,
    site_name           VARCHAR(200),
    address             VARCHAR(500),
    city                VARCHAR(60),
    state               VARCHAR(60),
    country             VARCHAR(60),
    zip_code            VARCHAR(20),
    contact_person      VARCHAR(100),
    contact_phone       VARCHAR(50),
    contact_email       VARCHAR(100),
    payment_terms       VARCHAR(50),
   org_id               BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_supplier_site_batch ON ods_supplier_site(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_supplier_site_vendor ON ods_supplier_site(vendor_id);
CREATE INDEX IF NOT EXISTS idx_ods_supplier_site_dq ON ods_supplier_site(dq_status);

-- Customer (客户)
CREATE TABLE IF NOT EXISTS ods_customer (
    customer_id         BIGINT NOT NULL,
    customer_number     VARCHAR(50) NOT NULL,
    customer_name       VARCHAR(200) NOT NULL,
    customer_type       VARCHAR(30),           -- INTERNAL/EXTERNAL/GOVERNMENT
    status              VARCHAR(20),
    country             VARCHAR(60),
    city                VARCHAR(60),
    address             VARCHAR(500),
    contact_person      VARCHAR(100),
    contact_phone       VARCHAR(50),
    contact_email       VARCHAR(100),
    credit_limit        NUMERIC(18,2),
    payment_terms       VARCHAR(50),
    tax_id              VARCHAR(50),
    currency            VARCHAR(10) DEFAULT 'CNY',
    sales_region        VARCHAR(50),
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_customer_batch ON ods_customer(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_customer_number ON ods_customer(customer_number);
CREATE INDEX IF NOT EXISTS idx_ods_customer_dq ON ods_customer(dq_status);
CREATE INDEX IF NOT EXISTS idx_ods_customer_org ON ods_customer(org_id);

-- Customer Site (客户地点)
CREATE TABLE IF NOT EXISTS ods_customer_site (
    cust_site_id        BIGINT NOT NULL,
    customer_id         BIGINT NOT NULL,
    site_code           VARCHAR(50) NOT NULL,
    site_name           VARCHAR(200),
    address             VARCHAR(500),
    city                VARCHAR(60),
    state               VARCHAR(60),
    country             VARCHAR(60),
    zip_code            VARCHAR(20),
    contact_person      VARCHAR(100),
    contact_phone       VARCHAR(50),
    contact_email       VARCHAR(100),
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_customer_site_batch ON ods_customer_site(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_customer_site_customer ON ods_customer_site(customer_id);
CREATE INDEX IF NOT EXISTS idx_ods_customer_site_dq ON ods_customer_site(dq_status);

-- Item (物料)
CREATE TABLE IF NOT EXISTS ods_item (
    inventory_item_id   BIGINT NOT NULL,
    item_number         VARCHAR(50) NOT NULL,
    item_name           VARCHAR(200) NOT NULL,
    item_description    VARCHAR(500),
    item_type           VARCHAR(30),           -- RAW_MATERIAL/FINISHED_GOOD/SEMI_FINISHED/SERVICE/EXPENSE
    category            VARCHAR(100),
    uom                 VARCHAR(20),           -- EA/KG/M/L
    standard_cost       NUMERIC(18,4),
    list_price          NUMERIC(18,4),
    weight              NUMERIC(18,4),
    weight_uom          VARCHAR(20),
    lead_time_days      INTEGER,
    safety_stock        NUMERIC(18,4),
    min_order_qty       NUMERIC(18,4),
    status              VARCHAR(20),           -- ACTIVE/INACTIVE/OBSOLETE
    abc_class           VARCHAR(10),           -- A/B/C
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_item_batch ON ods_item(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_item_number ON ods_item(item_number);
CREATE INDEX IF NOT EXISTS idx_ods_item_dq ON ods_item(dq_status);
CREATE INDEX IF NOT EXISTS idx_ods_item_org ON ods_item(org_id);

-- Item Category (物料分类)
CREATE TABLE IF NOT EXISTS ods_item_category (
    category_id        BIGINT NOT NULL,
    category_code      VARCHAR(50) NOT NULL,
    category_name      VARCHAR(200) NOT NULL,
    parent_category_id  BIGINT,
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_item_category_batch ON ods_item_category(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_item_category_code ON ods_item_category(category_code);

-- Organization (组织)
CREATE TABLE IF NOT EXISTS ods_organization (
    org_id              BIGINT NOT NULL,
    org_code            VARCHAR(50) NOT NULL,
    org_name            VARCHAR(200) NOT NULL,
    org_type            VARCHAR(30),           -- COMPANY/BUSINESS_UNIT/DEPARTMENT/COST_CENTER
    parent_org_id       BIGINT,
    legal_entity        VARCHAR(200),
    country             VARCHAR(60),
    city                VARCHAR(60),
    status              VARCHAR(20),

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_org_batch ON ods_organization(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_org_code ON ods_organization(org_code);
CREATE INDEX IF NOT EXISTS idx_ods_org_dq ON ods_organization(dq_status);

-- Employee (员工)
CREATE TABLE IF NOT EXISTS ods_employee (
    employee_id         BIGINT NOT NULL,
    employee_number     VARCHAR(50) NOT NULL,
    employee_name       VARCHAR(100) NOT NULL,
    position            VARCHAR(100),
    department          VARCHAR(100),
    email               VARCHAR(100),
    phone               VARCHAR(50),
    manager_id          BIGINT,
    hire_date           TIMESTAMP,
    status              VARCHAR(20),
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_employee_batch ON ods_employee(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_employee_number ON ods_employee(employee_number);
CREATE INDEX IF NOT EXISTS idx_ods_employee_dq ON ods_employee(dq_status);
CREATE INDEX IF NOT EXISTS idx_ods_employee_org ON ods_employee(org_id);

-- Warehouse (仓库)
CREATE TABLE IF NOT EXISTS ods_warehouse (
    warehouse_id        BIGINT NOT NULL,
    warehouse_code      VARCHAR(50) NOT NULL,
    warehouse_name      VARCHAR(200) NOT NULL,
    warehouse_type      VARCHAR(30),           -- MAIN/SUB/TRANSIT/RETURN
    location            VARCHAR(200),
    capacity            NUMERIC(18,2),
    status              VARCHAR(20),
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_warehouse_batch ON ods_warehouse(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_warehouse_code ON ods_warehouse(warehouse_code);
CREATE INDEX IF NOT EXISTS idx_ods_warehouse_dq ON ods_warehouse(dq_status);
CREATE INDEX IF NOT EXISTS idx_ods_warehouse_org ON ods_warehouse(org_id);

-- BOM Header (物料清单头)
CREATE TABLE IF NOT EXISTS ods_bom_header (
    bom_id              BIGINT NOT NULL,
    bom_number          VARCHAR(50) NOT NULL,
    bom_name            VARCHAR(200),
    bom_type            VARCHAR(30),           -- STANDARD/ENGINEERING/PLANNING
    assembly_item_id    BIGINT,
    quantity            NUMERIC(18,4) DEFAULT 1.0,
    uom                 VARCHAR(20),
    effective_from      TIMESTAMP,
    effective_to        TIMESTAMP,
    status              VARCHAR(20),
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_bom_batch ON ods_bom_header(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_bom_number ON ods_bom_header(bom_number);
CREATE INDEX IF NOT EXISTS idx_ods_bom_dq ON ods_bom_header(dq_status);

-- BOM Component (BOM组件)
CREATE TABLE IF NOT EXISTS ods_bom_component (
    bom_component_id    BIGINT NOT NULL,
    bom_id              BIGINT NOT NULL,
    component_sequence  INTEGER NOT NULL,
    component_item_id   BIGINT NOT NULL,
    quantity_per        NUMERIC(18,6) NOT NULL,
    uom                 VARCHAR(20),
    effective_from      TIMESTAMP,
    effective_to        TIMESTAMP,
    yield_rate          NUMERIC(5,4) DEFAULT 1.0,
    wip_supply_type     VARCHAR(20),           -- PUSH/PULL/PHANTOM
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_bom_comp_batch ON ods_bom_component(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_bom_comp_bom ON ods_bom_component(bom_id);
CREATE INDEX IF NOT EXISTS idx_ods_bom_comp_dq ON ods_bom_component(dq_status);

-- UOM (计量单位)
CREATE TABLE IF NOT EXISTS ods_uom (
    uom_code            VARCHAR(20) NOT NULL,
    uom_name            VARCHAR(50),
    uom_class           VARCHAR(30),           -- QUANTITY/WEIGHT/LENGTH/VOLUME
    base_uom            VARCHAR(20),
    conversion_rate      NUMERIC(18,8) DEFAULT 1.0,
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_uom_batch ON ods_uom(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_uom_code ON ods_uom(uom_code);

-- Currency (币种)
CREATE TABLE IF NOT EXISTS ods_currency (
    currency_code       VARCHAR(10) NOT NULL,
    currency_name       VARCHAR(100),
    symbol              VARCHAR(10),
    decimal_places      INTEGER DEFAULT 2,
    is_base_currency    BOOLEAN DEFAULT false,
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_currency_batch ON ods_currency(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_currency_code ON ods_currency(currency_code);

-- ============================================================================
-- Procurement Domain (PTP) ODS Tables
-- ============================================================================

-- Purchase Requisition (采购申请)
CREATE TABLE IF NOT EXISTS ods_purchase_requisition (
    requisition_header_id BIGINT NOT NULL,
    pr_number           VARCHAR(64) NOT NULL,
    pr_type             VARCHAR(30),           -- STANDARD/BLANKET/INTERNAL
    description         VARCHAR(500),
    status              VARCHAR(30),           -- DRAFT/PENDING_APPROVAL/APPROVED/REJECTED/CLOSED
    requester_id        BIGINT,
    requester_name      VARCHAR(100),
    request_date        TIMESTAMP,
    need_by_date        TIMESTAMP,
    total_amount        NUMERIC(18,2),
    currency_code       VARCHAR(10) DEFAULT 'CNY',
    approval_date       TIMESTAMP,
    approver_name       VARCHAR(100),
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_pr_batch ON ods_purchase_requisition(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_pr_number ON ods_purchase_requisition(pr_number);
CREATE INDEX IF NOT EXISTS idx_ods_pr_dq ON ods_purchase_requisition(dq_status);
CREATE INDEX IF NOT EXISTS idx_ods_pr_org ON ods_purchase_requisition(org_id);

-- Purchase Requisition Line (采购申请行)
CREATE TABLE IF NOT EXISTS ods_purchase_requisition_line (
    requisition_line_id BIGINT NOT NULL,
    requisition_header_id BIGINT NOT NULL,
    line_number         INTEGER NOT NULL,
    line_type           VARCHAR(30),
    quantity            NUMERIC(18,4) NOT NULL,
    unit_price          NUMERIC(18,4),
    amount              NUMERIC(18,2),
    uom                 VARCHAR(20),
    need_by_date        TIMESTAMP,
    suggested_vendor_id BIGINT,
    item_id             BIGINT,
    item_description    VARCHAR(200),
    status              VARCHAR(30),
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_pr_line_batch ON ods_purchase_requisition_line(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_pr_line_header ON ods_purchase_requisition_line(requisition_header_id);
CREATE INDEX IF NOT EXISTS idx_ods_pr_line_dq ON ods_purchase_requisition_line(dq_status);

-- Purchase Order (采购订单)
CREATE TABLE IF NOT EXISTS ods_purchase_order (
    po_header_id        BIGINT NOT NULL,
    po_number           VARCHAR(64) NOT NULL,
    po_type             VARCHAR(30),           -- STANDARD/BLANKET/CONTRACT/PLANNED
    description         VARCHAR(500),
    status              VARCHAR(30),           -- DRAFT/APPROVED/OPEN/CLOSED/CANCELLED
    buyer_id            BIGINT,
    buyer_name          VARCHAR(100),
    vendor_id           BIGINT,
    vendor_name         VARCHAR(200),
    order_date          TIMESTAMP,
    approved_date       TIMESTAMP,
    total_amount        NUMERIC(18,2) NOT NULL,
    currency_code       VARCHAR(10) DEFAULT 'CNY',
    exchange_rate       NUMERIC(18,6) DEFAULT 1.0,
    payment_terms       VARCHAR(50),
    freight_terms       VARCHAR(50),
    ship_to_location    VARCHAR(200),
    bill_to_location    VARCHAR(200),
    close_date          TIMESTAMP,
    cancel_reason       VARCHAR(200),
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_po_batch ON ods_purchase_order(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_po_number ON ods_purchase_order(po_number);
CREATE INDEX IF NOT EXISTS idx_ods_po_dq ON ods_purchase_order(dq_status);
CREATE INDEX IF NOT EXISTS idx_ods_po_vendor ON ods_purchase_order(vendor_id);
CREATE INDEX IF NOT EXISTS idx_ods_po_buyer ON ods_purchase_order(buyer_id);
CREATE INDEX IF NOT EXISTS idx_ods_po_org ON ods_purchase_order(org_id);
CREATE INDEX IF NOT EXISTS idx_ods_po_update ON ods_purchase_order(source_update_time);

-- Purchase Order Line (采购订单行)
CREATE TABLE IF NOT EXISTS ods_purchase_order_line (
    po_line_id          BIGINT NOT NULL,
    po_header_id        BIGINT NOT NULL,
    line_number         INTEGER NOT NULL,
    line_type           VARCHAR(30),           -- GOODS/SERVICE
    item_id             BIGINT,
    item_description    VARCHAR(200),
    quantity            NUMERIC(18,4) NOT NULL,
    unit_price          NUMERIC(18,4) NOT NULL,
    amount              NUMERIC(18,2) NOT NULL,
    uom                 VARCHAR(20),
    need_by_date        TIMESTAMP,
    promised_date       TIMESTAMP,
    received_quantity   NUMERIC(18,4) DEFAULT 0,
    invoiced_quantity   NUMERIC(18,4) DEFAULT 0,
    status              VARCHAR(30),
    tax_code            VARCHAR(20),
    tax_rate            NUMERIC(5,4) DEFAULT 0,
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_po_line_batch ON ods_purchase_order_line(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_po_line_header ON ods_purchase_order_line(po_header_id);
CREATE INDEX IF NOT EXISTS idx_ods_po_line_item ON ods_purchase_order_line(item_id);
CREATE INDEX IF NOT EXISTS idx_ods_po_line_dq ON ods_purchase_order_line(dq_status);

-- Receipt (收货单)
CREATE TABLE IF NOT EXISTS ods_receipt (
    shipment_header_id  BIGINT NOT NULL,
    receipt_number      VARCHAR(64) NOT NULL,
    receipt_type       VARCHAR(30),           -- STANDARD/RETURN
    receipt_date       TIMESTAMP NOT NULL,
    status              VARCHAR(30),           -- PENDING/RECEIVED/PARTIALLY_RECEIVED/RETURNED
    receiver_id        BIGINT,
    receiver_name      VARCHAR(100),
    po_header_id       BIGINT,
    total_quantity     NUMERIC(18,4),
    warehouse_code     VARCHAR(50),
    comments           VARCHAR(500),
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_receipt_batch ON ods_receipt(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_receipt_number ON ods_receipt(receipt_number);
CREATE INDEX IF NOT EXISTS idx_ods_receipt_po ON ods_receipt(po_header_id);
CREATE INDEX IF NOT EXISTS idx_ods_receipt_dq ON ods_receipt(dq_status);
CREATE INDEX IF NOT EXISTS idx_ods_receipt_org ON ods_receipt(org_id);

-- Receipt Line (收货单行)
CREATE TABLE IF NOT EXISTS ods_receipt_line (
    shipment_line_id    BIGINT NOT NULL,
    shipment_header_id  BIGINT NOT NULL,
    po_line_id          BIGINT,
    line_number         INTEGER NOT NULL,
    item_id             BIGINT,
    received_quantity  NUMERIC(18,4) NOT NULL,
    accepted_quantity   NUMERIC(18,4),
    rejected_quantity  NUMERIC(18,4) DEFAULT 0,
    uom                 VARCHAR(20),
    inspection_status  VARCHAR(30),           -- PENDING/PASSED/FAILED
    lot_number          VARCHAR(50),
    subinventory        VARCHAR(50),
    sublocation         VARCHAR(100),
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_receipt_line_batch ON ods_receipt_line(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_receipt_line_header ON ods_receipt_line(shipment_header_id);
CREATE INDEX IF NOT EXISTS idx_ods_receipt_line_po ON ods_receipt_line(po_line_id);
CREATE INDEX IF NOT EXISTS idx_ods_receipt_line_dq ON ods_receipt_line(dq_status);

-- Supplier Qualification (供应商资质)
CREATE TABLE IF NOT EXISTS ods_supplier_qualification (
    qualification_id   BIGINT NOT NULL,
    vendor_id           BIGINT NOT NULL,
    qualification_type  VARCHAR(50),           -- ISO9001/SAFETY/ENVIRONMENTAL/CUSTOM
    status              VARCHAR(20),           -- VALID/EXPIRED/REVOKED
    issue_date          TIMESTAMP,
    expiry_date         TIMESTAMP,
    issuing_body        VARCHAR(200),
    scope               VARCHAR(500),
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_sup_qual_batch ON ods_supplier_qualification(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_sup_qual_vendor ON ods_supplier_qualification(vendor_id);
CREATE INDEX IF NOT EXISTS idx_ods_sup_qual_dq ON ods_supplier_qualification(dq_status);

-- ASL (Approved Supplier List) - not a vertex, creates SUPPLIES_ITEM edge
CREATE TABLE IF NOT EXISTS ods_asl (
    asl_id              BIGINT NOT NULL,
    vendor_id           BIGINT NOT NULL,
    item_id             BIGINT NOT NULL,
    priority            INTEGER DEFAULT 1,
    unit_price          NUMERIC(18,4),
    lead_time_days      INTEGER,
    status              VARCHAR(20) DEFAULT 'ACTIVE',  -- ACTIVE/INACTIVE
    effective_from      TIMESTAMP,
    effective_to        TIMESTAMP,
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_asl_batch ON ods_asl(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_asl_vendor ON ods_asl(vendor_id);
CREATE INDEX IF NOT EXISTS idx_ods_asl_item ON ods_asl(item_id);
CREATE INDEX IF NOT EXISTS idx_ods_asl_dq ON ods_asl(dq_status);

-- ============================================================================
-- Accounts Payable Domain ODS Tables
-- ============================================================================

-- AP Invoice (应付发票)
CREATE TABLE IF NOT EXISTS ods_ap_invoice (
    invoice_id          BIGINT NOT NULL,
    invoice_number     VARCHAR(64) NOT NULL,
    invoice_type       VARCHAR(30),           -- STANDARD/CREDIT_MEMO/DEBIT_MEMO/PREPAYMENT
    vendor_id           BIGINT NOT NULL,
    vendor_name         VARCHAR(200),
    vendor_site_id      BIGINT,
    invoice_date        TIMESTAMP NOT NULL,
    due_date            TIMESTAMP,
    status              VARCHAR(30),           -- DRAFT/VALIDATED/APPROVED/PAID/CANCELLED/ON_HOLD
    total_amount        NUMERIC(18,2) NOT NULL,
    tax_amount          NUMERIC(18,2) DEFAULT 0,
    currency_code       VARCHAR(10) DEFAULT 'CNY',
    exchange_rate       NUMERIC(18,6) DEFAULT 1.0,
    payment_method      VARCHAR(30),
    description         VARCHAR(500),
    gl_date             TIMESTAMP,
    po_header_id        BIGINT,
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_ap_inv_batch ON ods_ap_invoice(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_ap_inv_number ON ods_ap_invoice(invoice_number);
CREATE INDEX IF NOT EXISTS idx_ods_ap_inv_vendor ON ods_ap_invoice(vendor_id);
CREATE INDEX IF NOT EXISTS idx_ods_ap_inv_po ON ods_ap_invoice(po_header_id);
CREATE INDEX IF NOT EXISTS idx_ods_ap_inv_dq ON ods_ap_invoice(dq_status);
CREATE INDEX IF NOT EXISTS idx_ods_ap_inv_org ON ods_ap_invoice(org_id);

-- AP Invoice Line (应付发票行)
CREATE TABLE IF NOT EXISTS ods_ap_invoice_line (
    invoice_line_id     BIGINT NOT NULL,
    invoice_id          BIGINT NOT NULL,
    line_number         INTEGER NOT NULL,
    line_type           VARCHAR(30),           -- ITEM/TAX/FREIGHT/MISC
    item_id             BIGINT,
    item_description    VARCHAR(200),
    quantity            NUMERIC(18,4),
    unit_price          NUMERIC(18,4),
    amount              NUMERIC(18,2) NOT NULL,
    tax_code            VARCHAR(20),
    tax_rate            NUMERIC(5,4),
    po_line_id          BIGINT,
    receipt_line_id     BIGINT,
    description         VARCHAR(200),
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_ap_inv_line_batch ON ods_ap_invoice_line(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_ap_inv_line_invoice ON ods_ap_invoice_line(invoice_id);
CREATE INDEX IF NOT EXISTS idx_ods_ap_inv_line_po ON ods_ap_invoice_line(po_line_id);
CREATE INDEX IF NOT EXISTS idx_ods_ap_inv_line_dq ON ods_ap_invoice_line(dq_status);

-- AP Payment (应付付款)
CREATE TABLE IF NOT EXISTS ods_ap_payment (
    check_id            BIGINT NOT NULL,
    payment_number      VARCHAR(64) NOT NULL,
    payment_type        VARCHAR(30),           -- CHECK/ELECTRONIC/WIRE/CASH
    vendor_id           BIGINT NOT NULL,
    vendor_site_id      BIGINT,
    bank_account        VARCHAR(50),
    payment_date        TIMESTAMP NOT NULL,
    amount              NUMERIC(18,2) NOT NULL,
    currency_code       VARCHAR(10) DEFAULT 'CNY',
    exchange_rate       NUMERIC(18,6) DEFAULT 1.0,
    status              VARCHAR(30),           -- CREATED/CONFIRMED/CLEARED/VOIDED/RECONCILED
    payment_method      VARCHAR(30),
    check_number        VARCHAR(50),
    cleared_date        TIMESTAMP,
    void_date           TIMESTAMP,
    batch_id            BIGINT,
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_ap_pay_batch ON ods_ap_payment(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_ap_pay_number ON ods_ap_payment(payment_number);
CREATE INDEX IF NOT EXISTS idx_ods_ap_pay_vendor ON ods_ap_payment(vendor_id);
CREATE INDEX IF NOT EXISTS idx_ods_ap_pay_dq ON ods_ap_payment(dq_status);
CREATE INDEX IF NOT EXISTS idx_ods_ap_pay_org ON ods_ap_payment(org_id);

-- AP Payment Batch (付款批次)
CREATE TABLE IF NOT EXISTS ods_ap_payment_batch (
    schedule_id         BIGINT NOT NULL,
    batch_number        VARCHAR(64) NOT NULL,
    batch_date          TIMESTAMP,
    total_amount        NUMERIC(18,2),
    payment_count       INTEGER,
    status              VARCHAR(30),           -- DRAFT/CONFIRMED/COMPLETED
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_ap_pay_batch_batch ON ods_ap_payment_batch(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_ap_pay_batch_number ON ods_ap_payment_batch(batch_number);
CREATE INDEX IF NOT EXISTS idx_ods_ap_pay_batch_dq ON ods_ap_payment_batch(dq_status);

-- AP Invoice Payment (发票付款关联) - creates PAYS_INVOICE edge
CREATE TABLE IF NOT EXISTS ods_ap_invoice_payment (
    invoice_payment_id  BIGINT NOT NULL,
    invoice_id          BIGINT NOT NULL,
    check_id            BIGINT NOT NULL,
    paid_amount         NUMERIC(18,2) NOT NULL,
    payment_date        TIMESTAMP,
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_ap_inv_pay_batch ON ods_ap_invoice_payment(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_ap_inv_pay_invoice ON ods_ap_invoice_payment(invoice_id);
CREATE INDEX IF NOT EXISTS idx_ods_ap_inv_pay_check ON ods_ap_invoice_payment(check_id);
CREATE INDEX IF NOT EXISTS idx_ods_ap_inv_pay_dq ON ods_ap_invoice_payment(dq_status);

-- ============================================================================
-- Order-to-Cash Domain ODS Tables
-- ============================================================================

-- Sales Order (销售订单)
CREATE TABLE IF NOT EXISTS ods_sales_order (
    header_id           BIGINT NOT NULL,
    so_number           VARCHAR(64) NOT NULL,
    order_type          VARCHAR(30),           -- STANDARD/RETURN/INTERNAL
    order_date          TIMESTAMP NOT NULL,
    status              VARCHAR(30),           -- DRAFT/BOOKED/SHIPPED/INVOICED/CLOSED/CANCELLED
    customer_id         BIGINT NOT NULL,
    customer_name       VARCHAR(200),
    total_amount        NUMERIC(18,2) NOT NULL,
    currency_code       VARCHAR(10) DEFAULT 'CNY',
    exchange_rate       NUMERIC(18,6) DEFAULT 1.0,
    payment_terms       VARCHAR(50),
    ship_to_address     VARCHAR(500),
    bill_to_address     VARCHAR(500),
    salesperson         VARCHAR(100),
    requested_date      TIMESTAMP,
    scheduled_date      TIMESTAMP,
    cancel_reason       VARCHAR(200),
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_so_batch ON ods_sales_order(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_so_number ON ods_sales_order(so_number);
CREATE INDEX IF NOT EXISTS idx_ods_so_customer ON ods_sales_order(customer_id);
CREATE INDEX IF NOT EXISTS idx_ods_so_dq ON ods_sales_order(dq_status);
CREATE INDEX IF NOT EXISTS idx_ods_so_org ON ods_sales_order(org_id);
CREATE INDEX IF NOT EXISTS idx_ods_so_update ON ods_sales_order(source_update_time);

-- Sales Order Line (销售订单行)
CREATE TABLE IF NOT EXISTS ods_sales_order_line (
    line_id             BIGINT NOT NULL,
    header_id           BIGINT NOT NULL,
    line_number         INTEGER NOT NULL,
    line_type           VARCHAR(30),
    item_id             BIGINT,
    item_description    VARCHAR(200),
    quantity            NUMERIC(18,4) NOT NULL,
    unit_price          NUMERIC(18,4) NOT NULL,
    amount              NUMERIC(18,2) NOT NULL,
    uom                 VARCHAR(20),
    shipped_quantity    NUMERIC(18,4) DEFAULT 0,
    invoiced_quantity   NUMERIC(18,4) DEFAULT 0,
    status              VARCHAR(30),
    tax_code            VARCHAR(20),
    tax_rate            NUMERIC(5,4) DEFAULT 0,
    scheduled_ship_date TIMESTAMP,
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_so_line_batch ON ods_sales_order_line(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_so_line_header ON ods_sales_order_line(header_id);
CREATE INDEX IF NOT EXISTS idx_ods_so_line_item ON ods_sales_order_line(item_id);
CREATE INDEX IF NOT EXISTS idx_ods_so_line_dq ON ods_sales_order_line(dq_status);

-- Shipment (发货单)
CREATE TABLE IF NOT EXISTS ods_shipment (
    delivery_detail_id  BIGINT NOT NULL,
    shipment_number     VARCHAR(64) NOT NULL,
    so_header_id        BIGINT,
    shipment_date       TIMESTAMP NOT NULL,
    status              VARCHAR(30),           -- PLANNED/PICKED/SHIPPED/DELIVERED/CANCELLED
    carrier             VARCHAR(100),
    tracking_number     VARCHAR(100),
    total_quantity      NUMERIC(18,4),
    warehouse_code      VARCHAR(50),
    delivery_date       TIMESTAMP,
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_ship_batch ON ods_shipment(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_ship_number ON ods_shipment(shipment_number);
CREATE INDEX IF NOT EXISTS idx_ods_ship_so ON ods_shipment(so_header_id);
CREATE INDEX IF NOT EXISTS idx_ods_ship_dq ON ods_shipment(dq_status);
CREATE INDEX IF NOT EXISTS idx_ods_ship_org ON ods_shipment(org_id);

-- Shipment Line (发货单行)
CREATE TABLE IF NOT EXISTS ods_shipment_line (
    assignment_id       BIGINT NOT NULL,
    delivery_detail_id  BIGINT NOT NULL,
    so_line_id          BIGINT,
    line_number         INTEGER NOT NULL,
    item_id             BIGINT,
    shipped_quantity    NUMERIC(18,4) NOT NULL,
    uom                 VARCHAR(20),
    lot_number          VARCHAR(50),
    serial_number       VARCHAR(50),
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_ship_line_batch ON ods_shipment_line(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_ship_line_header ON ods_shipment_line(delivery_detail_id);
CREATE INDEX IF NOT EXISTS idx_ods_ship_line_so ON ods_shipment_line(so_line_id);
CREATE INDEX IF NOT EXISTS idx_ods_ship_line_dq ON ods_shipment_line(dq_status);

-- AR Invoice (应收发票)
CREATE TABLE IF NOT EXISTS ods_ar_invoice (
    customer_trx_id     BIGINT NOT NULL,
    invoice_number      VARCHAR(64) NOT NULL,
    invoice_type        VARCHAR(30),           -- INVOICE/CREDIT_MEMO/DEBIT_MEMO
    customer_id         BIGINT NOT NULL,
    customer_name       VARCHAR(200),
    cust_site_id        BIGINT,
    invoice_date        TIMESTAMP NOT NULL,
    due_date            TIMESTAMP,
    status              VARCHAR(30),           -- DRAFT/COMPLETE/COLLECTED/CANCELLED
    total_amount        NUMERIC(18,2) NOT NULL,
    tax_amount          NUMERIC(18,2) DEFAULT 0,
    currency_code       VARCHAR(10) DEFAULT 'CNY',
    exchange_rate       NUMERIC(18,6) DEFAULT 1.0,
    payment_terms       VARCHAR(50),
    gl_date             TIMESTAMP,
    so_header_id        BIGINT,
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_ar_inv_batch ON ods_ar_invoice(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_ar_inv_number ON ods_ar_invoice(invoice_number);
CREATE INDEX IF NOT EXISTS idx_ods_ar_inv_customer ON ods_ar_invoice(customer_id);
CREATE INDEX IF NOT EXISTS idx_ods_ar_inv_so ON ods_ar_invoice(so_header_id);
CREATE INDEX IF NOT EXISTS idx_ods_ar_inv_dq ON ods_ar_invoice(dq_status);
CREATE INDEX IF NOT EXISTS idx_ods_ar_inv_org ON ods_ar_invoice(org_id);

-- AR Receipt (应收收款)
CREATE TABLE IF NOT EXISTS ods_ar_receipt (
    cash_receipt_id     BIGINT NOT NULL,
    receipt_number      VARCHAR(64) NOT NULL,
    receipt_type        VARCHAR(30),           -- STANDARD/MISC
    customer_id         BIGINT NOT NULL,
    customer_name       VARCHAR(200),
    cust_site_id        BIGINT,
    receipt_date        TIMESTAMP NOT NULL,
    amount              NUMERIC(18,2) NOT NULL,
    currency_code       VARCHAR(10) DEFAULT 'CNY',
    status              VARCHAR(30),           -- CONFIRMED/APPLIED/REVERSED
    payment_method      VARCHAR(30),           -- WIRE/CHECK/CASH
    bank_account        VARCHAR(50),
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_ar_rcpt_batch ON ods_ar_receipt(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_ar_rcpt_number ON ods_ar_receipt(receipt_number);
CREATE INDEX IF NOT EXISTS idx_ods_ar_rcpt_customer ON ods_ar_receipt(customer_id);
CREATE INDEX IF NOT EXISTS idx_ods_ar_rcpt_dq ON ods_ar_receipt(dq_status);
CREATE INDEX IF NOT EXISTS idx_ods_ar_rcpt_org ON ods_ar_receipt(org_id);

-- AR Receipt Application (收款核销) - creates APPLIES_TO edge
CREATE TABLE IF NOT EXISTS ods_ar_receipt_application (
    application_id      BIGINT NOT NULL,
    cash_receipt_id     BIGINT NOT NULL,
    customer_trx_id     BIGINT NOT NULL,
    applied_amount      NUMERIC(18,2) NOT NULL,
    application_date    TIMESTAMP,
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_ar_rcpt_app_batch ON ods_ar_receipt_application(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_ar_rcpt_app_receipt ON ods_ar_receipt_application(cash_receipt_id);
CREATE INDEX IF NOT EXISTS idx_ods_ar_rcpt_app_trx ON ods_ar_receipt_application(customer_trx_id);
CREATE INDEX IF NOT EXISTS idx_ods_ar_rcpt_app_dq ON ods_ar_receipt_application(dq_status);

-- ============================================================================
-- General Ledger / Accounting Domain ODS Tables
-- ============================================================================

-- GL Account (总账科目)
CREATE TABLE IF NOT EXISTS ods_gl_account (
    code_combination_id  BIGINT NOT NULL,
    account_code        VARCHAR(50) NOT NULL,
    account_name        VARCHAR(200) NOT NULL,
    account_type        VARCHAR(30),           -- ASSET/LIABILITY/EQUITY/REVENUE/EXPENSE
    parent_ccid         BIGINT,
    level_num           INTEGER,
    is_leaf             BOOLEAN DEFAULT true,
    currency_code       VARCHAR(10),
    status              VARCHAR(20),
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_gl_acct_batch ON ods_gl_account(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_gl_acct_code ON ods_gl_account(account_code);
CREATE INDEX IF NOT EXISTS idx_ods_gl_acct_dq ON ods_gl_account(dq_status);

-- GL Journal Entry (日记账分录)
CREATE TABLE IF NOT EXISTS ods_gl_journal (
    je_header_id        BIGINT NOT NULL,
    journal_number      VARCHAR(64) NOT NULL,
    journal_name        VARCHAR(100),
    journal_source      VARCHAR(30),           -- AP/AR/PO/MANUAL
    journal_category    VARCHAR(30),
    period_name         VARCHAR(20),           -- e.g., 2026-04
    gl_date             TIMESTAMP NOT NULL,
    status              VARCHAR(20),           -- UNPOSTED/POSTED/REVERSED
    total_debit         NUMERIC(18,2),
    total_credit        NUMERIC(18,2),
    description         VARCHAR(500),
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_gl_je_batch ON ods_gl_journal(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_gl_je_number ON ods_gl_journal(journal_number);
CREATE INDEX IF NOT EXISTS idx_ods_gl_je_dq ON ods_gl_journal(dq_status);
CREATE INDEX IF NOT EXISTS idx_ods_gl_je_org ON ods_gl_journal(org_id);
CREATE INDEX IF NOT EXISTS idx_ods_gl_je_gl_date ON ods_gl_journal(gl_date);

-- GL Journal Line (日记账行)
CREATE TABLE IF NOT EXISTS ods_gl_journal_line (
    je_line_id          BIGINT NOT NULL,
    je_header_id        BIGINT NOT NULL,
    line_number         INTEGER NOT NULL,
    code_combination_id BIGINT NOT NULL,
    debit_amount        NUMERIC(18,2) DEFAULT 0,
    credit_amount       NUMERIC(18,2) DEFAULT 0,
    description         VARCHAR(200),
    reference           VARCHAR(100),           -- Source document number
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_gl_je_line_batch ON ods_gl_journal_line(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_gl_je_line_header ON ods_gl_journal_line(je_header_id);
CREATE INDEX IF NOT EXISTS idx_ods_gl_je_line_acct ON ods_gl_journal_line(code_combination_id);
CREATE INDEX IF NOT EXISTS idx_ods_gl_je_line_dq ON ods_gl_journal_line(dq_status);

-- XLA Event (XLA会计事件)
CREATE TABLE IF NOT EXISTS ods_xla_event (
    event_id            BIGINT NOT NULL,
    event_number        VARCHAR(64) NOT NULL,
    event_class         VARCHAR(30),           -- PURCHASE/RECEIPT/INVOICE/PAYMENT/SALES/SHIPMENT
    event_type          VARCHAR(30),           -- CREATE/REVERSE/ADJUSTMENT
    event_date          TIMESTAMP NOT NULL,
    accounting_date     TIMESTAMP,
    status              VARCHAR(20),           -- DRAFT/FINAL/INCOMPLETE
    source_doc_type     VARCHAR(30),
    source_doc_id       VARCHAR(64),
    description         VARCHAR(200),
    entity_id           BIGINT,
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_xla_event_batch ON ods_xla_event(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_xla_event_number ON ods_xla_event(event_number);
CREATE INDEX IF NOT EXISTS idx_ods_xla_event_dq ON ods_xla_event(dq_status);
CREATE INDEX IF NOT EXISTS idx_ods_xla_event_org ON ods_xla_event(org_id);

-- XLA Distribution (会计分配)
CREATE TABLE IF NOT EXISTS ods_xla_distribution (
    distribution_id     BIGINT NOT NULL,
    event_id            BIGINT NOT NULL,
    line_number         INTEGER,
    code_combination_id BIGINT NOT NULL,
    debit_amount        NUMERIC(18,2) DEFAULT 0,
    credit_amount       NUMERIC(18,2) DEFAULT 0,
    currency_code       VARCHAR(10) DEFAULT 'CNY',
    accounting_class    VARCHAR(30),           -- CHARGE/TAX/FREIGHT/ACCRUAL
    posted_flag         BOOLEAN DEFAULT false,
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_xla_dist_batch ON ods_xla_distribution(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_xla_dist_event ON ods_xla_distribution(event_id);
CREATE INDEX IF NOT EXISTS idx_ods_xla_dist_acct ON ods_xla_distribution(code_combination_id);
CREATE INDEX IF NOT EXISTS idx_ods_xla_dist_dq ON ods_xla_distribution(dq_status);

-- ============================================================================
-- Approval / Contract Domain ODS Tables
-- ============================================================================

-- Approval Record (审批记录)
CREATE TABLE IF NOT EXISTS ods_approval_record (
    approval_id         BIGINT NOT NULL,
    doc_type            VARCHAR(30),           -- PR/PO/INVOICE/PAYMENT/SO
    doc_number          VARCHAR(64),
    doc_header_id       BIGINT,
    approval_action     VARCHAR(30),           -- SUBMIT/APPROVE/REJECT/RETURN
    approver_id         BIGINT,
    approver_name       VARCHAR(100),
    approval_date       TIMESTAMP,
    comments            VARCHAR(500),
    approval_level      INTEGER,
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_approval_batch ON ods_approval_record(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_approval_doc ON ods_approval_record(doc_type, doc_header_id);
CREATE INDEX IF NOT EXISTS idx_ods_approval_dq ON ods_approval_record(dq_status);
CREATE INDEX IF NOT EXISTS idx_ods_approval_org ON ods_approval_record(org_id);

-- Contract (合同)
CREATE TABLE IF NOT EXISTS ods_contract (
    contract_id         BIGINT NOT NULL,
    contract_number     VARCHAR(64) NOT NULL,
    contract_type       VARCHAR(30),           -- PURCHASE/SALES/SERVICE/BLANKET
    contract_name       VARCHAR(200),
    status              VARCHAR(30),           -- DRAFT/ACTIVE/EXPIRED/TERMINATED
    start_date          TIMESTAMP,
    end_date            TIMESTAMP,
    total_amount        NUMERIC(18,2),
    currency_code       VARCHAR(10) DEFAULT 'CNY',
    description         VARCHAR(500),
    party_type          VARCHAR(30),           -- SUPPLIER/CUSTOMER
    party_id            BIGINT,
    party_name          VARCHAR(200),
    org_id              BIGINT,

    etl_batch_id        VARCHAR(64) NOT NULL,
    etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
    source_system       VARCHAR(30) NOT NULL,
    source_update_time  TIMESTAMP,
    is_deleted          BOOLEAN DEFAULT false,
    dq_status           VARCHAR(20) DEFAULT 'pending',
    dq_errors           JSONB
);

CREATE INDEX IF NOT EXISTS idx_ods_contract_batch ON ods_contract(etl_batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_contract_number ON ods_contract(contract_number);
CREATE INDEX IF NOT EXISTS idx_ods_contract_party ON ods_contract(party_type, party_id);
CREATE INDEX IF NOT EXISTS idx_ods_contract_dq ON ods_contract(dq_status);
CREATE INDEX IF NOT EXISTS idx_ods_contract_org ON ods_contract(org_id);

-- ============================================================================
-- ETL Per-Table Sync Status (P3: incremental loading)
-- ============================================================================
-- Tracks the extraction progress of each ODS table independently, so a
-- failed batch can be resumed per-table (e.g. supplier succeeded but
-- purchase_order failed). Replaces reliance on etl_sync_status.tables[]
-- which only records batch-level completion.
--
-- The (batch_id, table_name) UNIQUE constraint makes loads idempotent:
-- the incremental loader skips a table when a 'success' row already
-- exists for the same batch.

CREATE TABLE IF NOT EXISTS etl_table_sync_status (
    id                  BIGSERIAL PRIMARY KEY,
    batch_id            VARCHAR(64) NOT NULL,
    table_name          VARCHAR(64) NOT NULL,
    source_system       VARCHAR(30) NOT NULL,
    watermark_start     TIMESTAMP,              -- since value used for extraction
    extraction_cutoff   TIMESTAMP,              -- Oracle SYSTIMESTAMP at extract start (next watermark)
    rows_extracted      BIGINT DEFAULT 0,
    rows_loaded         BIGINT DEFAULT 0,
    status              VARCHAR(20) NOT NULL,   -- extracting/loading/success/failed/skipped
    error_message       TEXT,
    started_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMP,
    UNIQUE(batch_id, table_name)
);

CREATE INDEX IF NOT EXISTS idx_table_sync_status_table ON etl_table_sync_status(table_name, status);
CREATE INDEX IF NOT EXISTS idx_table_sync_status_batch ON etl_table_sync_status(batch_id);
CREATE INDEX IF NOT EXISTS idx_table_sync_status_started ON etl_table_sync_status(started_at DESC);

-- ============================================================================
-- ETL Per-Table Sync Status (P3: incremental loading)
-- ============================================================================
-- Tracks the extraction progress of each ODS table independently, so a
-- failed batch can be resumed per-table (e.g. supplier succeeded but
-- purchase_order failed). Replaces reliance on etl_sync_status.tables[]
-- which only records batch-level completion.
--
-- The (batch_id, table_name) UNIQUE constraint makes loads idempotent:
-- the incremental loader skips a table when a 'success' row already
-- exists for the same batch.

CREATE TABLE IF NOT EXISTS etl_table_sync_status (
    id                  BIGSERIAL PRIMARY KEY,
    batch_id            VARCHAR(64) NOT NULL,
    table_name          VARCHAR(64) NOT NULL,
    source_system       VARCHAR(30) NOT NULL,
    watermark_start     TIMESTAMP,              -- since value used for extraction
    extraction_cutoff   TIMESTAMP,              -- Oracle SYSTIMESTAMP at extract start (next watermark)
    rows_extracted      BIGINT DEFAULT 0,
    rows_loaded         BIGINT DEFAULT 0,
    status              VARCHAR(20) NOT NULL,   -- extracting/loading/success/failed/skipped
    error_message       TEXT,
    started_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMP,
    UNIQUE(batch_id, table_name)
);

CREATE INDEX IF NOT EXISTS idx_table_sync_status_table ON etl_table_sync_status(table_name, status);
CREATE INDEX IF NOT EXISTS idx_table_sync_status_batch ON etl_table_sync_status(batch_id);
CREATE INDEX IF NOT EXISTS idx_table_sync_status_started ON etl_table_sync_status(started_at DESC);
