"""Graph transformation engine for HoneyBadge ETL.

Transforms ODS (Operational Data Store) data from PostgreSQL into
NebulaGraph vertex/edge format for import via nebula-importer.

Key concepts:
    - VERTEX_MAPPINGS: Defines how ODS tables map to NebulaGraph tags
    - EDGE_MAPPINGS: Defines how ODS tables map to NebulaGraph edge types
    - GraphTransformer: Transforms ODS data into CSV files for nebula-importer
"""

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg
import structlog

from honeybadge.core.constants import (
    VID_PREFIX_APPROVAL,
    VID_PREFIX_AR_INVOICE,
    VID_PREFIX_AR_RECEIPT,
    VID_PREFIX_BOM,
    VID_PREFIX_BOM_COMP,
    VID_PREFIX_CONTRACT,
    VID_PREFIX_CUSTOMER,
    VID_PREFIX_EMPLOYEE,
    VID_PREFIX_GL_ACCOUNT,
    VID_PREFIX_INVOICE,
    VID_PREFIX_INVOICE_LINE,
    VID_PREFIX_ITEM,
    VID_PREFIX_JOURNAL,
    VID_PREFIX_JOURNAL_LINE,
    VID_PREFIX_ORG,
    VID_PREFIX_PAYMENT,
    VID_PREFIX_PAYMENT_BATCH,
    VID_PREFIX_PO,
    VID_PREFIX_PO_LINE,
    VID_PREFIX_PR,
    VID_PREFIX_PR_LINE,
    VID_PREFIX_QUALIFICATION,
    VID_PREFIX_RECEIPT,
    VID_PREFIX_RECEIPT_LINE,
    VID_PREFIX_SHIPMENT,
    VID_PREFIX_SHIPMENT_LINE,
    VID_PREFIX_SO,
    VID_PREFIX_SO_LINE,
    VID_PREFIX_SUPPLIER,
    VID_PREFIX_UOM,
    VID_PREFIX_WAREHOUSE,
    VID_PREFIX_XLA_EVENT,
)

logger = structlog.get_logger()


# =============================================================================
# Vertex Mappings
# =============================================================================

VERTEX_MAPPINGS: dict[str, dict[str, Any]] = {
    "Supplier": {
        "source_table": "ods_supplier",
        "vid_template": f"{VID_PREFIX_SUPPLIER}:{{vendor_id}}",
        "properties": {
            "supplier_number": "vendor_number",
            "supplier_name": "vendor_name",
            "supplier_type": "vendor_type",
            "status": "status",
            "country": "country",
            "city": "city",
            "address": "address",
            "contact_person": "contact_person",
            "contact_phone": "contact_phone",
            "contact_email": "contact_email",
            "bank_account": "bank_account",
            "bank_name": "bank_name",
            "tax_id": "vat_registration_num",
            "currency": "'CNY'",  # Default currency
            "payment_terms": "payment_terms",
            "credit_rating": "credit_rating",
            "registration_date": "start_date",
            "qualification_expiry": "end_date",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status = 'ACTIVE' THEN true ELSE false END",
        },
    },
    "Customer": {
        "source_table": "ods_customer",
        "vid_template": f"{VID_PREFIX_CUSTOMER}:{{customer_id}}",
        "properties": {
            "customer_number": "customer_number",
            "customer_name": "customer_name",
            "customer_type": "customer_type",
            "status": "status",
            "country": "country",
            "city": "city",
            "address": "address",
            "contact_person": "contact_person",
            "contact_phone": "contact_phone",
            "contact_email": "contact_email",
            "credit_limit": "credit_limit",
            "payment_terms": "payment_terms",
            "tax_id": "tax_id",
            "currency": "currency",
            "sales_region": "sales_region",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status = 'ACTIVE' THEN true ELSE false END",
        },
    },
    "Item": {
        "source_table": "ods_item",
        "vid_template": f"{VID_PREFIX_ITEM}:{{inventory_item_id}}",
        "properties": {
            "item_number": "item_number",
            "item_name": "item_name",
            "item_description": "item_description",
            "item_type": "item_type",
            "category": "category",
            "uom": "uom",
            "standard_cost": "standard_cost",
            "list_price": "list_price",
            "weight": "weight",
            "weight_uom": "weight_uom",
            "lead_time_days": "lead_time_days",
            "safety_stock": "safety_stock",
            "min_order_qty": "min_order_qty",
            "status": "status",
            "abc_class": "abc_class",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status = 'ACTIVE' THEN true ELSE false END",
        },
    },
    "Organization": {
        "source_table": "ods_organization",
        "vid_template": f"{VID_PREFIX_ORG}:{{org_id}}",
        "properties": {
            "org_code": "org_code",
            "org_name": "org_name",
            "org_type": "org_type",
            "parent_org_code": "parent_org_id",  # Would need subquery in real impl
            "legal_entity": "legal_entity",
            "country": "country",
            "city": "city",
            "status": "status",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status = 'ACTIVE' THEN true ELSE false END",
        },
    },
    "Employee": {
        "source_table": "ods_employee",
        "vid_template": f"{VID_PREFIX_EMPLOYEE}:{{employee_id}}",
        "properties": {
            "employee_number": "employee_number",
            "employee_name": "employee_name",
            "position": "position",
            "department": "department",
            "email": "email",
            "phone": "phone",
            "manager_id": "manager_id",
            "hire_date": "hire_date",
            "status": "status",
            "org_id": "org_id",
            "dept_id": "org_id",
            "data_scope": "'本人'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status = 'ACTIVE' THEN true ELSE false END",
        },
    },
    "Warehouse": {
        "source_table": "ods_warehouse",
        "vid_template": f"{VID_PREFIX_WAREHOUSE}:{{warehouse_id}}",
        "properties": {
            "warehouse_code": "warehouse_code",
            "warehouse_name": "warehouse_name",
            "warehouse_type": "warehouse_type",
            "location": "location",
            "capacity": "capacity",
            "status": "status",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status = 'ACTIVE' THEN true ELSE false END",
        },
    },
    "BOM": {
        "source_table": "ods_bom_header",
        "vid_template": f"{VID_PREFIX_BOM}:{{bom_id}}",
        "properties": {
            "bom_number": "bom_number",
            "bom_name": "bom_name",
            "bom_type": "bom_type",
            "effective_from": "effective_from",
            "effective_to": "effective_to",
            "quantity": "quantity",
            "uom": "uom",
            "status": "status",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status = 'ACTIVE' THEN true ELSE false END",
        },
    },
    "BOMComponent": {
        "source_table": "ods_bom_component",
        "vid_template": f"{VID_PREFIX_BOM_COMP}:{{bom_component_id}}",
        "properties": {
            "component_seq": "component_sequence",
            "quantity_per": "quantity_per",
            "uom": "uom",
            "effective_from": "effective_from",
            "effective_to": "effective_to",
            "yield_rate": "yield_rate",
            "wip_supply_type": "wip_supply_type",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status = 'ACTIVE' THEN true ELSE false END",
        },
    },
    "Currency": {
        "source_table": "ods_currency",
        "vid_template": f"{VID_PREFIX_UOM}:{{currency_code}}",  # Reusing UOM prefix for currency
        "properties": {
            "currency_code": "currency_code",
            "currency_name": "currency_name",
            "symbol": "symbol",
            "decimal_places": "decimal_places",
            "is_base_currency": "is_base_currency",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "true",
        },
    },
    "UOM": {
        "source_table": "ods_uom",
        "vid_template": f"{VID_PREFIX_UOM}:{{uom_code}}",
        "properties": {
            "uom_code": "uom_code",
            "uom_name": "uom_name",
            "uom_class": "uom_class",
            "base_uom": "base_uom",
            "conversion_rate": "conversion_rate",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "true",
        },
    },
    "PurchaseRequisition": {
        "source_table": "ods_purchase_requisition",
        "vid_template": f"{VID_PREFIX_PR}:{{requisition_header_id}}",
        "properties": {
            "pr_number": "pr_number",
            "pr_type": "pr_type",
            "description": "description",
            "status": "status",
            "requester": "requester_name",
            "request_date": "request_date",
            "need_by_date": "need_by_date",
            "total_amount": "total_amount",
            "currency": "currency_code",
            "approval_date": "approval_date",
            "approver": "approver_name",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status = 'CLOSED' THEN false ELSE true END",
        },
    },
    "PurchaseRequisitionLine": {
        "source_table": "ods_purchase_requisition_line",
        "vid_template": f"{VID_PREFIX_PR_LINE}:{{requisition_line_id}}",
        "properties": {
            "line_number": "line_number",
            "quantity": "quantity",
            "unit_price": "unit_price",
            "amount": "amount",
            "uom": "uom",
            "need_by_date": "need_by_date",
            "suggested_vendor": "suggested_vendor_id",  # Would need join
            "status": "status",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status = 'CLOSED' THEN false ELSE true END",
        },
    },
    "PurchaseOrder": {
        "source_table": "ods_purchase_order",
        "vid_template": f"{VID_PREFIX_PO}:{{po_header_id}}",
        "properties": {
            "po_number": "po_number",
            "po_type": "po_type",
            "description": "description",
            "status": "status",
            "buyer": "buyer_name",
            "order_date": "order_date",
            "approved_date": "approved_date",
            "total_amount": "total_amount",
            "currency": "currency_code",
            "exchange_rate": "exchange_rate",
            "payment_terms": "payment_terms",
            "freight_terms": "freight_terms",
            "ship_to_location": "ship_to_location",
            "bill_to_location": "bill_to_location",
            "close_date": "close_date",
            "cancel_reason": "cancel_reason",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status IN ('CLOSED', 'CANCELLED') THEN false ELSE true END",
        },
    },
    "PurchaseOrderLine": {
        "source_table": "ods_purchase_order_line",
        "vid_template": f"{VID_PREFIX_PO_LINE}:{{po_line_id}}",
        "properties": {
            "line_number": "line_number",
            "line_type": "line_type",
            "quantity": "quantity",
            "unit_price": "unit_price",
            "amount": "amount",
            "uom": "uom",
            "need_by_date": "need_by_date",
            "promised_date": "promised_date",
            "received_quantity": "received_quantity",
            "invoiced_quantity": "invoiced_quantity",
            "status": "status",
            "tax_code": "tax_code",
            "tax_rate": "tax_rate",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status = 'CLOSED' THEN false ELSE true END",
        },
    },
    "Receipt": {
        "source_table": "ods_receipt",
        "vid_template": f"{VID_PREFIX_RECEIPT}:{{shipment_header_id}}",
        "properties": {
            "receipt_number": "receipt_number",
            "receipt_type": "receipt_type",
            "receipt_date": "receipt_date",
            "status": "status",
            "receiver": "receiver_name",
            "total_quantity": "total_quantity",
            "warehouse": "warehouse_code",
            "comments": "comments",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "true",
        },
    },
    "ReceiptLine": {
        "source_table": "ods_receipt_line",
        "vid_template": f"{VID_PREFIX_RECEIPT_LINE}:{{shipment_line_id}}",
        "properties": {
            "line_number": "line_number",
            "received_quantity": "received_quantity",
            "accepted_quantity": "accepted_quantity",
            "rejected_quantity": "rejected_quantity",
            "uom": "uom",
            "inspection_status": "inspection_status",
            "lot_number": "lot_number",
            "sublocation": "sublocation",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "true",
        },
    },
    "SupplierQualification": {
        "source_table": "ods_supplier_qualification",
        "vid_template": f"{VID_PREFIX_QUALIFICATION}:{{qualification_id}}",
        "properties": {
            "qualification_id": "qualification_id",
            "qualification_type": "qualification_type",
            "status": "status",
            "issue_date": "issue_date",
            "expiry_date": "expiry_date",
            "issuing_body": "issuing_body",
            "scope": "scope",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status = 'VALID' THEN true ELSE false END",
        },
    },
    "Invoice": {
        "source_table": "ods_ap_invoice",
        "vid_template": f"{VID_PREFIX_INVOICE}:{{invoice_id}}",
        "properties": {
            "invoice_number": "invoice_number",
            "invoice_type": "invoice_type",
            "invoice_date": "invoice_date",
            "due_date": "due_date",
            "status": "status",
            "total_amount": "total_amount",
            "tax_amount": "tax_amount",
            "currency": "currency_code",
            "exchange_rate": "exchange_rate",
            "payment_method": "payment_method",
            "description": "description",
            "gl_date": "gl_date",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status IN ('PAID', 'CANCELLED') THEN false ELSE true END",
        },
    },
    "InvoiceLine": {
        "source_table": "ods_ap_invoice_line",
        "vid_template": f"{VID_PREFIX_INVOICE_LINE}:{{invoice_line_id}}",
        "properties": {
            "line_number": "line_number",
            "line_type": "line_type",
            "quantity": "quantity",
            "unit_price": "unit_price",
            "amount": "amount",
            "tax_code": "tax_code",
            "tax_rate": "tax_rate",
            "description": "description",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "true",
        },
    },
    "Payment": {
        "source_table": "ods_ap_payment",
        "vid_template": f"{VID_PREFIX_PAYMENT}:{{check_id}}",
        "properties": {
            "payment_number": "payment_number",
            "payment_type": "payment_type",
            "payment_date": "payment_date",
            "amount": "amount",
            "currency": "currency_code",
            "exchange_rate": "exchange_rate",
            "status": "status",
            "bank_account": "bank_account",
            "payment_method": "payment_method",
            "check_number": "check_number",
            "cleared_date": "cleared_date",
            "void_date": "void_date",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status IN ('CLEARED', 'VOIDED') THEN false ELSE true END",
        },
    },
    "PaymentBatch": {
        "source_table": "ods_ap_payment_batch",
        "vid_template": f"{VID_PREFIX_PAYMENT_BATCH}:{{schedule_id}}",
        "properties": {
            "batch_number": "batch_number",
            "batch_date": "batch_date",
            "total_amount": "total_amount",
            "payment_count": "payment_count",
            "status": "status",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status = 'COMPLETED' THEN false ELSE true END",
        },
    },
    "SalesOrder": {
        "source_table": "ods_sales_order",
        "vid_template": f"{VID_PREFIX_SO}:{{header_id}}",
        "properties": {
            "so_number": "so_number",
            "order_type": "order_type",
            "order_date": "order_date",
            "status": "status",
            "total_amount": "total_amount",
            "currency": "currency_code",
            "exchange_rate": "exchange_rate",
            "payment_terms": "payment_terms",
            "ship_to_address": "ship_to_address",
            "bill_to_address": "bill_to_address",
            "salesperson": "salesperson",
            "requested_date": "requested_date",
            "scheduled_date": "scheduled_date",
            "cancel_reason": "cancel_reason",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status IN ('CLOSED', 'CANCELLED') THEN false ELSE true END",
        },
    },
    "SalesOrderLine": {
        "source_table": "ods_sales_order_line",
        "vid_template": f"{VID_PREFIX_SO_LINE}:{{line_id}}",
        "properties": {
            "line_number": "line_number",
            "quantity": "quantity",
            "unit_price": "unit_price",
            "amount": "amount",
            "uom": "uom",
            "shipped_quantity": "shipped_quantity",
            "invoiced_quantity": "invoiced_quantity",
            "status": "status",
            "tax_code": "tax_code",
            "tax_rate": "tax_rate",
            "scheduled_ship_date": "scheduled_ship_date",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status = 'CLOSED' THEN false ELSE true END",
        },
    },
    "Shipment": {
        "source_table": "ods_shipment",
        "vid_template": f"{VID_PREFIX_SHIPMENT}:{{delivery_detail_id}}",
        "properties": {
            "shipment_number": "shipment_number",
            "shipment_date": "shipment_date",
            "status": "status",
            "carrier": "carrier",
            "tracking_number": "tracking_number",
            "total_quantity": "total_quantity",
            "warehouse": "warehouse_code",
            "delivery_date": "delivery_date",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status IN ('DELIVERED', 'CANCELLED') THEN false ELSE true END",
        },
    },
    "ShipmentLine": {
        "source_table": "ods_shipment_line",
        "vid_template": f"{VID_PREFIX_SHIPMENT_LINE}:{{assignment_id}}",
        "properties": {
            "line_number": "line_number",
            "shipped_quantity": "shipped_quantity",
            "uom": "uom",
            "lot_number": "lot_number",
            "serial_number": "serial_number",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "true",
        },
    },
    "ARInvoice": {
        "source_table": "ods_ar_invoice",
        "vid_template": f"{VID_PREFIX_AR_INVOICE}:{{customer_trx_id}}",
        "properties": {
            "invoice_number": "invoice_number",
            "invoice_type": "invoice_type",
            "invoice_date": "invoice_date",
            "due_date": "due_date",
            "status": "status",
            "total_amount": "total_amount",
            "tax_amount": "tax_amount",
            "currency": "currency_code",
            "exchange_rate": "exchange_rate",
            "payment_terms": "payment_terms",
            "gl_date": "gl_date",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status IN ('COLLECTED', 'CANCELLED') THEN false ELSE true END",
        },
    },
    "ARReceipt": {
        "source_table": "ods_ar_receipt",
        "vid_template": f"{VID_PREFIX_AR_RECEIPT}:{{cash_receipt_id}}",
        "properties": {
            "receipt_number": "receipt_number",
            "receipt_type": "receipt_type",
            "receipt_date": "receipt_date",
            "amount": "amount",
            "currency": "currency_code",
            "status": "status",
            "payment_method": "payment_method",
            "bank_account": "bank_account",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status IN ('APPLIED', 'REVERSED') THEN false ELSE true END",
        },
    },
    "GLAccount": {
        "source_table": "ods_gl_account",
        "vid_template": f"{VID_PREFIX_GL_ACCOUNT}:{{code_combination_id}}",
        "properties": {
            "account_code": "account_code",
            "account_name": "account_name",
            "account_type": "account_type",
            "parent_account": "parent_ccid",  # Would need subquery
            "level": "level_num",
            "is_leaf": "is_leaf",
            "currency": "currency_code",
            "status": "status",
            "org_id": "org_id",
            "dept_id": "org_id",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status = 'ACTIVE' THEN true ELSE false END",
        },
    },
    "GLJournalEntry": {
        "source_table": "ods_gl_journal",
        "vid_template": f"{VID_PREFIX_JOURNAL}:{{je_header_id}}",
        "properties": {
            "journal_number": "journal_number",
            "journal_name": "journal_name",
            "journal_source": "journal_source",
            "journal_category": "journal_category",
            "period_name": "period_name",
            "gl_date": "gl_date",
            "status": "status",
            "total_debit": "total_debit",
            "total_credit": "total_credit",
            "description": "description",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "true",
        },
    },
    "GLJournalLine": {
        "source_table": "ods_gl_journal_line",
        "vid_template": f"{VID_PREFIX_JOURNAL_LINE}:{{je_line_id}}",
        "properties": {
            "line_number": "line_number",
            "debit_amount": "debit_amount",
            "credit_amount": "credit_amount",
            "description": "description",
            "reference": "reference",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "true",
        },
    },
    "XLAEvent": {
        "source_table": "ods_xla_event",
        "vid_template": f"{VID_PREFIX_XLA_EVENT}:{{event_id}}",
        "properties": {
            "event_id": "event_number",
            "event_class": "event_class",
            "event_type": "event_type",
            "event_date": "event_date",
            "accounting_date": "accounting_date",
            "status": "status",
            "source_doc_type": "source_doc_type",
            "source_doc_id": "source_doc_id",
            "description": "description",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "true",
        },
    },
    "AccountingDistribution": {
        "source_table": "ods_xla_distribution",
        "vid_template": f"{VID_PREFIX_XLA_EVENT}:{{distribution_id}}",  # Reusing prefix
        "properties": {
            "distribution_id": "distribution_id",
            "line_number": "line_number",
            "debit_amount": "debit_amount",
            "credit_amount": "credit_amount",
            "currency": "currency_code",
            "accounting_class": "accounting_class",
            "posted_flag": "posted_flag",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "true",
        },
    },
    "ApprovalRecord": {
        "source_table": "ods_approval_record",
        "vid_template": f"{VID_PREFIX_APPROVAL}:{{approval_id}}",
        "properties": {
            "approval_id": "approval_id",
            "doc_type": "doc_type",
            "doc_number": "doc_number",
            "approval_action": "approval_action",
            "approver": "approver_name",
            "approval_date": "approval_date",
            "comments": "comments",
            "approval_level": "approval_level",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "true",
        },
    },
    "Contract": {
        "source_table": "ods_contract",
        "vid_template": f"{VID_PREFIX_CONTRACT}:{{contract_id}}",
        "properties": {
            "contract_number": "contract_number",
            "contract_type": "contract_type",
            "contract_name": "contract_name",
            "status": "status",
            "start_date": "start_date",
            "end_date": "end_date",
            "total_amount": "total_amount",
            "currency": "currency_code",
            "description": "description",
            "org_id": "org_id",
            "dept_id": "NULL",
            "data_scope": "'全公司'",
            "source_system": "source_system",
            "is_active": "CASE WHEN status = 'ACTIVE' THEN true ELSE false END",
        },
    },
}


# =============================================================================
# Edge Mappings
# =============================================================================

EDGE_MAPPINGS: dict[str, dict[str, Any]] = {
    # ==========================================================================
    # Procurement Domain Edges
    # ==========================================================================
    "PLACED_WITH": {
        "source_table": "ods_purchase_order",
        "src_vid": f"{VID_PREFIX_PO}:{{po_header_id}}",
        "dst_vid": f"{VID_PREFIX_SUPPLIER}:{{vendor_id}}",
        "properties": {
            "order_date": "order_date",
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "HAS_PO_LINE": {
        "source_table": "ods_purchase_order_line",
        "src_vid": f"{VID_PREFIX_PO}:{{po_header_id}}",
        "dst_vid": f"{VID_PREFIX_PO_LINE}:{{po_line_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "ORDERS_ITEM": {
        "source_table": "ods_purchase_order_line",
        "src_vid": f"{VID_PREFIX_PO_LINE}:{{po_line_id}}",
        "dst_vid": f"{VID_PREFIX_ITEM}:{{item_id}}",
        "properties": {
            "quantity": "quantity",
            "unit_price": "unit_price",
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "CONVERTS_TO_PO": {
        "source_table": "ods_purchase_requisition",
        "src_vid": f"{VID_PREFIX_PR}:{{requisition_header_id}}",
        "dst_vid": f"{VID_PREFIX_PO}:{{po_header_id}}",  # po_header_id populated after conversion
        "properties": {
            "conversion_date": "approval_date",  # Or actual conversion date
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "HAS_PR_LINE": {
        "source_table": "ods_purchase_requisition_line",
        "src_vid": f"{VID_PREFIX_PR}:{{requisition_header_id}}",
        "dst_vid": f"{VID_PREFIX_PR_LINE}:{{requisition_line_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "HAS_RECEIPT": {
        "source_table": "ods_receipt",
        "src_vid": f"{VID_PREFIX_PO}:{{po_header_id}}",
        "dst_vid": f"{VID_PREFIX_RECEIPT}:{{shipment_header_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "HAS_RECEIPT_LINE": {
        "source_table": "ods_receipt_line",
        "src_vid": f"{VID_PREFIX_RECEIPT}:{{shipment_header_id}}",
        "dst_vid": f"{VID_PREFIX_RECEIPT_LINE}:{{shipment_line_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "HAS_INVOICE": {
        "source_table": "ods_ap_invoice",
        "src_vid": f"{VID_PREFIX_PO}:{{po_header_id}}",
        "dst_vid": f"{VID_PREFIX_INVOICE}:{{invoice_id}}",
        "properties": {
            "match_status": "'UNMATCHED'",  # Default, updated by matching logic
            "match_date": "NULL",
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "ORDERED_BY": {
        "source_table": "ods_purchase_order",
        "src_vid": f"{VID_PREFIX_PO}:{{po_header_id}}",
        "dst_vid": f"{VID_PREFIX_EMPLOYEE}:{{buyer_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "org_id",
        },
    },
    "HAS_QUALIFICATION": {
        "source_table": "ods_supplier_qualification",
        "src_vid": f"{VID_PREFIX_SUPPLIER}:{{vendor_id}}",
        "dst_vid": f"{VID_PREFIX_QUALIFICATION}:{{qualification_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "SUPPLIES_ITEM": {
        "source_table": "ods_asl",
        "src_vid": f"{VID_PREFIX_SUPPLIER}:{{vendor_id}}",
        "dst_vid": f"{VID_PREFIX_ITEM}:{{item_id}}",
        "properties": {
            "priority": "priority",
            "unit_price": "unit_price",
            "lead_time_days": "lead_time_days",
            "status": "status",
            "effective_from": "effective_from",
            "effective_to": "effective_to",
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    # ==========================================================================
    # Accounts Payable Domain Edges
    # ==========================================================================
    "HAS_INVOICE_LINE": {
        "source_table": "ods_ap_invoice_line",
        "src_vid": f"{VID_PREFIX_INVOICE}:{{invoice_id}}",
        "dst_vid": f"{VID_PREFIX_INVOICE_LINE}:{{invoice_line_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "INVOICED_BY": {
        "source_table": "ods_ap_invoice",
        "src_vid": f"{VID_PREFIX_INVOICE}:{{invoice_id}}",
        "dst_vid": f"{VID_PREFIX_SUPPLIER}:{{vendor_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "PAYS_INVOICE": {
        "source_table": "ods_ap_invoice_payment",
        "src_vid": f"{VID_PREFIX_PAYMENT}:{{check_id}}",
        "dst_vid": f"{VID_PREFIX_INVOICE}:{{invoice_id}}",
        "properties": {
            "paid_amount": "paid_amount",
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "PAID_TO": {
        "source_table": "ods_ap_payment",
        "src_vid": f"{VID_PREFIX_PAYMENT}:{{check_id}}",
        "dst_vid": f"{VID_PREFIX_SUPPLIER}:{{vendor_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "CONTAINS_PAYMENT": {
        "source_table": "ods_ap_payment",
        "src_vid": f"{VID_PREFIX_PAYMENT_BATCH}:{{batch_id}}",
        "dst_vid": f"{VID_PREFIX_PAYMENT}:{{check_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    # ==========================================================================
    # Order-to-Cash Domain Edges
    # ==========================================================================
    "SOLD_TO": {
        "source_table": "ods_sales_order",
        "src_vid": f"{VID_PREFIX_SO}:{{header_id}}",
        "dst_vid": f"{VID_PREFIX_CUSTOMER}:{{customer_id}}",
        "properties": {
            "order_date": "order_date",
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "HAS_SO_LINE": {
        "source_table": "ods_sales_order_line",
        "src_vid": f"{VID_PREFIX_SO}:{{header_id}}",
        "dst_vid": f"{VID_PREFIX_SO_LINE}:{{line_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "SELLS_ITEM": {
        "source_table": "ods_sales_order_line",
        "src_vid": f"{VID_PREFIX_SO_LINE}:{{line_id}}",
        "dst_vid": f"{VID_PREFIX_ITEM}:{{item_id}}",
        "properties": {
            "quantity": "quantity",
            "unit_price": "unit_price",
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "HAS_SHIPMENT": {
        "source_table": "ods_shipment",
        "src_vid": f"{VID_PREFIX_SO}:{{so_header_id}}",
        "dst_vid": f"{VID_PREFIX_SHIPMENT}:{{delivery_detail_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "HAS_SHIPMENT_LINE": {
        "source_table": "ods_shipment_line",
        "src_vid": f"{VID_PREFIX_SHIPMENT}:{{delivery_detail_id}}",
        "dst_vid": f"{VID_PREFIX_SHIPMENT_LINE}:{{assignment_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "HAS_AR_INVOICE": {
        "source_table": "ods_ar_invoice",
        "src_vid": f"{VID_PREFIX_SO}:{{so_header_id}}",
        "dst_vid": f"{VID_PREFIX_AR_INVOICE}:{{customer_trx_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "RECEIVED_FROM": {
        "source_table": "ods_ar_receipt",
        "src_vid": f"{VID_PREFIX_AR_RECEIPT}:{{cash_receipt_id}}",
        "dst_vid": f"{VID_PREFIX_CUSTOMER}:{{customer_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "APPLIES_TO": {
        "source_table": "ods_ar_receipt_application",
        "src_vid": f"{VID_PREFIX_AR_RECEIPT}:{{cash_receipt_id}}",
        "dst_vid": f"{VID_PREFIX_AR_INVOICE}:{{customer_trx_id}}",
        "properties": {
            "applied_amount": "applied_amount",
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    # ==========================================================================
    # Master Data / Organization Edges
    # ==========================================================================
    "BOM_FOR": {
        "source_table": "ods_bom_header",
        "src_vid": f"{VID_PREFIX_BOM}:{{bom_id}}",
        "dst_vid": f"{VID_PREFIX_ITEM}:{{assembly_item_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "USES_COMPONENT": {
        "source_table": "ods_bom_component",
        "src_vid": f"{VID_PREFIX_BOM_COMP}:{{bom_component_id}}",
        "dst_vid": f"{VID_PREFIX_ITEM}:{{component_item_id}}",
        "properties": {
            "quantity_per": "quantity_per",
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "PARENT_ORG": {
        "source_table": "ods_organization",
        "src_vid": f"{VID_PREFIX_ORG}:{{org_id}}",
        "dst_vid": f"{VID_PREFIX_ORG}:{{parent_org_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "BELONGS_TO_ORG": {
        "source_table": "ods_employee",
        "src_vid": f"{VID_PREFIX_EMPLOYEE}:{{employee_id}}",
        "dst_vid": f"{VID_PREFIX_ORG}:{{org_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "org_id",
        },
    },
    "RECEIVED_AT": {
        "source_table": "ods_receipt",
        "src_vid": f"{VID_PREFIX_RECEIPT}:{{shipment_header_id}}",
        "dst_vid": f"{VID_PREFIX_WAREHOUSE}:{{warehouse_id}}",  # Would need warehouse_id lookup
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "SHIPPED_FROM": {
        "source_table": "ods_shipment",
        "src_vid": f"{VID_PREFIX_SHIPMENT}:{{delivery_detail_id}}",
        "dst_vid": f"{VID_PREFIX_WAREHOUSE}:{{warehouse_id}}",  # Would need warehouse_id lookup
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    # ==========================================================================
    # Accounting Domain Edges
    # ==========================================================================
    "ACCOUNTING_FOR": {
        "source_table": "ods_xla_event",
        "src_vid": f"{VID_PREFIX_XLA_EVENT}:{{event_id}}",
        "dst_vid": f"{VID_PREFIX_XLA_EVENT}:{{source_doc_id}}",  # Polymorphic
        "properties": {
            "event_class": "event_class",
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "POSTED_TO": {
        "source_table": "ods_gl_journal_line",
        "src_vid": f"{VID_PREFIX_JOURNAL_LINE}:{{je_line_id}}",
        "dst_vid": f"{VID_PREFIX_GL_ACCOUNT}:{{code_combination_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "HAS_JOURNAL_LINE": {
        "source_table": "ods_gl_journal_line",
        "src_vid": f"{VID_PREFIX_JOURNAL}:{{je_header_id}}",
        "dst_vid": f"{VID_PREFIX_JOURNAL_LINE}:{{je_line_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "DISTRIBUTED_TO": {
        "source_table": "ods_xla_distribution",
        "src_vid": f"{VID_PREFIX_XLA_EVENT}:{{event_id}}",
        "dst_vid": f"{VID_PREFIX_GL_ACCOUNT}:{{code_combination_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    # ==========================================================================
    # Approval / Contract Edges
    # ==========================================================================
    "APPROVED_BY": {
        "source_table": "ods_approval_record",
        "src_vid": f"{VID_PREFIX_APPROVAL}:{{approval_id}}",
        "dst_vid": f"{VID_PREFIX_EMPLOYEE}:{{approver_id}}",
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "APPROVAL_FOR": {
        "source_table": "ods_approval_record",
        "src_vid": f"{VID_PREFIX_APPROVAL}:{{approval_id}}",
        "dst_vid": f"{VID_PREFIX_APPROVAL}:{{doc_header_id}}",  # Polymorphic by doc_type
        "properties": {
            "doc_type": "doc_type",
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "CONTRACT_WITH": {
        "source_table": "ods_contract",
        "src_vid": f"{VID_PREFIX_CONTRACT}:{{contract_id}}",
        "dst_vid": f"{VID_PREFIX_SUPPLIER}:{{party_id}}",  # Or Customer, polymorphic
        "properties": {
            "party_type": "party_type",
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
    "UNDER_CONTRACT": {
        "source_table": "ods_purchase_order",
        "src_vid": f"{VID_PREFIX_PO}:{{po_header_id}}",
        "dst_vid": f"{VID_PREFIX_CONTRACT}:{{contract_id}}",  # Would need contract_id on PO
        "properties": {
            "org_id": "org_id",
            "dept_id": "NULL",
        },
    },
}


# =============================================================================
# Transformation Result
# =============================================================================


@dataclass
class TransformResult:
    """Result of a transformation operation."""

    success: bool
    output_path: str | None = None
    records_processed: int = 0
    records_written: int = 0
    error_message: str | None = None

    def __bool__(self) -> bool:
        return self.success


# =============================================================================
# Graph Transformer
# =============================================================================


class GraphTransformer:
    """
    Transforms ODS data into NebulaGraph import format.

    Converts PostgreSQL ODS tables into CSV files suitable for
    nebula-importer, handling VID generation and property mapping.

    Example:
        >>> transformer = GraphTransformer(
        ...     postgres_dsn="postgresql://user:pass@localhost/ods",
        ...     output_dir="/tmp/import"
        ... )
        >>> result = await transformer.transform_vertices("Supplier", batch_id="ETL-20260404-001")
        >>> print(f"Generated: {result.output_path}")
    """

    def __init__(
        self,
        postgres_dsn: str,
        output_dir: str = "import",
    ):
        """
        Initialize the GraphTransformer.

        Args:
            postgres_dsn: PostgreSQL connection string for ODS database
            output_dir: Directory to write CSV import files
        """
        self.postgres_dsn = postgres_dsn
        self.output_dir = Path(output_dir)
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        """Connect to the ODS PostgreSQL database."""
        self._pool = await asyncpg.create_pool(
            self.postgres_dsn, min_size=2, max_size=10
        )
        logger.info("etl_transformer_connected", dsn=self.postgres_dsn)

    async def disconnect(self) -> None:
        """Disconnect from the ODS PostgreSQL database."""
        if self._pool:
            await self._pool.close()
            self._pool = None
        logger.info("etl_transformer_disconnected")

    async def transform_vertices(
        self,
        tag: str,
        batch_id: str,
        incremental: bool = True,
    ) -> TransformResult:
        """
        Transform ODS data for a specific vertex tag.

        Args:
            tag: Vertex tag name (e.g., 'Supplier', 'PurchaseOrder')
            batch_id: ETL batch identifier
            incremental: If True, only transform records for this batch_id

        Returns:
            TransformResult with output path and statistics
        """
        if tag not in VERTEX_MAPPINGS:
            return TransformResult(
                success=False,
                error_message=f"Unknown vertex tag: {tag}",
            )

        mapping = VERTEX_MAPPINGS[tag]
        source_table = mapping["source_table"]

        # Build output directory for this batch
        batch_dir = self.output_dir / batch_id
        batch_dir.mkdir(parents=True, exist_ok=True)
        output_path = batch_dir / f"vertex_{tag}.csv"

        try:
            # Build SELECT query
            select_sql = self._build_vertex_select(mapping, batch_id, incremental)
            logger.info(
                "transform_vertices_start",
                tag=tag,
                table=source_table,
                batch_id=batch_id,
                output=str(output_path),
            )

            # Execute query and write CSV
            records_processed = 0
            records_written = 0

            headers = [":VID"] + list(mapping["properties"].keys())
            with open(output_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                assert self._pool is not None
                async with self._pool.acquire() as conn:
                    async with conn.transaction():
                        async for row in conn.cursor(select_sql, batch_id):
                            records_processed += 1
                            row_dict = dict(row)
                            vid = self._generate_vid(mapping["vid_template"], row_dict)
                            values = [vid] + [
                                self._format_value(row_dict.get(prop))
                                for prop in mapping["properties"].values()
                            ]
                            writer.writerow(values)
                            records_written += 1

            logger.info(
                "transform_vertices_complete",
                tag=tag,
                records_processed=records_processed,
                records_written=records_written,
            )

            return TransformResult(
                success=True,
                output_path=str(output_path),
                records_processed=records_processed,
                records_written=records_written,
            )

        except Exception as e:
            logger.error(
                "transform_vertices_failed",
                tag=tag,
                error=str(e),
            )
            return TransformResult(
                success=False,
                error_message=str(e),
            )

    async def transform_edges(
        self,
        edge_type: str,
        batch_id: str,
        incremental: bool = True,
    ) -> TransformResult:
        """
        Transform ODS data for a specific edge type.

        Args:
            edge_type: Edge type name (e.g., 'PLACED_WITH', 'HAS_PO_LINE')
            batch_id: ETL batch identifier
            incremental: If True, only transform records for this batch_id

        Returns:
            TransformResult with output path and statistics
        """
        if edge_type not in EDGE_MAPPINGS:
            return TransformResult(
                success=False,
                error_message=f"Unknown edge type: {edge_type}",
            )

        mapping = EDGE_MAPPINGS[edge_type]
        source_table = mapping["source_table"]

        # Build output directory for this batch
        batch_dir = self.output_dir / batch_id
        batch_dir.mkdir(parents=True, exist_ok=True)
        output_path = batch_dir / f"edge_{edge_type}.csv"

        try:
            # Build SELECT query
            select_sql = self._build_edge_select(mapping, batch_id, incremental)
            logger.info(
                "transform_edges_start",
                edge_type=edge_type,
                table=source_table,
                batch_id=batch_id,
                output=str(output_path),
            )

            # Execute query and write CSV
            records_processed = 0
            records_written = 0

            headers = [":SRC_VID", ":DST_VID"] + list(mapping["properties"].keys())
            with open(output_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                assert self._pool is not None
                async with self._pool.acquire() as conn:
                    async with conn.transaction():
                        async for row in conn.cursor(select_sql, batch_id):
                            records_processed += 1
                            row_dict = dict(row)
                            src_vid = self._generate_vid(mapping["src_vid"], row_dict)
                            dst_vid = self._generate_vid(mapping["dst_vid"], row_dict)
                            values = [src_vid, dst_vid] + [
                                self._format_value(row_dict.get(prop))
                                for prop in mapping["properties"].values()
                            ]
                            writer.writerow(values)
                            records_written += 1

            logger.info(
                "transform_edges_complete",
                edge_type=edge_type,
                records_processed=records_processed,
                records_written=records_written,
            )

            return TransformResult(
                success=True,
                output_path=str(output_path),
                records_processed=records_processed,
                records_written=records_written,
            )

        except Exception as e:
            logger.error(
                "transform_edges_failed",
                edge_type=edge_type,
                error=str(e),
            )
            return TransformResult(
                success=False,
                error_message=str(e),
            )

    async def transform_all(
        self,
        batch_id: str,
        incremental: bool = True,
    ) -> dict[str, TransformResult]:
        """
        Transform all vertex tags and edge types.

        Args:
            batch_id: ETL batch identifier
            incremental: If True, only transform records for this batch_id

        Returns:
            Dict mapping tag/edge names to their TransformResults
        """
        results: dict[str, TransformResult] = {}

        # Transform all vertices
        for tag in VERTEX_MAPPINGS:
            results[tag] = await self.transform_vertices(tag, batch_id, incremental)

        # Transform all edges
        for edge_type in EDGE_MAPPINGS:
            results[edge_type] = await self.transform_edges(edge_type, batch_id, incremental)

        return results

    def _build_vertex_select(
        self,
        mapping: dict[str, Any],
        batch_id: str,
        incremental: bool,
    ) -> str:
        """Build SELECT SQL for vertex transformation."""
        source_table = mapping["source_table"]
        properties = mapping["properties"]

        # Build property list
        prop_list = []
        for alias, col_or_expr in properties.items():
            if col_or_expr == "NULL":
                prop_list.append("NULL as " + alias)
            elif col_or_expr.startswith("CASE"):
                prop_list.append(f"{col_or_expr} as {alias}")
            elif col_or_expr.startswith("'"):
                # Literal string value
                prop_list.append(f"{col_or_expr} as {alias}")
            else:
                prop_list.append(col_or_expr + " as " + alias)

        sql = f"""
            SELECT {', '.join(prop_list)}
            FROM {source_table}
            WHERE etl_batch_id = $1
        """

        if incremental:
            sql += " AND dq_status = 'passed'"

        return sql

    def _build_edge_select(
        self,
        mapping: dict[str, Any],
        batch_id: str,
        incremental: bool,
    ) -> str:
        """Build SELECT SQL for edge transformation."""
        source_table = mapping["source_table"]
        properties = mapping["properties"]

        # Build property list
        prop_list = []
        for alias, col_or_expr in properties.items():
            if col_or_expr == "NULL":
                prop_list.append("NULL as " + alias)
            elif col_or_expr == "org_id":
                prop_list.append(f"{col_or_expr} as {alias}")
            else:
                prop_list.append(col_or_expr + " as " + alias)

        sql = f"""
            SELECT {', '.join(prop_list)}
            FROM {source_table}
            WHERE etl_batch_id = $1
        """

        if incremental:
            sql += " AND dq_status = 'passed'"

        return sql

    def _generate_vid(self, template: str, row: dict[str, Any]) -> str:
        """
        Generate a VID from a template and row data.

        Args:
            template: VID template (e.g., "SUP:{vendor_id}")
            row: Row data dictionary

        Returns:
            Generated VID string
        """
        try:
            return template.format(**row)
        except KeyError as e:
            logger.warning("vid_generation_key_error", template=template, missing_key=str(e))
            return template.format(**{k: row.get(k, "") for k in row})

    def _format_value(self, value: Any) -> str:
        """Format a value for CSV output."""
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def get_import_files(self, batch_id: str) -> dict[str, list[str]]:
        """
        Get all generated import files for a batch.

        Args:
            batch_id: ETL batch identifier

        Returns:
            Dict with 'vertices' and 'edges' keys, each containing list of file paths
        """
        batch_dir = self.output_dir / batch_id
        if not batch_dir.exists():
            return {"vertices": [], "edges": []}

        vertices = []
        edges = []

        for f in batch_dir.iterdir():
            if f.suffix == ".csv":
                if f.name.startswith("vertex_"):
                    vertices.append(str(f))
                elif f.name.startswith("edge_"):
                    edges.append(str(f))

        return {"vertices": sorted(vertices), "edges": sorted(edges)}
