# XLA (Subledger Accounting) Ontology

> **Purpose**: Oracle EBS **XLA (Subledger Accounting)** layer — the engine that converts business events (PO, Receipt, Invoice, Payment, SO, ARInvoice) into accounting entries before GL transfer. Bridge from source documents to `gl.md`.
> **Keywords**: xla, subledger, 子分类账, accounting event, 会计事件, accounting entry, 记账凭证, journal entry, 凭证, 追溯, trace, 源单据, distribution link, 分配链接, 借贷, dr, cr
> **Tags**: `XLAEvent`, `XLAJournalEntry` (🆕v2.0), `XLAJournalLine` (🆕v2.0), `XLADistributionLink` (🆕v2.0), `AccountingDistribution`
> **Edges**: `ACCOUNTING_FOR`, `GENERATES_ENTRY` (🆕), `HAS_XLA_LINE` (🆕), `XLA_LINE_TO_ACCOUNT` (🆕), `XLA_DIST_LINK` (🆕), `LINKS_TO_SOURCE_DIST` (🆕), `TRANSFERRED_TO_GL` (🆕), `DISTRIBUTED_TO`

---

## Entities

### XLAEvent
- **vid**: `XLAE:{event_id}`
- **source**: `XLA_EVENTS`
- **key props**: `event_id STRING`, `event_class STRING`, `event_type STRING`, `event_date TIMESTAMP`, `accounting_date TIMESTAMP`, `status STRING`, `source_doc_type STRING`, `source_doc_id STRING`
- **event_class enum**: `PURCHASE_ORDER` / `RECEIVING` / `INVOICES` / `PAYMENTS` / `SALES_INVOICES` / `RECEIPTS` / `ADJUSTMENTS`
- **event_type enum**: `CREATE` / `REVERSE` / `ADJUSTMENT` / `CANCEL`
- **status enum**: `U` (Unprocessed) / `P` (Processed) / `N` (No-Action) / `I` (Invalid)
- **semantics**: Triggered by a business action. Each business document that needs accounting produces 1+ XLAEvent. Linked to the source document via `ACCOUNTING_FOR`.

### XLAJournalEntry 🆕v2.0
- **vid**: `XJE:{ae_header_id}`
- **source**: `XLA_AE_HEADERS`
- **key props**: `ae_header_id STRING`, `accounting_entry_status STRING`, `accounting_date TIMESTAMP`, `period_name STRING`, `je_category STRING`, `gl_transfer_status STRING`, `description STRING`
- **accounting_entry_status enum**: `F` (Final) / `D` (Draft) / `I` (Incomplete)
- **gl_transfer_status enum**: `N` (not transferred) / `Y` (transferred) / `NT` (never-transfer)
- **semantics**: The subledger journal header — 1 XLAEvent generally produces 1 XLAJournalEntry.

### XLAJournalLine 🆕v2.0
- **vid**: `XJL:{ae_header_id}:{ae_line_num}`
- **source**: `XLA_AE_LINES`
- **key props**: `ae_line_num INT64`, `accounting_class STRING`, `entered_dr DOUBLE`, `entered_cr DOUBLE`, `accounted_dr DOUBLE`, `accounted_cr DOUBLE`, `currency_code STRING`, `currency_conversion_rate DOUBLE`, `description STRING`
- **accounting_class examples**: `ACCRUAL` / `CHARGE` (PO); `LIABILITY` / `CASH` / `DISCOUNT` (AP); `RECEIVABLE` / `REVENUE` / `TAX` (AR)
- **semantics**: The debit/credit lines of an entry. Each line points to a `GLCodeCombination` via `XLA_LINE_TO_ACCOUNT`.

### XLADistributionLink 🆕v2.0
- **vid**: `XDL:{link_id}`
- **source**: `XLA_DISTRIBUTION_LINKS`
- **key props**: `link_id STRING`, `source_distribution_type STRING`, `source_distribution_id STRING`, `applied_to_dist_id STRING`
- **semantics**: **The critical audit bridge.** Links an XLAJournalLine back to the source document's distribution (InvoiceDistribution, PODistribution, etc.). Without this, end-to-end trace from GL to source document is impossible.

### AccountingDistribution
- **vid**: `ACCDIST:{distribution_id}`
- **key props**: `distribution_id STRING`, `debit_amount DOUBLE`, `credit_amount DOUBLE`, `accounting_class STRING`, `posted_flag STRING`

---

## Relationships

| edge | direction | key attrs | semantics |
|------|-----------|-----------|-----------|
| `ACCOUNTING_FOR` | XLAEvent → (source doc) | `event_class STRING` | 会计事件 ↔ 源单据 (PO/Receipt/Invoice/Payment/SO/ARInvoice) |
| `GENERATES_ENTRY` 🆕 | XLAEvent → XLAJournalEntry | — | 事件生成的凭证 |
| `HAS_XLA_LINE` 🆕 | XLAJournalEntry → XLAJournalLine | — | 凭证行 |
| `XLA_LINE_TO_ACCOUNT` 🆕 | XLAJournalLine → GLCodeCombination | — | 记入科目组合 |
| `XLA_DIST_LINK` 🆕 | XLAJournalLine → XLADistributionLink | — | |
| `LINKS_TO_SOURCE_DIST` 🆕 | XLADistributionLink → InvoiceDistribution | — | 回溯源分配行 |
| `TRANSFERRED_TO_GL` 🆕 | XLAJournalEntry → GLJournalEntry | — | 子分类账→总账传输 |
| `DISTRIBUTED_TO` | AccountingDistribution → GLAccount | — | |

---

## Business Rules

- **R-XLA-1** (P1 CRITICAL): Balanced entry — `SUM(XLAJournalLine.entered_dr) == SUM(XLAJournalLine.entered_cr)` per XLAJournalEntry.
- **R-XLA-2** (P1 CRITICAL): Currency consistency — `XLAJournalLine.accounted_dr == entered_dr * currency_conversion_rate` (within rounding).
- **R-XLA-3** (P2 HIGH): Every PO, Receipt, Invoice, Payment, SO, ARInvoice, ARReceipt should have at least one XLAEvent via `ACCOUNTING_FOR`. Missing = accounting gap.
- **R-XLA-4** (P2 HIGH): `XLAJournalEntry.gl_transfer_status = 'N'` AND `accounting_entry_status = 'F'` AND `accounting_date < GLPeriod.end_date` of an OPEN period = untransferred final entry (period close blocker).
- **R-XLA-5** (P2 HIGH): Every `XLAJournalLine` should have an `XLA_DIST_LINK` to an `XLADistributionLink` (except for system-generated balancing lines like currency rounding).
- **R-XLA-6** (P1 CRITICAL): `XLAEvent.status = 'F'` (final) — must not be modified; adjustments happen via a new REVERSE event.

---

## Example Queries

### Q: 某 PO 的完整会计处理链
```ngql
MATCH (xe:XLAEvent)-[:ACCOUNTING_FOR]->(po:PurchaseOrder)
WHERE po.PurchaseOrder.po_number == "PO-2026-0001"
OPTIONAL MATCH (xe)-[:GENERATES_ENTRY]->(xje:XLAJournalEntry)-[:HAS_XLA_LINE]->(xjl:XLAJournalLine)
OPTIONAL MATCH (xjl)-[:XLA_LINE_TO_ACCOUNT]->(cc:GLCodeCombination)
RETURN xe.XLAEvent.event_class, xe.XLAEvent.event_type, xe.XLAEvent.event_date,
       xje.XLAJournalEntry.ae_header_id,
       xjl.XLAJournalLine.accounting_class,
       xjl.XLAJournalLine.entered_dr, xjl.XLAJournalLine.entered_cr,
       cc.GLCodeCombination.concatenated_segments AS account;
```

### Q: 期间关闭前未传 GL 的子分类账凭证（R-XLA-4）
```ngql
MATCH (xje:XLAJournalEntry)
WHERE xje.XLAJournalEntry.gl_transfer_status == "N"
  AND xje.XLAJournalEntry.accounting_entry_status == "F"
RETURN xje.XLAJournalEntry.ae_header_id,
       xje.XLAJournalEntry.accounting_date,
       xje.XLAJournalEntry.period_name,
       xje.XLAJournalEntry.je_category;
```

### Q: 从某 GL 科目一路追溯到源单据（全链审计）
```ngql
MATCH (xjl:XLAJournalLine)-[:XLA_LINE_TO_ACCOUNT]->(cc:GLCodeCombination)
WHERE cc.GLCodeCombination.segment3 == "2201"
MATCH (xje:XLAJournalEntry)-[:HAS_XLA_LINE]->(xjl)
MATCH (xe:XLAEvent)-[:GENERATES_ENTRY]->(xje)
MATCH (xe)-[:ACCOUNTING_FOR]->(doc)
RETURN xjl.XLAJournalLine.entered_dr, xjl.XLAJournalLine.entered_cr,
       xe.XLAEvent.source_doc_type, xe.XLAEvent.source_doc_id,
       xe.XLAEvent.event_class, xe.XLAEvent.accounting_date;
```

### Q: 非平衡凭证检测（R-XLA-1）
```ngql
MATCH (xje:XLAJournalEntry)-[:HAS_XLA_LINE]->(xjl:XLAJournalLine)
WITH xje, sum(xjl.XLAJournalLine.entered_dr) AS total_dr,
     sum(xjl.XLAJournalLine.entered_cr) AS total_cr
WHERE abs(total_dr - total_cr) > 0.01
RETURN xje.XLAJournalEntry.ae_header_id,
       total_dr, total_cr, (total_dr - total_cr) AS imbalance;
```

---

## Query Hints

- "会计事件" / "accounting event" → `XLAEvent`.
- "子分类账凭证" / "XLA entry" → `XLAJournalEntry` / `XLAJournalLine`.
- "从 GL 追溯" / "trace to source" → chain `GLJournalLine ← (TRANSFERRED_TO_GL) ← XLAJournalEntry → HAS_XLA_LINE → XLAJournalLine → XLA_DIST_LINK → XLADistributionLink → LINKS_TO_SOURCE_DIST → InvoiceDistribution`.
- "未传 GL" → `XLAJournalEntry.gl_transfer_status = 'N'`.
- "借贷不平" → aggregate `entered_dr` vs `entered_cr` per entry.
