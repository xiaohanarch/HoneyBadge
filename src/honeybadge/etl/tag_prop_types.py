"""NebulaGraph property type mappings for PTP tags and edges.

Hardcoded mapping of {prop_name: nebula_type} for the 9 PTP main-chain
vertex tags and their associated edge types. Extracted from
deploy/docker/nebula-schema.ngql and nebula-edges.ngql.

Used by run_pipeline._generate_minimal_config() to dynamically build
the nebula-importer YAML `files` section with correct property types.

NebulaGraph types: STRING, INT64, DOUBLE, TIMESTAMP, BOOL, DATE, DATETIME
"""

# =============================================================================
# Vertex Tag Property Types
# =============================================================================

TAG_PROP_TYPES: dict[str, dict[str, str]] = {
    "Organization": {
        "org_code": "STRING",
        "org_name": "STRING",
        "org_type": "STRING",
        "parent_org_code": "STRING",
        "legal_entity": "STRING",
        "country": "STRING",
        "city": "STRING",
        "status": "STRING",
        "org_id": "INT64",
        "dept_id": "INT64",
        "data_scope": "STRING",
        "created_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP",
        "etl_batch_id": "STRING",
        "source_system": "STRING",
        "is_active": "BOOL",
    },
    "Supplier": {
        "supplier_number": "STRING",
        "supplier_name": "STRING",
        "supplier_type": "STRING",
        "status": "STRING",
        "country": "STRING",
        "city": "STRING",
        "address": "STRING",
        "contact_person": "STRING",
        "contact_phone": "STRING",
        "contact_email": "STRING",
        "bank_account": "STRING",
        "bank_name": "STRING",
        "tax_id": "STRING",
        "currency": "STRING",
        "payment_terms": "STRING",
        "credit_rating": "STRING",
        "registration_date": "TIMESTAMP",
        "qualification_expiry": "TIMESTAMP",
        "org_id": "INT64",
        "dept_id": "INT64",
        "data_scope": "STRING",
        "created_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP",
        "etl_batch_id": "STRING",
        "source_system": "STRING",
        "is_active": "BOOL",
    },
    "Item": {
        "item_number": "STRING",
        "item_name": "STRING",
        "item_description": "STRING",
        "item_type": "STRING",
        "category": "STRING",
        "uom": "STRING",
        "standard_cost": "DOUBLE",
        "list_price": "DOUBLE",
        "weight": "DOUBLE",
        "weight_uom": "STRING",
        "lead_time_days": "INT64",
        "safety_stock": "DOUBLE",
        "min_order_qty": "DOUBLE",
        "status": "STRING",
        "abc_class": "STRING",
        "org_id": "INT64",
        "dept_id": "INT64",
        "data_scope": "STRING",
        "created_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP",
        "etl_batch_id": "STRING",
        "source_system": "STRING",
        "is_active": "BOOL",
    },
    "PurchaseOrder": {
        "po_number": "STRING",
        "po_type": "STRING",
        "description": "STRING",
        "status": "STRING",
        "buyer": "STRING",
        "order_date": "TIMESTAMP",
        "approved_date": "TIMESTAMP",
        "total_amount": "DOUBLE",
        "currency": "STRING",
        "exchange_rate": "DOUBLE",
        "payment_terms": "STRING",
        "freight_terms": "STRING",
        "ship_to_location": "STRING",
        "bill_to_location": "STRING",
        "close_date": "TIMESTAMP",
        "cancel_reason": "STRING",
        "org_id": "INT64",
        "dept_id": "INT64",
        "data_scope": "STRING",
        "created_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP",
        "etl_batch_id": "STRING",
        "source_system": "STRING",
        "is_active": "BOOL",
    },
    "PurchaseOrderLine": {
        "line_number": "INT64",
        "line_type": "STRING",
        "quantity": "DOUBLE",
        "unit_price": "DOUBLE",
        "amount": "DOUBLE",
        "uom": "STRING",
        "need_by_date": "TIMESTAMP",
        "promised_date": "TIMESTAMP",
        "received_quantity": "DOUBLE",
        "invoiced_quantity": "DOUBLE",
        "status": "STRING",
        "tax_code": "STRING",
        "tax_rate": "DOUBLE",
        "org_id": "INT64",
        "dept_id": "INT64",
        "data_scope": "STRING",
        "created_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP",
        "etl_batch_id": "STRING",
        "source_system": "STRING",
        "is_active": "BOOL",
    },
    "Receipt": {
        "receipt_number": "STRING",
        "receipt_type": "STRING",
        "receipt_date": "TIMESTAMP",
        "status": "STRING",
        "receiver": "STRING",
        "total_quantity": "DOUBLE",
        "warehouse": "STRING",
        "comments": "STRING",
        "org_id": "INT64",
        "dept_id": "INT64",
        "data_scope": "STRING",
        "created_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP",
        "etl_batch_id": "STRING",
        "source_system": "STRING",
        "is_active": "BOOL",
    },
    "ReceiptLine": {
        "line_number": "INT64",
        "received_quantity": "DOUBLE",
        "accepted_quantity": "DOUBLE",
        "rejected_quantity": "DOUBLE",
        "uom": "STRING",
        "inspection_status": "STRING",
        "lot_number": "STRING",
        "sublocation": "STRING",
        "org_id": "INT64",
        "dept_id": "INT64",
        "data_scope": "STRING",
        "created_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP",
        "etl_batch_id": "STRING",
        "source_system": "STRING",
        "is_active": "BOOL",
    },
    "Invoice": {
        "invoice_number": "STRING",
        "invoice_type": "STRING",
        "invoice_date": "TIMESTAMP",
        "due_date": "TIMESTAMP",
        "status": "STRING",
        "total_amount": "DOUBLE",
        "tax_amount": "DOUBLE",
        "currency": "STRING",
        "exchange_rate": "DOUBLE",
        "payment_method": "STRING",
        "description": "STRING",
        "gl_date": "TIMESTAMP",
        "pay_group": "STRING",
        "source": "STRING",
        "org_id": "INT64",
        "dept_id": "INT64",
        "data_scope": "STRING",
        "created_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP",
        "etl_batch_id": "STRING",
        "source_system": "STRING",
        "is_active": "BOOL",
    },
    "InvoiceLine": {
        "line_number": "INT64",
        "line_type": "STRING",
        "quantity": "DOUBLE",
        "unit_price": "DOUBLE",
        "amount": "DOUBLE",
        "tax_code": "STRING",
        "tax_rate": "DOUBLE",
        "description": "STRING",
        "org_id": "INT64",
        "dept_id": "INT64",
        "data_scope": "STRING",
        "created_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP",
        "etl_batch_id": "STRING",
        "source_system": "STRING",
        "is_active": "BOOL",
    },
}

# =============================================================================
# Edge Property Types
# =============================================================================

EDGE_PROP_TYPES: dict[str, dict[str, str]] = {
    "PLACED_WITH": {
        "order_date": "TIMESTAMP",
        "org_id": "INT64",
        "dept_id": "INT64",
    },
    "HAS_PO_LINE": {
        "org_id": "INT64",
        "dept_id": "INT64",
    },
    "ORDERS_ITEM": {
        "quantity": "DOUBLE",
        "unit_price": "DOUBLE",
        "org_id": "INT64",
        "dept_id": "INT64",
    },
    "HAS_RECEIPT": {
        "org_id": "INT64",
        "dept_id": "INT64",
    },
    "HAS_RECEIPT_LINE": {
        "org_id": "INT64",
        "dept_id": "INT64",
    },
    "HAS_INVOICE": {
        "match_status": "STRING",
        "match_date": "TIMESTAMP",
        "org_id": "INT64",
        "dept_id": "INT64",
    },
    "HAS_INVOICE_LINE": {
        "org_id": "INT64",
        "dept_id": "INT64",
    },
    "INVOICED_BY": {
        "org_id": "INT64",
        "dept_id": "INT64",
    },
    "ORDERED_BY": {
        "org_id": "INT64",
        "dept_id": "INT64",
    },
    "RECEIVED_AT": {
        "org_id": "INT64",
        "dept_id": "INT64",
    },
    "PARENT_ORG": {
        "org_id": "INT64",
        "dept_id": "INT64",
    },
    "BELONGS_TO_ORG": {
        "org_id": "INT64",
        "dept_id": "INT64",
    },
}

# PTP vertex tags (9) — used to filter which tags get importer config
PTP_TAGS = {
    "Organization",
    "Supplier",
    "Item",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "Receipt",
    "ReceiptLine",
    "Invoice",
    "InvoiceLine",
}

# PTP edge types — used to filter which edges get importer config
PTP_EDGES = {
    "PLACED_WITH",
    "HAS_PO_LINE",
    "ORDERS_ITEM",
    "HAS_RECEIPT",
    "HAS_RECEIPT_LINE",
    "HAS_INVOICE",
    "HAS_INVOICE_LINE",
    "INVOICED_BY",
    "ORDERED_BY",
    "RECEIVED_AT",
    "PARENT_ORG",
    "BELONGS_TO_ORG",
}


def get_tag_prop_type(tag: str, prop: str) -> str:
    """Get NebulaGraph property type for a tag property.

    Falls back to STRING if the (tag, prop) pair is not in the mapping table.
    """
    return TAG_PROP_TYPES.get(tag, {}).get(prop, "STRING")


def get_edge_prop_type(edge: str, prop: str) -> str:
    """Get NebulaGraph property type for an edge property.

    Falls back to STRING if the (edge, prop) pair is not in the mapping table.
    """
    return EDGE_PROP_TYPES.get(edge, {}).get(prop, "STRING")
