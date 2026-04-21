# Customer Domain Ontology

> **Purpose**: Oracle EBS TCA (Trading Community Architecture) customer model — Customer (Party + Account) and CustomerSite (bill-to, ship-to, deliver-to, payment).
> **Keywords**: customer, 客户, tca, party, account, site, 地点, bill to, ship to, deliver to, 开票地址, 送货地址, credit limit, 信用额度
> **Tags**: `Customer`, `CustomerSite` (🆕v2.0)
> **Edges**: `HAS_CUSTOMER_SITE` (🆕), `SOLD_TO`, `BILL_TO_SITE` (🆕), `SHIP_TO_SITE` (🆕), `RECEIVED_FROM`

---

## Entities

### Customer
- **vid**: `CUS:{customer_number}`
- **source**: `HZ_PARTIES` + `HZ_CUST_ACCOUNTS` (TCA)
- **key props**: `customer_number STRING`, `customer_name STRING`, `customer_type STRING`, `status STRING`, `country STRING`, `credit_limit DOUBLE`, `payment_terms STRING`, `tax_id STRING`, `sales_region STRING`, `industry STRING`
- **customer_type enum**: `INTERNAL` / `EXTERNAL` / `GOVERNMENT`
- **status enum**: `ACTIVE` / `INACTIVE` / `BLACKLISTED`
- **semantics**: Oracle EBS R12 uses TCA — a Party (legal entity) can have multiple Accounts, each with multiple Sites. Our graph flattens Party+Account into this single `Customer` node.

### CustomerSite 🆕v2.0
- **vid**: `CUSS:{customer_number}-{site_code}`
- **source**: `HZ_CUST_ACCT_SITES_ALL` + `HZ_CUST_SITE_USES_ALL`
- **key props**: `site_code STRING`, `site_name STRING`, `address STRING`, `city STRING`, `country STRING`, `site_use_code STRING`, `primary_flag BOOL`, `status STRING`
- **site_use_code enum**: `BILL_TO` (开票) / `SHIP_TO` (送货) / `DELIVER_TO` (最终交付) / `PAYMENT` (付款地址) / `STATEMENTS` (对账单) / `DUN` (催款)
- **semantics**: One customer can have many sites with different uses. A single SalesOrder references distinct sites for BILL_TO and SHIP_TO. Changes to a ship-to site address on large orders require audit.

---

## Relationships

| edge | direction | key attrs | semantics |
|------|-----------|-----------|-----------|
| `HAS_CUSTOMER_SITE` 🆕 | Customer → CustomerSite | — | |
| `SOLD_TO` | SalesOrder → Customer | `order_date TIMESTAMP` | |
| `BILL_TO_SITE` 🆕 | SalesOrder → CustomerSite | — | site_use_code='BILL_TO' 地点 |
| `SHIP_TO_SITE` 🆕 | SalesOrder → CustomerSite | — | site_use_code='SHIP_TO' 地点 |
| `RECEIVED_FROM` | ARReceipt → Customer | — | |

---

## Business Rules

- **R-CUS-1** (P1 CRITICAL): `Customer.credit_limit >= SUM(ARInvoice.total_amount with no ARReceipt applied)` for that customer. Violation = credit control failure.
- **R-CUS-2** (P2 HIGH): `CustomerSite.status = INACTIVE` sites must not appear as `BILL_TO_SITE`/`SHIP_TO_SITE` on new `SOLD_TO.order_date` entries.
- **R-CUS-3** (P3 MEDIUM): Large order (>1M) where `SHIP_TO_SITE` differs from all prior orders for the same customer = unusual ship-to change; log for audit.
- **R-CUS-4** (P2 HIGH): At least one `CustomerSite` with `site_use_code = 'BILL_TO'` AND `primary_flag = true` per active Customer.
- **R-CUS-5** (P2 HIGH): `BLACKLISTED` Customer must not be target of new `SOLD_TO` (`SO.status != CANCELLED`).

---

## Example Queries

### Q: 某客户的所有地点及用途
```ngql
MATCH (c:Customer)-[:HAS_CUSTOMER_SITE]->(site:CustomerSite)
WHERE c.Customer.customer_number == "C000123"
RETURN c.Customer.customer_name,
       site.CustomerSite.site_code,
       site.CustomerSite.site_use_code,
       site.CustomerSite.address,
       site.CustomerSite.primary_flag,
       site.CustomerSite.status;
```

### Q: 客户超出信用额度（R-CUS-1）
```ngql
MATCH (c:Customer)
WHERE c.Customer.credit_limit > 0
MATCH (so:SalesOrder)-[:SOLD_TO]->(c)
MATCH (so)-[:HAS_AR_INVOICE]->(inv:ARInvoice)
WHERE inv.ARInvoice.status == "COMPLETE"
WHERE NOT EXISTS { MATCH (inv)<-[:APPLIES_TO]-(:ARReceipt) }
WITH c, sum(inv.ARInvoice.total_amount) AS unpaid_ar
WHERE unpaid_ar > c.Customer.credit_limit
RETURN c.Customer.customer_name,
       c.Customer.credit_limit,
       unpaid_ar,
       unpaid_ar - c.Customer.credit_limit AS excess;
```

### Q: 大额订单送货地点与常用地点不一致（R-CUS-3）
```ngql
MATCH (so:SalesOrder)-[:SOLD_TO]->(c:Customer)
MATCH (so)-[:SHIP_TO_SITE]->(current_site:CustomerSite)
WHERE so.SalesOrder.total_amount > 1000000
OPTIONAL MATCH (prev_so:SalesOrder)-[:SOLD_TO]->(c)
WHERE prev_so.SalesOrder.order_date < so.SalesOrder.order_date
MATCH (prev_so)-[:SHIP_TO_SITE]->(prev_site:CustomerSite)
WITH so, c, current_site,
     collect(DISTINCT prev_site.CustomerSite.site_code) AS historical_sites
WHERE NOT current_site.CustomerSite.site_code IN historical_sites
RETURN so.SalesOrder.so_number, c.Customer.customer_name,
       current_site.CustomerSite.site_code, historical_sites;
```

---

## Query Hints

- "客户主数据" → `Customer`.
- "开票地址" / "bill-to" → `BILL_TO_SITE` edge (SO → CustomerSite).
- "送货地址" / "ship-to" → `SHIP_TO_SITE` edge.
- "信用额度" → `Customer.credit_limit`.
- "客户地点变更" → compare `CustomerSite.updated_at` across orders.
