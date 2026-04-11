## Why

Phase 1 架构要求可观测性栈（Prometheus + Grafana + Loki + Alertmanager），但当前 `docker-compose.yaml` 中未集成这些组件。`deploy/observability/` 目录已有完整的配置文件，但服务未接入 compose，无法在本地开发/演示环境中使用。

在 compose 中接入 observability 后，可实现：
- 实时监控 HiClaw Workers / MCP Servers / NebulaGraph 指标
- 日志统一收集与查询
- 告警触发与通知
- 分布式追踪（Jaeger）

## What Changes

- 新增 **Prometheus** 服务：指标采集与存储
- 新增 **Grafana** 服务：可视化仪表板
- 新增 **Loki** 服务：日志聚合
- 新增 **Promtail** 服务：日志采集（通过 Docker labels 自动发现服务）
- 新增 **Alertmanager** 服务：告警路由与通知
- 更新 **docker-compose.yaml**：添加 `observability` profile，按需启用
- 更新 **deploy/observability/prometheus/prometheus.yml**：适配实际 service names
- 为现有服务添加 Docker labels，供 Promtail 自动发现

## Capabilities

### New Capabilities

- `observability-stack`: 在 docker-compose 中集成 Prometheus / Grafana / Loki / Promtail / Alertmanager，提供指标、日志、告警三大支柱的可观测性基础设施

## Impact

- **新增 services**: prometheus, grafana, loki, promtail, alertmanager
- **修改 services**: 所有现有服务添加 `com.honeybadge.service` label
- **配置文件**: `deploy/observability/prometheus/prometheus.yml` 需要更新 scrape targets
- **端口占用**:
  - Prometheus: 9090
  - Grafana: 3030
  - Loki: 3100
  - Alertmanager: 9093
