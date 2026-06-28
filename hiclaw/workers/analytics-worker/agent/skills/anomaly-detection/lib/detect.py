"""Anomaly detection patterns — replaces prose in anomaly-detection/SKILL.md."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from common.mcp_client import MCPClient, QueryResult
from common.severity import Severity, classify
from common.session_state import Anomaly, AnomalyTracker
from anomaly_detection.lib.patterns import (
    THREE_WAY_TOLERANCE,
    THREE_WAY_WARNING_RATIO,
    THREE_WAY_ALERT_RATIO,
    DUPLICATE_INVOICE_COUNT,
    PAYMENT_DEVIATION_FACTOR,
    SUPPLIER_CONCENTRATION,
)


@dataclass
class DetectionContext:
    """Context for detection functions — injected for testability."""
    client: MCPClient
    tracker: AnomalyTracker
    user_id: str | None = None


def detect_three_way_mismatch(ctx: DetectionContext, po_id: str) -> list[Anomaly]:
    """Detect PO vs Invoice amount mismatches.

    Flags when invoice_amount > po_amount * THREE_WAY_TOLERANCE.
    """
    result = ctx.client.validate_and_execute(
        f'GO FROM "{po_id}" OVER po_line YIELD po_line.amount AS po_amount, '
        f'po_line.invoice_amount AS invoice_amount',
        user_id=ctx.user_id,
    )
    anomalies: list[Anomaly] = []
    for row in result.rows:
        po_amount = float(row.get("po_amount", 0))
        invoice_amount = float(row.get("invoice_amount", 0))
        if po_amount <= 0:
            continue
        ratio = invoice_amount / po_amount
        if ratio >= THREE_WAY_TOLERANCE:
            severity = classify(ratio, THREE_WAY_WARNING_RATIO, THREE_WAY_ALERT_RATIO)
            anomalies.append(Anomaly(
                type="three_way_mismatch",
                severity=severity.value,
                evidence={
                    "po_id": po_id,
                    "po_amount": po_amount,
                    "invoice_amount": invoice_amount,
                    "ratio": round(ratio, 4),
                },
                round=0,  # round set by caller
            ))
    if anomalies:
        ctx.tracker.save(anomalies)
    return anomalies


def detect_duplicate_invoices(
    ctx: DetectionContext, supplier_id: str | None = None
) -> list[Anomaly]:
    """Detect duplicate invoices grouped by (supplier, amount, date)."""
    ngql = (
        'GET SUBGRAPH WITH PROP 3 FROM "invoice_root" YIELD '
        'vertices AS v, edges AS e | UNWIND v AS invoice | '
        'RETURN invoice.supplier AS supplier, invoice.amount AS amount, '
        'invoice.invoice_date AS invoice_date, count(*) AS cnt'
    )
    result = ctx.client.validate_and_execute(ngql, user_id=ctx.user_id)
    anomalies: list[Anomaly] = []
    for row in result.rows:
        count = int(row.get("count", row.get("cnt", 0)))
        if count > DUPLICATE_INVOICE_COUNT:
            anomalies.append(Anomaly(
                type="duplicate_invoice",
                severity=Severity.WARNING.value,
                evidence={
                    "supplier": row.get("supplier"),
                    "amount": row.get("amount"),
                    "invoice_date": row.get("invoice_date"),
                    "count": count,
                },
                round=0,
            ))
    if anomalies:
        ctx.tracker.save(anomalies)
    return anomalies


def detect_unusual_payments(
    ctx: DetectionContext, days: int = 90
) -> list[Anomaly]:
    """Detect payments exceeding 2x supplier's historical average."""
    ngql = (
        f'GO FROM "payment_root" OVER payment YIELD '
        f'payment.supplier AS supplier, payment.amount AS amount, '
        f'payment.avg_amount AS avg_amount'
    )
    result = ctx.client.validate_and_execute(ngql, user_id=ctx.user_id)
    anomalies: list[Anomaly] = []
    for row in result.rows:
        amount = float(row.get("amount", 0))
        avg = float(row.get("avg_amount", 0))
        if avg <= 0:
            continue
        if amount > avg * PAYMENT_DEVIATION_FACTOR:
            ratio = amount / avg
            severity = classify(ratio, PAYMENT_DEVIATION_FACTOR, PAYMENT_DEVIATION_FACTOR * 1.5)
            anomalies.append(Anomaly(
                type="unusual_payment",
                severity=severity.value,
                evidence={
                    "supplier": row.get("supplier"),
                    "amount": amount,
                    "avg_amount": avg,
                    "ratio": round(ratio, 4),
                },
                round=0,
            ))
    if anomalies:
        ctx.tracker.save(anomalies)
    return anomalies


def detect_supplier_concentration(
    ctx: DetectionContext, category: str | None = None
) -> list[Anomaly]:
    """Detect suppliers exceeding 60% of category spend."""
    ngql = (
        'GO FROM "category_root" OVER category_spend YIELD '
        'category_spend.supplier AS supplier, '
        'category_spend.spend AS category_spend, '
        'category_spend.total AS total_spend'
    )
    result = ctx.client.validate_and_execute(ngql, user_id=ctx.user_id)
    anomalies: list[Anomaly] = []
    for row in result.rows:
        spend = float(row.get("category_spend", row.get("spend", 0)))
        total = float(row.get("total_spend", row.get("total", 0)))
        if total <= 0:
            continue
        ratio = spend / total
        if ratio > SUPPLIER_CONCENTRATION:
            severity = classify(ratio, SUPPLIER_CONCENTRATION, 0.80)
            anomalies.append(Anomaly(
                type="supplier_concentration",
                severity=severity.value,
                evidence={
                    "supplier": row.get("supplier"),
                    "category_spend": spend,
                    "total_spend": total,
                    "ratio": round(ratio, 4),
                },
                round=0,
            ))
    if anomalies:
        ctx.tracker.save(anomalies)
    return anomalies
