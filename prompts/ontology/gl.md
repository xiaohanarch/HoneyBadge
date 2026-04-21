# General Ledger (GL) Ontology

> **Purpose**: Oracle EBS General Ledger — Ledger, Period, CCID (code combination), Account hierarchy, JournalBatch/Entry/Line, Balance, CurrencyRate.
> **Keywords**: gl, general ledger, 总账, 日记账, journal, journal entry, 凭证, batch, 批次, period, 期间, 期末, close, 关账, ccid, 科目组合, coa, chart of accounts, 科目, account, ledger, 账套, balance, 余额, trial balance, 试算平衡, rate, 汇率, posted, 过账
> **Tags**: `Ledger` (🆕v2.0), `GLPeriod` (🆕v2.0), `GLCodeCombination` (🆕v2.0), `GLAccount`, `GLJournalBatch` (🆕v2.0), `GLJournalEntry`, `GLJournalLine`, `GLBalance` (🆕v2.0), `CurrencyRate` (🆕v2.0)
> **Edges**: `IN_LEDGER` (🆕), `IN_PERIOD` (🆕), `IN_BATCH` (🆕), `HAS_JOURNAL_LINE`, `POSTED_TO`, `BALANCE_FOR` (🆕), `BALANCE_IN_PERIOD` (🆕), `ACCOUNT_IN_COA` (🆕), `PARENT_ACCOUNT` (🆕), `TRANSFERRED_TO_GL` (🆕, from XLA)

---

## Entities

### Ledger 🆕v2.0
- **vid**: `LEDGER:{ledger_id}`
- **source**: `GL_LEDGERS`
- **key props**: `ledger_id STRING`, `ledger_name STRING`, `short_name STRING`, `chart_of_accounts_id STRING`, `currency_code STRING`, `period_set_name STRING`, `period_type STRING`, `description STRING`
- **semantics**: Multi-Org accounting book. One Ledger = one COA + one functional currency + one calendar.

### GLPeriod 🆕v2.0
- **vid**: `GLP:{ledger_id}:{period_name}` or `GLP:{period_name}`
- **source**: `GL_PERIOD_STATUSES`
- **key props**: `period_name STRING`, `period_year INT64`, `period_num INT64`, `start_date TIMESTAMP`, `end_date TIMESTAMP`, `closing_status STRING`
- **closing_status enum**: `O` (Open) / `C` (Closed) / `P` (Permanently Closed) / `F` (Future Entry) / `N` (Never Opened)
- **semantics**: Controls which periods accept postings. `C`/`P` periods REJECT new entries.

### GLCodeCombination 🆕v2.0 — CCID / Accounting Flexfield
- **vid**: `CCID:{code_combination_id}`
- **source**: `GL_CODE_COMBINATIONS`
- **key props**: `code_combination_id STRING`, `segment1 STRING` (公司), `segment2 STRING` (成本中心), `segment3 STRING` (自然科目), `segment4 STRING` (子目), `segment5 STRING` (产品线), `concatenated_segments STRING`, `enabled_flag BOOL`, `summary_flag BOOL`, `account_type STRING`
- **account_type enum**: `A` (Asset) / `L` (Liability) / `O` (Owner's Equity) / `R` (Revenue) / `E` (Expense)
- **semantics**: The **full multi-segment accounting key**. Use this, not `GLAccount`, for postings. Example: `01-100-2201-00-000` = Company 01 / Cost Center 100 / AP liability (2201) / no sub / no product line.

### GLAccount
- **vid**: `GLA:{account_code}`
- **key props**: `account_code STRING`, `account_name STRING`, `account_type STRING`, `level INT64`, `is_leaf BOOL`
- **semantics**: The COA hierarchy tree (parent-child via `PARENT_ACCOUNT`) of the `segment3` natural account only.

### GLJournalBatch 🆕v2.0
- **vid**: `GLB:{batch_id}`
- **source**: `GL_JE_BATCHES`
- **key props**: `batch_id STRING`, `batch_name STRING`, `status STRING`, `default_period_name STRING`, `posted_date TIMESTAMP`, `description STRING`
- **status enum**: `U` (Unposted) / `P` (Posted) / `S` (Selected)

### GLJournalEntry
- **vid**: `JE:{journal_id}` or `JE:{journal_number}`
- **source**: `GL_JE_HEADERS`
- **key props**: `journal_number STRING`, `journal_name STRING`, `journal_source STRING`, `journal_category STRING`, `period_name STRING`, `gl_date TIMESTAMP`, `status STRING`, `total_debit DOUBLE`, `total_credit DOUBLE`
- **journal_source enum (std values)**: `Payables` / `Receivables` / `Purchasing` / `Manual` / `Assets` / `Inventory`
- **status enum**: `UNPOSTED` / `POSTED` / `ERROR` / `REVERSED`

### GLJournalLine
- **vid**: `JLL:{journal_id}-{line_number}` (e.g., `JLL:JLE00007500-8`)
- **source**: `GL_JE_LINES`
- **key props**: `line_number INT64`, `debit_amount DOUBLE`, `credit_amount DOUBLE`, `description STRING`, `reference STRING`

### GLBalance 🆕v2.0
- **vid**: `GLBAL:{ccid}:{period_name}:{currency}`
- **source**: `GL_BALANCES`
- **key props**: `period_name STRING`, `currency_code STRING`, `period_net_dr DOUBLE`, `period_net_cr DOUBLE`, `begin_balance_dr DOUBLE`, `begin_balance_cr DOUBLE`, `translated_flag BOOL`
- **semantics**: One row per CCID × Period × Currency. Used for trial balance, trends, reports.

### CurrencyRate 🆕v2.0
- **vid**: `RATE:{from_currency}-{to_currency}-{conversion_date}-{conversion_type}`
- **source**: `GL_DAILY_RATES`
- **key props**: `from_currency STRING`, `to_currency STRING`, `conversion_date TIMESTAMP`, `conversion_type STRING`, `conversion_rate DOUBLE`
- **conversion_type enum**: `Spot` / `Corporate` / `User`

---

## Relationships

| edge | direction | key attrs | semantics |
|------|-----------|-----------|-----------|
| `IN_LEDGER` 🆕 | GLJournalEntry → Ledger | — | |
| `IN_PERIOD` 🆕 | GLJournalEntry → GLPeriod | — | |
| `IN_BATCH` 🆕 | GLJournalEntry → GLJournalBatch | — | |
| `HAS_JOURNAL_LINE` | GLJournalEntry → GLJournalLine | — | |
| `POSTED_TO` | GLJournalLine → GLCodeCombination | — | 过账到科目组合（v2.0 升级） |
| `BALANCE_FOR` 🆕 | GLBalance → GLCodeCombination | — | |
| `BALANCE_IN_PERIOD` 🆕 | GLBalance → GLPeriod | — | |
| `ACCOUNT_IN_COA` 🆕 | GLCodeCombination → GLAccount | — | CCID 的自然科目（segment3） |
| `PARENT_ACCOUNT` 🆕 | GLAccount → GLAccount | — | 科目上下级 |
| `TRANSFERRED_TO_GL` 🆕 | XLAJournalEntry → GLJournalEntry | — | see `xla.md` |

---

## Business Rules

- **R-GL-1** (P1 CRITICAL): Balanced entry — `GLJournalEntry.total_debit == total_credit`. Also `SUM(GLJournalLine.debit_amount) == SUM(credit_amount)` per entry.
- **R-GL-2** (P1 CRITICAL): Period control — `GLJournalEntry` with `gl_date` in a `GLPeriod.closing_status IN ('C','P')` must NOT be `UNPOSTED → POSTED`. Use `IN_PERIOD` edge.
- **R-GL-3** (P2 HIGH): Non-leaf postings — lines posting to a `GLCodeCombination` whose `ACCOUNT_IN_COA → GLAccount` has `is_leaf = false` are invalid.
- **R-GL-4** (P2 HIGH): Trial balance — `SUM(GLBalance.period_net_dr) == SUM(period_net_cr)` across all CCIDs per period+ledger.
- **R-GL-5** (P2 HIGH): Balance continuity — `GLBalance[period N+1].begin_balance_dr == GLBalance[period N].begin_balance_dr + period_net_dr` (same for cr).
- **R-GL-6** (P2 HIGH — fraud): Manual journals over threshold (e.g., 500K) in the last 3 days of a period with `journal_source = 'Manual'` = period-end earnings-management signal.
- **R-GL-7** (P3 MEDIUM): `CurrencyRate` uniqueness — at most one rate per `(from, to, date, type)` tuple.
- **R-GL-8** (P3 MEDIUM): `journal_source = 'Manual'` share of posted journals in a period — if >15%, audit attention.

---

## Example Queries

### Q: 某期间某自然科目的借贷发生额
```ngql
MATCH (je:GLJournalEntry)-[:HAS_JOURNAL_LINE]->(jl:GLJournalLine)-[:POSTED_TO]->(cc:GLCodeCombination)
WHERE cc.GLCodeCombination.segment3 == "6001"
  AND je.GLJournalEntry.period_name == "2026-03"
  AND je.GLJournalEntry.status == "POSTED"
RETURN sum(jl.GLJournalLine.debit_amount) AS total_debit,
       sum(jl.GLJournalLine.credit_amount) AS total_credit;
```

### Q: 期末手工凭证占比（R-GL-8）
```ngql
MATCH (je:GLJournalEntry)
WHERE je.GLJournalEntry.period_name == "2026-03"
  AND je.GLJournalEntry.status == "POSTED"
WITH count(je) AS total_count,
     sum(CASE WHEN je.GLJournalEntry.journal_source == "Manual" THEN 1 ELSE 0 END) AS manual_count
RETURN total_count, manual_count, manual_count * 100.0 / total_count AS manual_pct;
```

### Q: 期末异常大额手工凭证（R-GL-6）
```ngql
MATCH (je:GLJournalEntry)-[:IN_PERIOD]->(p:GLPeriod)
WHERE je.GLJournalEntry.journal_source == "Manual"
  AND je.GLJournalEntry.total_debit > 500000
  AND (p.GLPeriod.end_date - je.GLJournalEntry.gl_date) < 3 * 86400
  AND je.GLJournalEntry.gl_date <= p.GLPeriod.end_date
RETURN je.GLJournalEntry.journal_number, je.GLJournalEntry.gl_date,
       je.GLJournalEntry.total_debit, p.GLPeriod.period_name;
```

### Q: 关闭期间被违规过账（R-GL-2）
```ngql
MATCH (je:GLJournalEntry)-[:IN_PERIOD]->(p:GLPeriod)
WHERE p.GLPeriod.closing_status IN ["C", "P"]
  AND je.GLJournalEntry.status == "POSTED"
  AND je.GLJournalEntry.updated_at > p.GLPeriod.end_date
RETURN je.GLJournalEntry.journal_number, p.GLPeriod.period_name,
       p.GLPeriod.closing_status, je.GLJournalEntry.updated_at;
```

### Q: 科目余额趋势（某 CCID 近 6 期）
```ngql
MATCH (bal:GLBalance)-[:BALANCE_FOR]->(cc:GLCodeCombination)
WHERE cc.GLCodeCombination.concatenated_segments == "01-100-2201-00-000"
RETURN bal.GLBalance.period_name,
       bal.GLBalance.begin_balance_dr - bal.GLBalance.begin_balance_cr AS begin_bal,
       bal.GLBalance.period_net_dr - bal.GLBalance.period_net_cr AS period_change
ORDER BY bal.GLBalance.period_name;
```

### Q: 从 GL 凭证追溯到源单据（via XLA）
```ngql
MATCH (je:GLJournalEntry)-[:HAS_JOURNAL_LINE]->(jl:GLJournalLine)
WHERE je.GLJournalEntry.journal_number == "JE-2026-0001"
MATCH (xje:XLAJournalEntry)-[:TRANSFERRED_TO_GL]->(je)
MATCH (xe:XLAEvent)-[:GENERATES_ENTRY]->(xje)
MATCH (xe)-[:ACCOUNTING_FOR]->(doc)
RETURN jl.GLJournalLine.line_number, jl.GLJournalLine.debit_amount, jl.GLJournalLine.credit_amount,
       xe.XLAEvent.source_doc_type, xe.XLAEvent.source_doc_id;
```

---

## Query Hints

- "总账" / "GL" / "日记账" → `GLJournalEntry` / `GLJournalLine`.
- "科目" → prefer `GLCodeCombination` (multi-segment), not `GLAccount` (natural only).
- "期末" / "关账" / "period close" → `GLPeriod.closing_status`.
- "手工凭证" → `journal_source = 'Manual'`.
- "余额" / "balance" / "试算" → `GLBalance`.
- "汇率" → `CurrencyRate`.
- "从 GL 追溯源单据" → use `TRANSFERRED_TO_GL` back-edge into `xla.md` chain.
