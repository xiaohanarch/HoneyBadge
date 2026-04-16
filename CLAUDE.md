# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Project HoneyBadge** — Enterprise Knowledge Graph Intelligent Assistant built on ERP systems (Oracle EBS / custom ERP). Enables natural language Q&A over procurement/supply chain data, fraud detection, and three-way matching anomaly detection.

The canonical architecture document is `README.md` (v3.2). All implementation decisions should align with it.

## Current Status

- **Phase 0 (MVP)**: Complete — single-node Neo4j, OpenClaw agent, cloud LLM API
- **Phase 1 (Active)**: Infrastructure upgrade — migrating to NebulaGraph, HiClaw, Higress gateway, observability stack

## Architecture Summary

```
Frontend (matrix-js-sdk) → honeybadge-auth → Tuwunel Matrix → HiClaw Manager → Worker Pool → MCP Servers → Infrastructure
```

**Core technology choices:**
- Graph DB: NebulaGraph (distributed, openCypher 9)
- Agent orchestration: HiClaw (Alibaba, Manager-Worker-Matrix Room pattern)
- AI Gateway: Higress (Envoy-based)
- LLM (dev): qwen3.5-plus via DashScope (OpenAI-compatible)
- LLM (production target): GLM-5 / GLM-4.7-Flash on Huawei Ascend 910B
- Vector DB: Milvus (semantic cache, ontology retrieval)
- Cache: Redis Cluster
- Audit: PostgreSQL (immutable audit log)
- ETL: Apache SeaTunnel (T+1 batch), Debezium+Kafka (Phase 3 CDC)
- Data quality: Great Expectations (Python)
- Permissions: Existing Java SDK wrapped as MCP Server
- Infra: Kubernetes

**Critical design constraints:**
- LLM only generates nGQL and formats output — never directly answers questions
- Raw query results are passed to users unmodified; LLM only wraps/formats
- Every query carries a `trace_id` for full audit traceability
- Permissions are injected at Cypher AST level, never via string concatenation
- Transaction detail data must live in the graph (not federated) for fraud detection

## Anti-Hallucination Framework (5 Layers)

1. **L1**: Cypher syntax validation (parser-based, reject & regenerate)
2. **L2**: Schema compliance (validate against NebulaGraph schema)
3. **L3**: Permission injection (reject if Cypher lacks permission filters)
4. **L4**: Raw result passthrough (LLM cannot modify data values)
5. **L5**: Full-chain audit log (question → Cypher → result → summary in PostgreSQL)

## Business Domain

ERP-focused, two main processes:
- **Procure-to-Pay (PTP)**: PO → Receipt → Invoice → Payment
- **Order-to-Cash (OTC)**: Sales Order → Shipment → Billing → Collection
- Master data: Item master, Supplier master, BOM

## Language Notes

- The architecture document (`README.md`) is written in Chinese
- The project serves Chinese enterprise users
- Code comments and technical documentation may be in Chinese or English
