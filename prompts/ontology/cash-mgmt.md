# Cash Management Ontology

> **Purpose**: Corporate bank accounts, bank statements, and reconciliation of Payment/ARReceipt to bank lines.
> **Keywords**: bank, 银行, account, 账户, 账号, statement, 对账单, reconciliation, 对账, 银行流水, cash, 资金, sweep, 归集
> **Tags**: `BankAccount` (🆕v2.0), `BankStatement` (🆕v2.0), `BankStatementLine` (🆕v2.0)
> **Edges**: `PAID_FROM_ACCOUNT` (🆕, from Payment), `RECEIVED_TO_ACCOUNT` (🆕, from ARReceipt), `STATEMENT_FOR_ACCOUNT` (🆕), `HAS_STATEMENT_LINE` (🆕), `RECONCILES_PAYMENT` (🆕), `RECONCILES_RECEIPT` (🆕)

---

## Entities

### BankAccount 🆕v2.0
- **vid**: `BA:{bank_account_id}` or `BA:{bank_account_number}`
- **source**: `CE_BANK_ACCOUNTS`
- **key props**: `bank_account_id STRING`, `bank_account_name STRING`, `bank_account_number STRING`, `bank_name STRING`, `branch_name STRING`, `currency_code STRING`, `account_type STRING`, `status STRING`
- **account_type enum**: `INTERNAL` (企业自有) / `SUPPLIER` / `CUSTOMER`

### BankStatement 🆕v2.0
- **vid**: `BST:{statement_id}`
- **source**: `CE_STATEMENT_HEADERS`
- **key props**: `statement_id STRING`, `statement_number STRING`, `statement_date TIMESTAMP`, `bank_account_id STRING`, `opening_balance DOUBLE`, `closing_balance DOUBLE`, `status STRING`

### BankStatementLine 🆕v2.0
- **vid**: `BSTL:{statement_id}:{line_number}`
- **source**: `CE_STATEMENT_LINES`
- **key props**: `line_number INT64`, `trx_date TIMESTAMP`, `trx_type STRING`, `amount DOUBLE`, `bank_trx_number STRING`, `status STRING`, `reconciled_flag STRING`
- **trx_type enum**: `CREDIT` (入账 / 收款) / `DEBIT` (出账 / 付款) / `SWEEP` (资金归集)
- **reconciled_flag enum**: `Y` / `N`

---

## Relationships

| edge | direction | key attrs | semantics |
|------|-----------|-----------|-----------|
| `PAID_FROM_ACCOUNT` 🆕 | Payment → BankAccount | — | |
| `RECEIVED_TO_ACCOUNT` 🆕 | ARReceipt → BankAccount | — | |
| `STATEMENT_FOR_ACCOUNT` 🆕 | BankStatement → BankAccount | — | |
| `HAS_STATEMENT_LINE` 🆕 | BankStatement → BankStatementLine | — | |
| `RECONCILES_PAYMENT` 🆕 | BankStatementLine → Payment | — | 流水对账到付款 |
| `RECONCILES_RECEIPT` 🆕 | BankStatementLine → ARReceipt | — | 流水对账到收款 |

---

## Business Rules

- **R-CASH-1** (P1 CRITICAL): Balance continuity — `BankStatement[N+1].opening_balance == BankStatement[N].closing_balance` per account.
- **R-CASH-2** (P2 HIGH): `BankStatement.closing_balance == opening_balance + SUM(CREDIT) - SUM(DEBIT)` over its lines.
- **R-CASH-3** (P1 CRITICAL — fraud): Unreconciled bank line — `BankStatementLine.reconciled_flag = 'N'` AND `trx_date < now() - 90 days` = potential hidden flow. Escalate if amount > 100K.
- **R-CASH-4** (P2 HIGH): Every `Payment.status = CLEARED` should have a `RECONCILES_PAYMENT` back-link from a BankStatementLine with matching amount and date.
- **R-CASH-5** (P2 HIGH): Every `ARReceipt` with `status = CLEARED` should have a `RECONCILES_RECEIPT` back-link.

---

## Example Queries

### Q: 长期未对账的大额流水（R-CASH-3）
```ngql
MATCH (line:BankStatementLine)<-[:HAS_STATEMENT_LINE]-(stmt:BankStatement)-[:STATEMENT_FOR_ACCOUNT]->(acc:BankAccount)
WHERE line.BankStatementLine.reconciled_flag == "N"
  AND line.BankStatementLine.trx_date < now() - 90 * 86400
  AND abs(line.BankStatementLine.amount) > 100000
RETURN acc.BankAccount.bank_account_number,
       line.BankStatementLine.trx_date,
       line.BankStatementLine.trx_type,
       line.BankStatementLine.amount,
       line.BankStatementLine.bank_trx_number;
```

### Q: 付款流水完整对账检查（R-CASH-4）
```ngql
MATCH (p:Payment)
WHERE p.Payment.status == "CLEARED"
  AND p.Payment.payment_date > now() - 90 * 86400
WHERE NOT EXISTS { MATCH (p)<-[:RECONCILES_PAYMENT]-(:BankStatementLine) }
RETURN p.Payment.payment_number, p.Payment.amount, p.Payment.payment_date;
```

### Q: 账户余额核对
```ngql
MATCH (stmt:BankStatement)-[:STATEMENT_FOR_ACCOUNT]->(acc:BankAccount)
WHERE acc.BankAccount.bank_account_number == "6228480012345678"
RETURN stmt.BankStatement.statement_date,
       stmt.BankStatement.opening_balance,
       stmt.BankStatement.closing_balance,
       stmt.BankStatement.closing_balance - stmt.BankStatement.opening_balance AS net_flow
ORDER BY stmt.BankStatement.statement_date;
```

### Q: 支出大于收入的异常账户（近 30 天）
```ngql
MATCH (line:BankStatementLine)<-[:HAS_STATEMENT_LINE]-(stmt:BankStatement)-[:STATEMENT_FOR_ACCOUNT]->(acc:BankAccount)
WHERE line.BankStatementLine.trx_date > now() - 30 * 86400
WITH acc,
     sum(CASE WHEN line.BankStatementLine.trx_type == "CREDIT" THEN line.BankStatementLine.amount ELSE 0 END) AS total_in,
     sum(CASE WHEN line.BankStatementLine.trx_type == "DEBIT" THEN line.BankStatementLine.amount ELSE 0 END) AS total_out
WHERE total_out > total_in * 2
RETURN acc.BankAccount.bank_account_number, total_in, total_out;
```

---

## Query Hints

- "银行账户" → `BankAccount`.
- "对账单" / "statement" → `BankStatement` + `BankStatementLine`.
- "银行流水" → `BankStatementLine`.
- "未对账" → `reconciled_flag = 'N'`.
- "付款/收款对账" → `RECONCILES_PAYMENT` / `RECONCILES_RECEIPT`.
