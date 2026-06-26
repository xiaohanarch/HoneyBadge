# v1.1.0 Baseline 快照

> 本目录存放升级到 v1.1.2 之前的 v1.1.0 运行时配置快照，用于回滚和 schema diff。

## 用途

1. **回滚 baseline**：升级失败时，用这些快照恢复到 v1.1.0 状态
2. **Schema diff**：与 v1.1.2 模板做 diff，验证 mcpServers schema 变化（**已完成 —— 结果：IDENTICAL，无变化**）

## 已提交的文件（安全，不含敏感信息）

| 文件 | 来源 | 用途 |
|------|------|------|
| `graph-worker-mcporter.json` | `honeybadge-graph-worker` 容器导出 | MCP 挂载配置 baseline（仅含 baseUrl） |
| `analytics-worker-mcporter.json` | `honeybadge-analytics-worker` 容器导出 | MCP 挂载配置 baseline（仅含 baseUrl） |
| `worker-openclaw.json.tmpl` | `honeybadge-hiclaw-manager` 容器 `/opt/hiclaw/agent/skills/worker-management/references/` | Worker 配置模板（上游镜像通用文件） |
| `manager-openclaw.json.tmpl` | `honeybadge-hiclaw-manager` 容器 `/opt/hiclaw/configs/` | Manager 配置模板（上游镜像通用文件） |
| `generate-worker-config.sh` | `honeybadge-hiclaw-manager` 容器 `/opt/hiclaw/agent/skills/worker-management/scripts/` | Worker 配置生成脚本（上游镜像通用文件） |

## 未提交的文件（含敏感信息 —— 需要时从运行中容器导出）

以下文件含真实凭据（Matrix token、LLM apiKey、gateway accessToken），**不应提交到 git**。需要时从运行中的 v1.1.0 容器导出：

| 文件 | 来源容器 | 容器内路径 | 敏感内容 |
|------|---------|-----------|---------|
| `graph-worker-openclaw.json` | `honeybadge-graph-worker` | `/root/hiclaw-fs/agents/graph-worker/openclaw.json` | Matrix token, LLM apiKey |
| `analytics-worker-openclaw.json` | `honeybadge-analytics-worker` | `/root/hiclaw-fs/agents/analytics-worker/openclaw.json` | Matrix token, LLM apiKey |
| `manager-openclaw.json` | `honeybadge-hiclaw-manager` | `/root/manager-workspace/openclaw.json` | Gateway accessToken |
| `workers-registry.json` | `honeybadge-hiclaw-manager` | `/root/manager-workspace/workers-registry.json` | Matrix room_id, user_id |

## 导出命令

在 v1.1.0 docker-compose 栈正常运行时，从仓库根目录执行：

```bash
# 确保容器在运行
docker compose -f deploy/docker/docker-compose.yaml ps | grep hiclaw

# 导出所有 baseline 文件
mkdir -p docs/baselines/v1.1.0

docker cp honeybadge-graph-worker:/root/hiclaw-fs/agents/graph-worker/openclaw.json \
    docs/baselines/v1.1.0/graph-worker-openclaw.json

docker cp honeybadge-analytics-worker:/root/hiclaw-fs/agents/analytics-worker/openclaw.json \
    docs/baselines/v1.1.0/analytics-worker-openclaw.json

docker cp honeybadge-hiclaw-manager:/root/manager-workspace/openclaw.json \
    docs/baselines/v1.1.0/manager-openclaw.json

docker cp honeybadge-hiclaw-manager:/root/manager-workspace/workers-registry.json \
    docs/baselines/v1.1.0/workers-registry.json

docker cp honeybadge-graph-worker:/root/hiclaw-fs/config/mcporter.json \
    docs/baselines/v1.1.0/graph-worker-mcporter.json

docker cp honeybadge-analytics-worker:/root/hiclaw-fs/config/mcporter.json \
    docs/baselines/v1.1.0/analytics-worker-mcporter.json

# 验证所有文件都已导出
ls -la docs/baselines/v1.1.0/
```

## 对比命令（升级后）

```bash
# mcpServers schema diff（硬 blocker 验证）
jq '.mcpServers' docs/baselines/v1.1.0/graph-worker-openclaw.json > /tmp/mcp-v1.1.0.json
docker exec honeybadge-graph-worker cat /root/hiclaw-fs/agents/graph-worker/openclaw.json \
    | jq '.mcpServers' > /tmp/mcp-v1.1.2.json
diff /tmp/mcp-v1.1.0.json /tmp/mcp-v1.1.2.json
```

## 参考

- v1.0.9 baseline（历史）：`docs/1.1.0-upgrade-evidence/workers-registry-v109-backup.json`
- 升级计划：`docs/1.1.2-upgrade-plan.md`
- 实测记录：`UPGRADE-NOTES.md`

## 状态

- [ ] baseline 已导出
- [ ] 已提交到 `ralph/hiclaw-1.1.2-upgrade` 分支
- [ ] 已用于 v1.1.2 schema diff
