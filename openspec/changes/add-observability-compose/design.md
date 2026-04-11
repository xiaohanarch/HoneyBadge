## Context

当前 `deploy/docker/docker-compose.yaml` 包含完整的 Phase 1 基础设施（NebulaGraph、Redis、PostgreSQL、HiClaw Manager/Workers、MCP Servers），但缺少 observability 栈。

`deploy/observability/` 目录已有完整配置：
- `prometheus/prometheus.yml` — scrape configs（但 targets 与实际 docker-compose service name 不匹配）
- `grafana/provisioning/datasources/datasources.yaml` — Prometheus + Loki + Jaeger datasources
- `grafana/provisioning/dashboards/` — HoneyBadge overview dashboard
- `loki/loki-config.yaml` — Loki 配置
- `promtail/promtail-config.yaml` — Promtail 配置（使用 Docker SD 通过 `com.honeybadge.service` label 发现容器）
- `alertmanager/alertmanager.yaml` — 告警路由规则

**问题**：
1. Prometheus scrape targets 名称与 docker-compose service name 不一致（如 `higress` vs `hiclaw-manager`）
2. Promtail 的 Docker SD 配置期望所有容器有 `com.honeybadge.service` label，但当前服务未添加
3. Observability 服务未接入 docker-compose

## Goals / Non-Goals

**Goals:**
- 在 docker-compose 中以 `observability` profile 新增 Prometheus、Grafana、Loki、Promtail、Alertmanager
- 配置挂载现有 `deploy/observability/` 配置文件，无需重复创建
- 通过 Docker labels 实现 Promtail 自动服务发现
- 修正 Prometheus scrape targets 以匹配实际 service names

**Non-Goals:**
- 不修改 Phase 1 核心服务的业务逻辑
- 不添加 Jaeger（starter.md 提及但当前 observability config 中无 Jaeger 配置，暂不接入）
- 不修改 Kubernetes 部署配置（仅针对 docker-compose）

## Decisions

### 1. 使用 Docker profile 管理 observability 服务

**Decision**: 将 observability 服务放入 `observability` profile，使用 `docker compose --profile observability up` 启用。

**Rationale**: 不是所有开发/演示场景都需要 observability，按需启用避免资源占用。

**Alternatives considered**:
- Always-on: 所有环境都运行，增加资源消耗和复杂度
- Separate compose file: 维护成本高，跨服务引用困难

### 2. Prometheus scrape 架构

**Decision**: Prometheus 直接 scrape docker-compose 服务的 metrics endpoints，不通过额外 exporter。

**Rationale**:
- HiClaw Manager 内置 Prometheus metrics（`/metrics` endpoint）
- NebulaGraph 的 graphd/storaged 内置 metrics endpoints
- 避免额外维护 exporter 容器

**Note**: 当前 `prometheus.yml` 中 `nebula-exporter` job 需要 exporter 容器，但 compose 中未定义。可选：使用 NebulaGraph 内置 metrics 或移除该 job。

### 3. Promtail 日志收集

**Decision**: Promtail 通过 Docker socket 和 `com.honeybadge.service` label 自动发现所有带标签的容器。

**Rationale**:
- 服务只需添加 label，无需修改日志配置
- 支持 Higress（io.caddy.service）和 HoneyBadge（com.honeybadge.service）两套 label

**要求**: 所有 honeybadge-* 服务添加 `com.honeybadge.service` label。

### 4. Grafana 端口

**Decision**: Grafana 映射到 `3030`（避开 3000 frontend）。

**Rationale**: Frontend 已占用 3000 端口，Grafana 默认也是 3000，需要避免冲突。

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Promtail 需要访问 `/var/run/docker.sock`，存在权限安全问题 | 仅在本地开发环境使用，生产环境应使用 logging driver |
| Prometheus scrape targets 与实际服务不匹配 | 更新 `prometheus.yml` 使用实际 docker-compose service names |
| Alertmanager 需要外部 webhook 才能发送告警 | 默认 webhook receiver 指向 `alert-webhook`（需自行实现），生产环境配置真实渠道 |

## Migration Plan

1. **更新 `deploy/observability/prometheus/prometheus.yml`**
   - 将 `higress` → `hiclaw-manager`
   - 移除/注释 `nebula-exporter` job（无对应容器）
   - 将 worker targets 更新为实际 service names

2. **修改 `docker-compose.yaml`**
   - 新增 `prometheus` service（profile: observability）
   - 新增 `grafana` service（profile: observability，port 3030:3030）
   - 新增 `loki` service（profile: observability）
   - 新增 `promtail` service（profile: observability，需挂载 `/var/run/docker.sock`）
   - 新增 `alertmanager` service（profile: observability）
   - 为所有 honeybadge-* 服务添加 labels

3. **验证**
   - `docker compose --profile observability up -d`
   - 确认 Prometheus targets 全部 UP
   - 确认 Grafana 可访问（admin/admin123）
   - 确认 Loki 收到日志

## Open Questions

1. **NebulaGraph metrics**: 内置 metrics 在哪个端口？当前 prometheus.yml 配的 13000/13001 是否正确？
2. **Jaeger**: 是否需要接入分布式追踪？如需要，需新增 jaeger-all-in-one 容器
3. **Alertmanager webhook**: 是否需要实现 `alert-webhook` 服务？
