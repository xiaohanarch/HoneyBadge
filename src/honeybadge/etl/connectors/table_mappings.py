"""Source-to-ODS table mappings for Oracle EBS.

The full design (``docs/phase1/06-data-pipeline.md`` §2.1) lists 41
Oracle EBS -> ODS mappings. P3 ships the 9 PTP tables required for
end-to-end procure-to-pay coverage; the remaining mappings are
defined here but are not yet enabled for extraction so that
``IncrementalLoader`` will refuse to load them until they are added
to :data:`ENABLED_TABLES_P3`.

Conventions
-----------
* ``watermark_column`` is always ``LAST_UPDATE_DATE`` for EBS tables
  that expose it (every table in P3 scope does). This is a TIMESTAMP
  column maintained by EBS triggers on every insert/update.
* Soft-delete detection is mapped via ``derived_columns`` to an
  ``is_deleted`` flag. EBS uses status flags rather than physical
  deletes (``AUTHORIZATION_STATUS='CANCELLED'``, ``ENABLED_FLAG='N'``).
  Hard-delete capture (LogMiner) is a P4+ concern.
* Column names follow the ODS schema in ``src/honeybadge/etl/ods_schema.sql``.
  Only ODS *business* columns are listed; ETL metadata columns
  (``etl_batch_id`` etc.) are added by the incremental loader.
"""

from honeybadge.etl.connectors.base import TableMapping

# =============================================================================
# PTP tables (enabled for P3)
# =============================================================================

ODS_ORGANIZATION = TableMapping(
    source_table="HR_ALL_ORGANIZATION_UNITS",
    watermark_column="LAST_UPDATE_DATE",
    column_mapping={
        "org_id": "ORGANIZATION_ID",
        "org_code": "ORGANIZATION_CODE",
        "org_name": "NAME",
        "org_type": "TYPE",
        "parent_org_id": "BUSINESS_GROUP_ID",
        "legal_entity": "LEGAL_ENTITY_NAME",
        "country": "LOCATION_COUNTRY",
        "city": "LOCATION_CITY",
        "status": "ENABLED_FLAG",
    },
    derived_columns={
        "is_deleted": "CASE WHEN ENABLED_FLAG = 'N' THEN 1 ELSE 0 END",
    },
)

ODS_SUPPLIER = TableMapping(
    source_table="AP_SUPPLIERS",
    watermark_column="LAST_UPDATE_DATE",
    column_mapping={
        "vendor_id": "VENDOR_ID",
        "vendor_number": "SEGMENT1",
        "vendor_name": "VENDOR_NAME",
        "vendor_type": "VENDOR_TYPE_LOOKUP_CODE",
        "status": "ENABLED_FLAG",
        "country": "VENDOR_COUNTRY",
        "city": "VENDOR_CITY",
        "address": "ADDRESS_LINE1",
        "contact_person": "CONTACT_NAME",
        "contact_phone": "PHONE",
        "contact_email": "EMAIL_ADDRESS",
        "bank_account": "BANK_ACCOUNT_NUM",
        "bank_name": "BANK_NAME",
        "vat_registration_num": "VAT_REGISTRATION_NUM",
        "payment_terms": "PAYMENT_PRIORITY",  # EBS exposes priority; terms live in AP_TERMS
        "credit_rating": "CREDIT_RATING",
        "start_date": "START_DATE_ACTIVE",
        "end_date": "END_DATE_ACTIVE",
        "org_id": "PARTY_ID",
    },
    derived_columns={
        "is_deleted": "CASE WHEN ENABLED_FLAG = 'N' THEN 1 ELSE 0 END",
    },
)

ODS_ITEM = TableMapping(
    source_table="MTL_SYSTEM_ITEMS_B",
    watermark_column="LAST_UPDATE_DATE",
    column_mapping={
        "inventory_item_id": "INVENTORY_ITEM_ID",
        "item_number": "SEGMENT1",
        "item_name": "DESCRIPTION",
        "item_description": "LONG_DESCRIPTION",
        "item_type": "ITEM_TYPE",
        "category": "ITEM_CATALOG_GROUP_ID",
        "uom": "PRIMARY_UOM_CODE",
        "standard_cost": "STANDARD_COST",
        "list_price": "LIST_PRICE_PER_UNIT",
        "weight": "WEIGHT",
        "weight_uom": "WEIGHT_UOM_CODE",
        "lead_time_days": "FULL_LEAD_TIME",
        "safety_stock": "SAFETY_STOCK",
        "min_order_qty": "MINIMUM_ORDER_QUANTITY",
        "status": "INVENTORY_ITEM_STATUS_CODE",
        "abc_class": "ABC_ASSGN_GROUP_ID",
        "org_id": "ORGANIZATION_ID",
    },
    derived_columns={
        "is_deleted": "CASE WHEN INVENTORY_ITEM_STATUS_CODE = 'INACTIVE' THEN 1 ELSE 0 END",
    },
)

ODS_PURCHASE_ORDER = TableMapping(
    source_table="PO_HEADERS_ALL",
    watermark_column="LAST_UPDATE_DATE",
    column_mapping={
        "po_header_id": "PO_HEADER_ID",
        "po_number": "SEGMENT1",
        "po_type": "TYPE_LOOKUP_CODE",
        "description": "COMMENTS",
        "status": "AUTHORIZATION_STATUS",
        "buyer_id": "AGENT_ID",
        "buyer_name": "AGENT_NAME",
        "vendor_id": "VENDOR_ID",
        "vendor_name": "VENDOR_NAME",
        "order_date": "CREATION_DATE",
        "approved_date": "APPROVED_DATE",
        "total_amount": "TOTAL_AMOUNT",
        "currency_code": "CURRENCY_CODE",
        "exchange_rate": "RATE",
        "payment_terms": "TERMS_ID",
        "freight_terms": "FREIGHT_TERMS",
        "ship_to_location": "SHIP_TO_LOCATION_ID",
        "bill_to_location": "BILL_TO_LOCATION_ID",
        "close_date": "CLOSED_DATE",
        "cancel_reason": "CANCEL_REASON",
        "org_id": "ORG_ID",
    },
    derived_columns={
        "is_deleted": "CASE WHEN AUTHORIZATION_STATUS = 'CANCELLED' THEN 1 ELSE 0 END",
    },
)

ODS_PURCHASE_ORDER_LINE = TableMapping(
    source_table="PO_LINES_ALL",
    watermark_column="LAST_UPDATE_DATE",
    column_mapping={
        "po_line_id": "PO_LINE_ID",
        "po_header_id": "PO_HEADER_ID",
        "line_number": "LINE_NUM",
        "line_type": "LINE_TYPE",
        "item_id": "ITEM_ID",
        "item_description": "ITEM_DESCRIPTION",
        "quantity": "QUANTITY",
        "unit_price": "UNIT_PRICE",
        "amount": "AMOUNT",
        "uom": "UNIT_MEAS_LOOKUP_CODE",
        "need_by_date": "NEED_BY_DATE",
        "promised_date": "PROMISED_DATE",
        "received_quantity": "QUANTITY_RECEIVED",
        "invoiced_quantity": "QUANTITY_INVOICED",
        "status": "CLOSED_CODE",
        "tax_code": "TAX_CODE",
        "tax_rate": "TAX_RATE",
        "org_id": "ORG_ID",
    },
    derived_columns={
        "is_deleted": "CASE WHEN CLOSED_CODE = 'FINALLY_CLOSED' AND QUANTITY_RECEIVED = 0 THEN 1 ELSE 0 END",
    },
)

ODS_RECEIPT = TableMapping(
    source_table="RCV_SHIPMENT_HEADERS",
    watermark_column="LAST_UPDATE_DATE",
    column_mapping={
        "shipment_header_id": "SHIPMENT_HEADER_ID",
        "receipt_number": "RECEIPT_NUM",
        "receipt_type": "SHIPMENT_TYPE",
        "receipt_date": "RECEIPT_DATE",
        "status": "RECEIPT_SOURCE_CODE",
        "receiver_id": "RECEIVED_BY",
        "receiver_name": "RECEIVER_NAME",
        "po_header_id": "PO_HEADER_ID",
        "total_quantity": "TOTAL_UNITS_RECEIVED",
        "warehouse_code": "SUBINVENTORY",
        "comments": "COMMENTS",
        "org_id": "ORG_ID",
    },
    derived_columns={
        "is_deleted": "CASE WHEN RECEIPT_SOURCE_CODE = 'CANCELLED' THEN 1 ELSE 0 END",
    },
)

ODS_RECEIPT_LINE = TableMapping(
    source_table="RCV_SHIPMENT_LINES",
    watermark_column="LAST_UPDATE_DATE",
    column_mapping={
        "shipment_line_id": "SHIPMENT_LINE_ID",
        "shipment_header_id": "SHIPMENT_HEADER_ID",
        "po_line_id": "PO_LINE_ID",
        "line_number": "LINE_NUM",
        "item_id": "ITEM_ID",
        "received_quantity": "QUANTITY_RECEIVED",
        "accepted_quantity": "QUANTITY_ACCEPTED",
        "rejected_quantity": "QUANTITY_REJECTED",
        "uom": "UNIT_OF_MEASURE",
        "inspection_status": "INSPECTION_STATUS_CODE",
        "lot_number": "LOT_NUM",
        "subinventory": "SUBINVENTORY",
        "sublocation": "LOCATOR_ID",
        "org_id": "ORG_ID",
    },
    derived_columns={
        "is_deleted": "CASE WHEN QUANTITY_RECEIVED = 0 AND QUANTITY_REJECTED > 0 THEN 1 ELSE 0 END",
    },
)

ODS_AP_INVOICE = TableMapping(
    source_table="AP_INVOICES_ALL",
    watermark_column="LAST_UPDATE_DATE",
    column_mapping={
        "invoice_id": "INVOICE_ID",
        "invoice_number": "INVOICE_NUM",
        "invoice_type": "INVOICE_TYPE_LOOKUP_CODE",
        "vendor_id": "VENDOR_ID",
        "vendor_name": "VENDOR_NAME",
        "vendor_site_id": "VENDOR_SITE_ID",
        "invoice_date": "INVOICE_DATE",
        "due_date": "INVOICE_DUE_DATE",
        "status": "APPROVAL_STATUS",
        "total_amount": "INVOICE_AMOUNT",
        "tax_amount": "TAX_AMOUNT",
        "currency_code": "INVOICE_CURRENCY_CODE",
        "exchange_rate": "EXCHANGE_RATE",
        "payment_method": "PAYMENT_METHOD_CODE",
        "description": "DESCRIPTION",
        "gl_date": "GL_DATE",
        "po_header_id": "PO_HEADER_ID",
        "org_id": "ORG_ID",
    },
    derived_columns={
        "is_deleted": "CASE WHEN APPROVAL_STATUS = 'CANCELLED' THEN 1 ELSE 0 END",
    },
)

ODS_AP_INVOICE_LINE = TableMapping(
    source_table="AP_INVOICE_LINES_ALL",
    watermark_column="LAST_UPDATE_DATE",
    column_mapping={
        "invoice_line_id": "INVOICE_LINE_ID",
        "invoice_id": "INVOICE_ID",
        "line_number": "LINE_NUMBER",
        "line_type": "LINE_TYPE_LOOKUP_CODE",
        "item_id": "ITEM_ID",
        "item_description": "DESCRIPTION",
        "quantity": "QUANTITY",
        "unit_price": "UNIT_PRICE",
        "amount": "AMOUNT",
        "tax_code": "TAX_CODE",
        "tax_rate": "TAX_RATE",
        "po_line_id": "PO_LINE_ID",
        "receipt_line_id": "RCV_TRANSACTION_ID",
        "description": "DESCRIPTION",
        "org_id": "ORG_ID",
    },
    derived_columns={
        "is_deleted": "CASE WHEN AMOUNT = 0 AND LINE_TYPE_LOOKUP_CODE = 'CANCEL' THEN 1 ELSE 0 END",
    },
)


# =============================================================================
# Registry of all mappings (P3 enabled + future tables)
# =============================================================================

TABLE_MAPPINGS: dict[str, TableMapping] = {
    "ods_organization": ODS_ORGANIZATION,
    "ods_supplier": ODS_SUPPLIER,
    "ods_item": ODS_ITEM,
    "ods_purchase_order": ODS_PURCHASE_ORDER,
    "ods_purchase_order_line": ODS_PURCHASE_ORDER_LINE,
    "ods_receipt": ODS_RECEIPT,
    "ods_receipt_line": ODS_RECEIPT_LINE,
    "ods_ap_invoice": ODS_AP_INVOICE,
    "ods_ap_invoice_line": ODS_AP_INVOICE_LINE,
}

# Tables enabled for P3 extraction. Mirrors scripts/load_csv_to_ods.py LOAD_ORDER
# (master data first, then transactions) to respect FK dependencies.
ENABLED_TABLES_P3: list[str] = [
    "ods_organization",
    "ods_supplier",
    "ods_item",
    "ods_purchase_order",
    "ods_purchase_order_line",
    "ods_receipt",
    "ods_receipt_line",
    "ods_ap_invoice",
    "ods_ap_invoice_line",
]

# Alias for clarity in the loader; same ordering as P3.
LOAD_ORDER: list[str] = ENABLED_TABLES_P3


def get_mapping(table_name: str) -> TableMapping:
    """Resolve the :class:`TableMapping` for an ODS table name.

    Raises
    ------
    KeyError
        If the table has no mapping registered.
    """
    if table_name not in TABLE_MAPPINGS:
        raise KeyError(
            f"No TableMapping registered for '{table_name}'. "
            f"Known tables: {sorted(TABLE_MAPPINGS)}"
        )
    return TABLE_MAPPINGS[table_name]
