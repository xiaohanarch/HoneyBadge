"""Permission service configuration and process tags."""
from .models import PermissionContext

PROCESS_TAGS: dict[str, set[str]] = {
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
        "Organization", "Employee", "Supplier", "SupplierSite",
        "Customer", "CustomerSite", "Item",
        "Warehouse", "BOM", "BOMComponent", "Currency", "UOM",
        "GLAccount", "GLJournalEntry", "GLJournalLine",
        "XLAEvent", "AccountingDistribution", "ApprovalRecord",
    },
}

# MASTER tags that have org_id and should be org-filtered for non-admin users.
# These are business entities org-scoped in ERP (each org has its own suppliers,
# customers, items, etc.), not global reference data like Currency/UOM.
ORG_SCOPED_MASTER_TAGS: set[str] = {
    "Supplier", "SupplierSite",
    "Customer", "CustomerSite",
    "Item",
    "Employee",
    "Warehouse",
    "BOM", "BOMComponent",
}

PERMISSION_CONFIG: dict[str, PermissionContext] = {
    "admin": PermissionContext(
        user_id="admin",
        allowed_processes=["PTP", "OTC"],
        org_ids=None,
        dept_ids=None,
        data_scope="ALL",
    ),
    "procurement_lead": PermissionContext(
        user_id="procurement_lead",
        allowed_processes=["PTP"],
        org_ids=None,
        dept_ids=None,
        data_scope="ALL",
    ),
    "subsidiary_lead": PermissionContext(
        user_id="subsidiary_lead",
        allowed_processes=["PTP", "OTC"],
        org_ids=[1021],
        dept_ids=None,
        data_scope="ORG",
    ),
    "analyst": PermissionContext(
        user_id="analyst",
        allowed_processes=["PTP"],
        org_ids=[1000],
        dept_ids=None,
        data_scope="ORG",
    ),
    "auditor": PermissionContext(
        user_id="auditor",
        allowed_processes=["PTP", "OTC"],
        org_ids=None,
        dept_ids=None,
        data_scope="ALL",
    ),
}
