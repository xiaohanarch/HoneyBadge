# 可观测性体系

> 版本：v1.0
> 创建日期：2026-04-04
> 依赖：`09-deployment.md`（部署配置）

---

## 1. 架构概览

```
                 ┌──────────────────────────────────────┐
                 │           Grafana (看板)              │
                 │  Dashboard │ Alerting │ Explore       │
                 └──────┬─────────┬──────────┬──────────┘
                        │         │          │
                  ┌─────▼───┐ ┌──▼────┐ ┌───▼───┐
                  │Prometheus│ │ Loki  │ │Jaeger │
                  │ (指标)   │ │(日志) │ │(链路) │
                  └─────▲───┘ └──▲────┘ └───▲───┘
                        │         │          │
          ┌─────────────┼─────────┼──────────┼──────────┐
          │  应用层      │         │          │          │
          │  ┌───────┐  │  ┌──────┤   ┌──────┤          │
          │  │HiClaw │──┘  │      │   │      │          │
          │  │Manager│─────┘      │   │      │          │
          │  └───────┘            │   │      │          │
          │  ┌───────┐     ┌─────┘   │      │          │
          │  │Workers│─────┘  ┌──────┘      │          │
          │  └───────┘        │             │          │
          │  ┌───────┐  ┌────┘             │          │
          │  │Higress│──┘                   │          │
          │  └───────┘         OpenTelemetry SDK       │
          │  ┌───────────┐                             │
          │  │NebulaGraph│── Prometheus exporter        │
          │  └───────────┘                             │
          └────────────────────────────────────────────┘
```

---

## 2. Prometheus 指标定义

### 2.1 LLM 指标

```python
# metrics/llm.py
from prometheus_client import Counter, Histogram, Gauge

# Token 消耗
llm_tokens_total = Counter(
    'honeybadge_llm_tokens_total',
    'Total LLM tokens consumed',
    ['model', 'type']  # type: prompt / completion
)

# 调用延迟
llm_request_duration = Histogram(
    'honeybadge_llm_request_duration_seconds',
    'LLM request duration',
    ['model', 'operation'],  # operation: generate_cypher / summarize
    buckets=[0.5, 1, 2, 3, 5, 10, 15, 30, 60]
)

# 错误率
llm_errors_total = Counter(
    'honeybadge_llm_errors_total',
    'LLM call errors',
    ['model', 'error_type']  # timeout / rate_limit / server_error / content_filter
)

# 当前并发
llm_active_requests = Gauge(
    'honeybadge_llm_active_requests',
    'Current active LLM requests',
    ['model']
)
```

### 2.2 NebulaGraph 指标

```python
# metrics/nebula.py

# 查询延迟
nebula_query_duration = Histogram(
    'honeybadge_nebula_query_duration_seconds',
    'NebulaGraph query duration',
    ['query_type'],  # simple / multi_hop / aggregation
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5]
)

# 连接池
nebula_connection_pool_size = Gauge(
    'honeybadge_nebula_pool_size',
    'NebulaGraph connection pool size',
    ['status']  # active / idle
)

# 查询结果行数
nebula_result_rows = Histogram(
    'honeybadge_nebula_result_rows',
    'NebulaGraph query result row count',
    buckets=[0, 1, 10, 50, 100, 500, 1000]
)

# 存储使用 (通过 NebulaGraph HTTP API 采集)
nebula_storage_bytes = Gauge(
    'honeybadge_nebula_storage_bytes',
    'NebulaGraph storage usage',
    ['space']
)
```

### 2.3 HiClaw 指标

```python
# metrics/hiclaw.py

# Worker 数量
hiclaw_workers = Gauge(
    'honeybadge_hiclaw_workers',
    'HiClaw worker count',
    ['group', 'status']  # group: graph/analytics/mcp, status: active/idle
)

# 任务队列
hiclaw_task_queue_length = Gauge(
    'honeybadge_hiclaw_task_queue_length',
    'HiClaw task queue length',
    ['group']
)

# 任务处理耗时
hiclaw_task_duration = Histogram(
    'honeybadge_hiclaw_task_duration_seconds',
    'HiClaw task processing duration',
    ['group', 'status'],  # status: success / error
    buckets=[1, 2, 5, 10, 15, 30, 60, 120]
)

# Matrix Room 数量
hiclaw_active_rooms = Gauge(
    'honeybadge_hiclaw_active_rooms',
    'Active Matrix rooms'
)
```

### 2.4 网关指标

```
# Higress 内置 Envoy 指标（自动暴露）
envoy_http_downstream_rq_total          # 请求总数
envoy_http_downstream_rq_xx{code="2xx"} # 2xx 响应数
envoy_http_downstream_rq_xx{code="4xx"} # 4xx 响应数
envoy_http_downstream_rq_xx{code="5xx"} # 5xx 响应数
envoy_http_downstream_rq_time_bucket    # 请求延迟分布
envoy_http_downstream_cx_active         # 活跃连接数
```

### 2.5 防幻觉框架指标

```python
# metrics/validation.py

validation_total = Counter(
    'honeybadge_validation_total',
    'Validation attempts',
    ['layer', 'result']  # layer: L1/L2/L3/L4/L5, result: pass/fail
)

cypher_retry_total = Counter(
    'honeybadge_cypher_retry_total',
    'nGQL generation retries',
    ['final_result']  # success / exhausted
)

audit_log_total = Counter(
    'honeybadge_audit_log_total',
    'Audit log entries written',
    ['status']  # success / error
)
```

### 2.6 端到端查询指标

```python
# metrics/query.py

query_total = Counter(
    'honeybadge_query_total',
    'Total user queries',
    ['status']  # success / validation_failed / execution_error / timeout
)

query_e2e_duration = Histogram(
    'honeybadge_query_e2e_duration_seconds',
    'End-to-end query duration (user question to response)',
    ['complexity'],  # simple / complex
    buckets=[1, 2, 5, 10, 15, 30, 60, 120]
)
```

---

## 3. Grafana Dashboard

### 3.1 Dashboard 列表

| Dashboard | 说明 | 刷新间隔 |
|-----------|------|---------|
| HoneyBadge Overview | 全局概览：QPS, 错误率, P95 延迟 | 15s |
| LLM Performance | LLM token 消耗, 延迟, 错误率 | 15s |
| NebulaGraph | 查询延迟, 连接池, 存储 | 30s |
| HiClaw Workers | Worker 状态, 队列长度, 任务耗时 | 15s |
| Anti-Hallucination | 校验通过率, 重试率, 审计日志 | 30s |
| ETL Pipeline | 数据导入状态, 质量校验结果 | 60s |

### 3.2 Overview Dashboard 面板

```json
{
  "title": "HoneyBadge Overview",
  "panels": [
    {
      "title": "QPS",
      "type": "stat",
      "targets": [{"expr": "sum(rate(honeybadge_query_total[5m]))"}]
    },
    {
      "title": "Error Rate",
      "type": "gauge",
      "targets": [{"expr": "sum(rate(honeybadge_query_total{status!='success'}[5m])) / sum(rate(honeybadge_query_total[5m])) * 100"}],
      "thresholds": [{"value": 1, "color": "yellow"}, {"value": 5, "color": "red"}]
    },
    {
      "title": "P50/P95/P99 延迟",
      "type": "timeseries",
      "targets": [
        {"expr": "histogram_quantile(0.5, rate(honeybadge_query_e2e_duration_seconds_bucket[5m]))", "legendFormat": "P50"},
        {"expr": "histogram_quantile(0.95, rate(honeybadge_query_e2e_duration_seconds_bucket[5m]))", "legendFormat": "P95"},
        {"expr": "histogram_quantile(0.99, rate(honeybadge_query_e2e_duration_seconds_bucket[5m]))", "legendFormat": "P99"}
      ]
    },
    {
      "title": "LLM Token 消耗 (今日)",
      "type": "stat",
      "targets": [{"expr": "sum(increase(honeybadge_llm_tokens_total[24h]))"}]
    },
    {
      "title": "Active Workers",
      "type": "stat",
      "targets": [{"expr": "sum(honeybadge_hiclaw_workers{status='active'})"}]
    },
    {
      "title": "Active WebSocket Connections",
      "type": "stat",
      "targets": [{"expr": "envoy_http_downstream_cx_active"}]
    }
  ]
}
```

---

## 4. Loki 日志采集

### 4.1 结构化日志格式

所有服务统一使用 JSON 结构化日志：

```json
{
  "timestamp": "2026-04-04T10:30:00.123Z",
  "level": "INFO",
  "service": "graph-worker",
  "trace_id": "TRC-20260404-00147",
  "user_id": "user_001",
  "session_id": "sess_abc123",
  "message": "nGQL executed successfully",
  "duration_ms": 150,
  "result_rows": 5,
  "extra": {
    "ngql": "MATCH (po:PurchaseOrder)...",
    "space": "honeybadge"
  }
}
```

### 4.2 Loki 配置

```yaml
# loki/loki-config.yaml
auth_enabled: false

server:
  http_listen_port: 3100

common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: 2026-04-01
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

limits_config:
  retention_period: 720h    # 30 天日志保留
```

### 4.3 Promtail 配置（日志采集 Agent）

```yaml
# promtail/promtail-config.yaml
server:
  http_listen_port: 9080

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: honeybadge
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        refresh_interval: 5s
    relabel_configs:
      - source_labels: ['__meta_docker_container_name']
        target_label: container
      - source_labels: ['__meta_docker_container_label_com_docker_compose_service']
        target_label: service
    pipeline_stages:
      - json:
          expressions:
            level: level
            trace_id: trace_id
            service: service
      - labels:
          level:
          trace_id:
          service:
```

---

## 5. Jaeger 链路追踪

### 5.1 OpenTelemetry SDK 集成

```python
# tracing/setup.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanExporter
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.resources import Resource

def setup_tracing(service_name: str):
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    jaeger_exporter = JaegerExporter(
        agent_host_name="jaeger",
        agent_port=6831,
    )
    provider.add_span_processor(BatchSpanExporter(jaeger_exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)
```

### 5.2 关键 Span 定义

```
Trace: user_query
├── Span: gateway.authenticate          (~5ms)
├── Span: manager.route_task            (~10ms)
├── Span: worker.generate_cypher        (~2-5s)
│   ├── Span: llm.call                  (~2-5s)
│   └── Span: prompt.build              (~5ms)
├── Span: worker.validate_cypher        (~50ms)
│   ├── Span: validate.L1_syntax        (~20ms)
│   ├── Span: validate.L2_schema        (~20ms)
│   └── Span: validate.L3_permission    (~10ms)
├── Span: worker.execute_ngql           (~100-500ms)
│   └── Span: nebula.query              (~100-500ms)
├── Span: worker.summarize              (~1-3s)
│   └── Span: llm.call                  (~1-3s)
└── Span: worker.audit_log              (~10ms)
```

### 5.3 trace_id 关联

```
trace_id 在以下系统中统一使用，实现全链路追踪：
  - Jaeger Span: trace_id 作为 OpenTelemetry trace ID
  - 日志: 每条日志包含 trace_id 字段
  - 审计日志: audit_query_log.trace_id
  - 前端: trace_id 展示给用户
  - WebSocket 消息: 每条消息包含 trace_id
```

---

## 6. 告警规则

### 6.1 Alertmanager 配置

```yaml
# alertmanager/alertmanager.yaml
global:
  resolve_timeout: 5m

route:
  receiver: default
  group_by: ['alertname', 'severity']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - match:
        severity: critical
      receiver: critical-alerts
      repeat_interval: 1h

receivers:
  - name: default
    webhook_configs:
      - url: 'http://alert-webhook:9095/webhook'  # 企业微信/钉钉
  - name: critical-alerts
    webhook_configs:
      - url: 'http://alert-webhook:9095/webhook'
```

### 6.2 告警规则

```yaml
# prometheus/rules/honeybadge.yml
groups:
  - name: honeybadge
    rules:
      # 错误率 >5%
      - alert: HighErrorRate
        expr: |
          sum(rate(honeybadge_query_total{status!="success"}[5m]))
          / sum(rate(honeybadge_query_total[5m])) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Query error rate above 5%"

      # P95 延迟 >30s
      - alert: HighLatency
        expr: |
          histogram_quantile(0.95,
            rate(honeybadge_query_e2e_duration_seconds_bucket[5m])
          ) > 30
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "P95 query latency above 30s"

      # LLM 错误率高
      - alert: LLMHighErrorRate
        expr: |
          sum(rate(honeybadge_llm_errors_total[5m]))
          / sum(rate(honeybadge_llm_tokens_total[5m])) > 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "LLM error rate above 10%"

      # Worker 全部不可用
      - alert: NoActiveWorkers
        expr: sum(honeybadge_hiclaw_workers{status="active"}) == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "No active HiClaw workers"

      # NebulaGraph 连接池耗尽
      - alert: NebulaPoolExhausted
        expr: |
          honeybadge_nebula_pool_size{status="idle"} == 0
          AND honeybadge_nebula_pool_size{status="active"} > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "NebulaGraph connection pool exhausted"

      # 校验失败率高
      - alert: HighValidationFailRate
        expr: |
          sum(rate(honeybadge_validation_total{result="fail"}[15m]))
          / sum(rate(honeybadge_validation_total[15m])) > 0.3
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "nGQL validation failure rate above 30%"

      # ETL 超期未运行
      - alert: ETLStale
        expr: |
          (time() - honeybadge_etl_last_success_timestamp) > 93600
        for: 1h
        labels:
          severity: critical
        annotations:
          summary: "ETL pipeline has not run successfully in 26+ hours"
```
