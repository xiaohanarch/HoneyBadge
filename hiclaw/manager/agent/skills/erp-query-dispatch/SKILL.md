---
name: erp-query-dispatch
description: Dispatch ERP queries to Workers. Triggered when user message starts with "erp问题".
assign_when: User message starts with "erp问题"
---

# ERP Query Dispatch

When a user asks an ERP question, reply with **ONLY** the following format — no other text:

## For data queries (供应商/采购/发票/付款/库存/收货/物料/订单)

```
@graph-worker:matrix-local.hiclaw.io 请处理以下ERP查询：
question: "<原问题>"
```

## For analysis (分析/检测/对比/趋势/统计/fraud/异常)

```
@analytics-worker:matrix-local.hiclaw.io 请处理以下ERP分析任务：
question: "<原问题>"
```

**DO NOT spawn sub-agents. DO NOT run exec. DO NOT query databases. Just output the @mention text above.**
