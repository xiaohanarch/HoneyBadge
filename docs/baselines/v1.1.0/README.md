# v1.1.0 Baseline 快照

> 本目录存放升级到 v1.1.2 之前的 v1.1.0 运行时配置快照，用于回滚和 schema diff。

## 用途

1. **回滚 baseline**：升级失败时，用这些快照恢复到 v1.1.0 状态
2. **Schema diff**：与 v1.1.2 生成的配置做 diff，识别破坏性变化（特别是 `mcpServers` CRD 重构）

## 需要导出的文件

从运行中的 v1.1.0 容器导出以下文件：

| 文件 | 来源容器 | 容器内路径 | 用途 |
|------|---------|-----------|------|
| `graph-worker-openclaw.json` | `honeybadge-graph-worker` | `/root/hiclaw-fs/agents/graph-worker/openclaw.json` | Worker 配置 baseline |
| `analytics-worker-openclaw.json` | `honeybadge-analytics-worker` | `/root/hiclaw-fs/agents/analytics-worker/openclaw.json` | Worker 配置 baseline |
| `manager-openclaw.json` | `honeybadge-hiclaw-manager` | `/root/manager-workspace/openclaw.json` | Manager 配置 baseline |
| `workers-registry.json` | `honeybadge-hiclaw-manager` | `/root/manager-workspace/workers-registry.json` | Worker 注册表 baseline |
| `graph-worker-mcporter.json` | `honeybadge-graph-worker` | `/root/hiclaw-fs/config/mcporter.json` | MCP 挂载配置 baseline |
| `analytics-worker-mcporter.json` | `honeybadge-analytics-worker` | `/root/hiclaw-fs/config/mcporter.json` | MCP 挂载配置 baseline |

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
