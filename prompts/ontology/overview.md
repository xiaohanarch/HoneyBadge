# HoneyBadge ERP Ontology — Overview

> **Version**: v2.0 (Oracle EBS R12.2.2 aligned)
> **Purpose**: Master index. When answering ERP questions, select 1–3 relevant domain files below and include them in the prompt alongside this overview.
> **Keywords**: erp, oracle ebs, ontology, 本体, 实体, 关系
> **Graph Space**: `honeybadge` (NebulaGraph 3.x, openCypher 9)

---

## You are answering questions over an Oracle EBS knowledge graph

- 57 tags (entities), 82 edges (relationships). See `14.1/14.2` in `docs/phase1/10-ontology.md` for the authoritative list.
- Two primary business processes:
  - **PTP (Procure-to-Pay)**: `PR → PO → POShipment → Receipt → Invoice → Payment`
  - **OTC (Order-to-Cash)**: `SO → Shipment → ARInvoice → ARReceipt`
- Every transactional document flows through **XLA (子分类账) → GL (总账)** for accounting.
- Master data anchors: `Item`, `Supplier`, `Customer`, `Organization`, `Employee`, `GLCodeCombination`.

## nGQL (NebulaGraph) syntax reminders

- **Property access requires tag/edge prefix**: `p.Payment.amount`, NOT `p.amount`.
- **VID is STRING**, formatted `PREFIX:{business_key}` (e.g., `PO:PO-2026-0001`, `INV:I-2026-0001`, `JLL:JLE00007500-8`). See each domain file for VID format.
- **Timestamp** is INT64 (unix epoch seconds). Use `datetime_diff(a, b) / 86400` for day diffs.
- **Comments** use `#`, NOT `--`.
- **Return tag properties explicitly**: `RETURN p.Payment.amount AS amt`.

## Domain files (pick relevant ones per question)

| File | Scope | When to include |
|------|-------|-----------------|
| `supplier.md` | Supplier, SupplierSite, SupplierQualification, SUPPLIES_ITEM | 供应商/vendor/site/资质/qualification questions |
| `procurement.md` | PR, PO, POShipment, Receipt, ReceiptLine, ReceivingTransaction | 采购/PO/收货/receipt/requisition questions |
| `payable.md` | Invoice, InvoiceLine, InvoiceDistribution, InvoiceHold, Payment, PaymentBatch, PaymentSchedule, ExpenseReport | AP/发票/冻结/付款/hold/费用报销 questions |
| `receivable.md` | SalesOrder, SOLine, Shipment, ShipmentLine, ARInvoice, ARInvoiceLine, ARReceipt | 销售/发货/应收/AR/收款 questions |
| `customer.md` | Customer, CustomerSite | 客户/customer/site/ship-to/bill-to questions |
| `xla.md` | XLAEvent, XLAJournalEntry, XLAJournalLine, XLADistributionLink, AccountingDistribution | 会计事件/子分类账/XLA/accounting engine/追溯源单据 questions |
| `gl.md` | Ledger, GLPeriod, GLCodeCombination, GLAccount, GLJournalBatch, GLJournalEntry, GLJournalLine, GLBalance, CurrencyRate | 总账/GL/日记账/科目/期间/余额/汇率 questions |
| `inventory.md` | InventoryTransaction, ItemCategory | 库存/inventory/transaction/盘点/转移/分类 questions |
| `cash-mgmt.md` | BankAccount, BankStatement, BankStatementLine | 银行/bank/对账/statement/reconciliation questions |
| `master-data.md` | Item, BOM, BOMComponent, Organization, Employee, Warehouse, Currency, UOM, ApprovalRecord, Contract | 物料/BOM/组织/员工/仓库/合同/审批 questions |
| `constraints.md` | Three-way match, temporal rules, amount integrity, fraud patterns | Always include for risk/fraud/异常/三单匹配/审计 questions |

## Standard tag properties (appear on ALL tags)

```
org_id INT64           # permission anchor (must be filtered for RBAC)
dept_id INT64
data_scope STRING      # "GLOBAL" / "ORG" / "DEPT" / "SELF"
created_at TIMESTAMP
updated_at TIMESTAMP
etl_batch_id STRING
source_system STRING   # typically "ORACLE_EBS"
is_active BOOL DEFAULT true
```

All edges additionally carry `org_id INT64, dept_id INT64` for permission injection.

## Priority legend in rule annotations

- **P1 CRITICAL** — violation likely indicates fraud or data corruption; investigate immediately
- **P2 HIGH** — significant business anomaly; escalate
- **P3 MEDIUM** — notable deviation; log for review
- **P4 LOW** — informational

## Anti-hallucination directive

When generating nGQL: emit ONLY schema elements (tags/edges/props) that appear in the included domain files. If the user's question requires an element you cannot find, respond that the schema does not support the query — DO NOT invent tag names, edge names, or properties.
