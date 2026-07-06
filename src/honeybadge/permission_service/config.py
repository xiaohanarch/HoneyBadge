"""Permission service configuration and process tags.

PERMISSION_CONFIG is loaded from a YAML file when the
``HONEYBADGE_PERMISSIONS_CONFIG`` environment variable points to one;
otherwise the built-in demo defaults below are used. This keeps the
module import-safe (no YAML file required for dev/test) while allowing
production deployments to externalize user permissions without code
changes.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

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

_DEFAULT_PERMISSION_CONFIG: dict[str, PermissionContext] = {
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


def _load_permissions_from_yaml(path: str | Path) -> dict[str, PermissionContext]:
    """Load permission config from a YAML file.

    The YAML schema mirrors deploy/config/permissions.yaml:
    ``permissions: <user_id>: { user_id, allowed_processes, org_ids, dept_ids, data_scope }``.

    Args:
        path: Path to the YAML file.

    Returns:
        A dict mapping user_id to PermissionContext.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is malformed or missing required keys.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Permissions config file not found: {p}")

    with p.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict) or "permissions" not in data:
        raise ValueError(f"Invalid permissions config {p}: missing top-level 'permissions' key")

    raw = data["permissions"]
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid permissions config {p}: 'permissions' must be a mapping")

    result: dict[str, PermissionContext] = {}
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid permissions config {p}: entry '{key}' must be a mapping")
        try:
            raw_user_id = entry.get("user_id", key)
            result[key] = PermissionContext(
                user_id=str(raw_user_id) if raw_user_id is not None else key,
                allowed_processes=list(entry.get("allowed_processes", [])),
                org_ids=entry.get("org_ids"),
                dept_ids=entry.get("dept_ids"),
                data_scope=entry.get("data_scope", "ALL"),
            )
        except (TypeError, KeyError) as exc:
            raise ValueError(f"Invalid permissions config {p}: entry '{key}' malformed: {exc}") from exc

    return result


def load_permission_config() -> dict[str, PermissionContext]:
    """Load permission config from env-configured YAML, falling back to defaults.

    Reads ``HONEYBADGE_PERMISSIONS_CONFIG`` for the YAML path. If unset or
    the file is missing, returns the built-in demo defaults.

    Returns:
        A dict mapping user_id to PermissionContext.
    """
    yaml_path = os.environ.get("HONEYBADGE_PERMISSIONS_CONFIG")
    if not yaml_path:
        return dict(_DEFAULT_PERMISSION_CONFIG)
    try:
        return _load_permissions_from_yaml(yaml_path)
    except (FileNotFoundError, ValueError) as exc:
        # In production, a misconfigured path should fail loudly. For dev
        # convenience we fall back to defaults and log a warning.
        import sys
        print(f"[config] WARNING: failed to load permissions from {yaml_path}: {exc}", file=sys.stderr)
        return dict(_DEFAULT_PERMISSION_CONFIG)


# Module-level singleton — loaded once at import time. All existing imports
# (`from .config import PERMISSION_CONFIG`) continue to work unchanged.
PERMISSION_CONFIG: dict[str, PermissionContext] = load_permission_config()
