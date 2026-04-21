# HoneyBadge /chat 性能优化设计文档

**日期：** 2026-04-21
**状态：** 已批准，待实施
**范围：** Manager fast-query skill + Worker 上下文裁剪 + Worker 并发提升 + MCP transport 优化

---

## 背景与问题

### 实测数据

通过 Higress 网关日志分析（402 次 LLM 调用样本）：

| 组件 | 平均 duration | p50 | p90 | 平均 context 大小 |
|------|-------------|-----|-----|-----------------|
| Manager LLM 调用 | 5,738ms | 4,498ms | 11,208ms | 73KB |
| Worker LLM 调用 | 6,638ms | 5,470ms | 12,645ms | **227KB** |

### 当前请求路径（简单查询）

```
Browser → Tuwunel → Manager LLM×1 → Worker LLM×2 → MCP LLM×1 → NebulaGraph
                                                                      ↓
Browser ← Tuwunel ← Manager LLM×1 ← Worker LLM×1 ←────────────────────
```

- **5–6 次串行 LLM 调用**，每次 4–7s
- **端到端时延：25–40s**（对比直接 openclaw ~8–12s）
- MCP server 自带独立 LLM 调用（`generate_ngql`），与 Worker 推理形成冗余
- Worker 上下文随会话累积，均值 227KB（约 57K tokens），无上限

### 根本原因

1. 简单 CRUD 查询不需要 Worker 的多步编排，但仍走完整 5-6 LLM 的路径
2. Worker context 无限增长，每次 LLM 调用携带大量历史
3. 每次 `mcporter call` 触发 SSE 握手（~140ms），累计浪费
4. 单 Worker 并发上限 4，多用户时任务排队

---

## 目标

| 指标 | 当前 | 目标 |
|------|------|------|
| 简单查询端到端时延 | 25–40s | **8–12s** |
| Worker LLM 输入大小 | ~227KB | ~160KB（削减 30%） |
| 单 Worker pod 并发 | 4 | **8** |
| mcporter 调用握手开销 | ~140ms/次 | ~5ms/次 |

---

## 设计方案（方案 B：统一 performance release）

四项改动作为一次部署上线，单个 PR，一次 `init-workers.sh` 重跑。

---

## 改动一：Worker 上下文裁剪 + 并发提升

### 文件

`deploy/hiclaw/init-workers.sh`（Worker openclaw.json 模板）

### 变更

在 `agents.defaults` 新增三个字段：

```json
{
  "agents": {
    "defaults": {
      "timeoutSeconds": 1800,
      "maxConcurrent": 8,
      "contextTokens": 40000,
      "contextPruning": {
        "mode": "cache-ttl",
        "keepLastAssistants": 10,
        "softTrimRatio": 0.7,
        "hardClearRatio": 0.9,
        "hardClear": {
          "enabled": true,
          "placeholder": "[历史对话已自动压缩，当前任务上下文完整保留]"
        }
      },
      "subagents": { "maxConcurrent": 8 },
      "model": { "primary": "hiclaw-gateway/MiniMax-M2.7" },
      "workspace": "~"
    }
  }
}
```

### 字段说明

| 字段 | 当前值 | 新值 | 效果 |
|------|--------|------|------|
| `maxConcurrent` | 4 | 8 | 单 pod 最多同时处理 8 个 Matrix 消息 |
| `contextTokens` | 未设置 | 40,000 | context 硬上限（当前均值约 57K tokens） |
| `contextPruning.keepLastAssistants` | — | 10 | 软裁剪时保留最近 10 轮助手回复 |
| `contextPruning.softTrimRatio` | — | 0.7 | 达到 28K tokens 时触发软裁剪 |
| `contextPruning.hardClearRatio` | — | 0.9 | 达到 36K tokens 时触发硬清除 |

### 生效方式

重跑 `init-workers.sh` 推送到 MinIO，Worker 通过 `file-sync` 热加载，**无需重启 pod**。

---

## 改动二：Manager fast-query skill

### 触发逻辑

Manager SOUL.md 在现有路由规则里新增第三条路径。

**走 fast-query 的条件（须同时满足）：**
- 问题涉及单一实体类型的查找、计数或详情
- 包含关键词：查询/搜索/列出/查找/一共/总数/数量 + 实体名
- 不含分析性词汇：异常/欺诈/风险/对比/趋势/三单/匹配/检测
- 当前会话是首次提问（无前序上下文依赖）

**继续走 Worker 路径的条件（任意一项）：**
- 包含分析性词汇
- 跨实体关联查询
- 会话已有多轮上下文（follow-up 问题）
- fast-query.sh 返回非零退出码（自动降级）

### 新增文件

`deploy/hiclaw/manager-config/skills/fast-query/fast-query.sh`

```bash
#!/usr/bin/env bash
# fast-query.sh — Manager 直通 MCP，绕过 Worker
# 用法：bash fast-query.sh --question "..." --user-id "admin" --task-id "..."
set -euo pipefail

QUESTION=""
USER_ID=""
TASK_ID="fast-$(date +%s)"

while [[ $# -gt 0 ]]; do
  case $1 in
    --question)  QUESTION="$2";  shift 2 ;;
    --user-id)   USER_ID="$2";   shift 2 ;;
    --task-id)   TASK_ID="$2";   shift 2 ;;
    *) shift ;;
  esac
done

[[ -z "$QUESTION" ]] && { echo '{"error":"--question is required"}'; exit 1; }

# Step 1: 生成 nGQL
NGQL_RESP=$(mcporter call honeybadge-nebula.generate_query \
  --args "{\"question\":\"$QUESTION\"}")
NGQL=$(echo "$NGQL_RESP" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d['ngql'])" 2>/dev/null) \
  || { echo '{"error":"nGQL generation failed"}'; exit 2; }

# Step 2: 带权限执行
USER_CTX="{}"
[[ -n "$USER_ID" ]] && USER_CTX="{\"user_id\":\"$USER_ID\"}"

RESULT=$(mcporter call honeybadge-nebula.validate_and_execute \
  --args "{\"ngql\":\"$NGQL\",\"user_context\":$USER_CTX}") \
  || { echo '{"error":"query execution failed"}'; exit 3; }

echo "$RESULT"
```

### SOUL.md 新增路由规则

在 "Core Behavior" 第 4 条（Route based on intent）之后新增第 5 条：

```markdown
5. **Fast-query path（简单单步查询）：**
   当问题满足以下全部条件时，使用 fast-query skill，**不派发给 Worker**：
   - 问题涉及单一实体类型的查找、计数或详情
   - 不含分析性词汇（异常/欺诈/趋势/对比/三单匹配）
   - 当前会话是首次提问（无前序上下文依赖）

   执行方式：
   ```bash
   bash /opt/honeybadge/config/manager/agent/skills/fast-query/fast-query.sh \
     --question "$USER_QUESTION" \
     --user-id "$USER_ID" \
     --task-id "fast-$(date +%s%3N)"
   ```
   读取 JSON 输出后，直接向用户返回格式化结果。
   **不在 state.json 注册此类任务**（快速通道，无需任务生命周期管理）。

   **如果脚本退出码非零**，立即将原始问题降级派发给 graph-worker，不告知用户内部路径切换。
```

### 预期效果

| 指标 | 当前 | fast-query 后 |
|------|------|--------------|
| LLM 调用次数 | 5–6 次 | 2 次（Manager + MCP） |
| 端到端时延 | 25–40s | **8–12s** |
| 覆盖比例 | — | 约 60–70% 的日常查询 |

### K8s ConfigMap 挂载

`deploy/k8s/hiclaw/manager.yaml` 新增 volume mount：

```yaml
volumeMounts:
  - name: fast-query-skill
    mountPath: /opt/honeybadge/config/manager/agent/skills/fast-query
    readOnly: true
volumes:
  - name: fast-query-skill
    configMap:
      name: hiclaw-fast-query-skill
      defaultMode: 0755
```

---

## 改动三：MCP Transport SSE → streamable-http

### 背景

每次 `mcporter call` 的 SSE 握手流程：

```
GET /sse      → 建立 SSE 连接，获得 session_id   (~100ms)
POST /messages → 发送工具调用请求                  (~20ms)
POST /messages → 接收工具响应                      (~20ms)
连接关闭
```

每次工具调用额外消耗 ~140ms，Worker 单任务调用 mcporter 2-3 次，累计 ~300-420ms。

### 代码改动（三个 MCP server 各一行）

```python
# 改前
mcp.run(transport="sse")

# 改后
mcp.run(transport="streamable-http")
```

文件：
- `mcp-servers/honeybadge-nebula-mcp/server.py`
- `mcp-servers/honeybadge-audit-mcp/server.py`
- `mcp-servers/honeybadge-cache-mcp/server.py`

### mcporter.json URL 更新

`deploy/hiclaw/init-workers.sh` 里 mcporter.json 模板：

```json
{
  "mcpServers": {
    "honeybadge-nebula": { "baseUrl": "http://honeybadge-nebula-mcp:8000/mcp" },
    "honeybadge-audit":  { "baseUrl": "http://honeybadge-audit-mcp:8000/mcp"  },
    "honeybadge-cache":  { "baseUrl": "http://honeybadge-cache-mcp:8000/mcp"  }
  }
}
```

`/sse` → `/mcp`（FastMCP streamable-http 默认挂载路径）。

### 前置确认

```bash
kubectl -n honeybadge exec deploy/honeybadge-nebula-mcp -- \
  pip show fastmcp | grep Version
# 需要 FastMCP >= 2.3.0
# 如不满足，在 requirements.txt 升级
```

### 对比

| | SSE | streamable-http |
|--|-----|----------------|
| 每次调用开销 | ~140ms 握手 | ~5ms |
| 状态 | 有状态（session_id） | 无状态 |
| K8s healthcheck | 不变（socket 检查 port 8000） | 不变 |

---

## 部署步骤

```bash
# 1. 验证 FastMCP 版本
kubectl -n honeybadge exec deploy/honeybadge-nebula-mcp -- pip show fastmcp

# 2. 重建三个 MCP server 镜像（transport 变更）并推送
# （具体镜像 tag 策略按现有 CI/CD 流程）
kubectl -n honeybadge rollout restart deploy/honeybadge-nebula-mcp
kubectl -n honeybadge rollout restart deploy/honeybadge-audit-mcp
kubectl -n honeybadge rollout restart deploy/honeybadge-cache-mcp
kubectl -n honeybadge rollout status deploy/honeybadge-nebula-mcp

# 3. 应用 Manager ConfigMap（fast-query skill + SOUL.md）
kubectl -n honeybadge apply -f deploy/k8s/hiclaw/manager.yaml
kubectl -n honeybadge rollout restart deploy/hiclaw-manager

# 4. 重跑 init-workers.sh（推送新 openclaw.json + mcporter.json 到 MinIO）
bash deploy/hiclaw/init-workers.sh
# Worker 通过 file-sync 热加载，无需重启
```

---

## 验证检查点

| 检查项 | 验证方式 | 预期结果 |
|--------|---------|---------|
| MCP transport 切换 | `kubectl logs deploy/honeybadge-nebula-mcp` | 无 SSE 相关错误 |
| mcporter 连通性 | Manager heartbeat 日志 | `MCP Server Connectivity: OK` |
| fast-query 生效 | 发送"查询供应商总数" | Manager 日志见 `fast-query.sh` 执行，无 Worker 分发 |
| 复杂查询不受影响 | 发送"分析异常采购订单" | Manager 仍分发给 graph-worker |
| fast-query 降级 | mcporter 故意断连后发简单查询 | 自动降级到 graph-worker，用户无感知 |
| Worker 并发 | 同时发 6 个查询 | 日志显示并发处理，无排队 |
| context 裁剪 | 长对话后查看 Worker 日志 | token 用量不超过 40K |

---

## 回滚方案

每项改动独立可回滚：

| 改动 | 回滚方式 |
|------|---------|
| MCP transport | `kubectl rollout undo deploy/honeybadge-nebula-mcp`（及 audit/cache） |
| fast-query skill | 删除 ConfigMap 中 fast-query 目录 + 还原 SOUL.md，重启 Manager |
| Worker 配置 | 还原 `init-workers.sh` 模板，重跑推送，Worker 热加载 |

---

## 未来扩容预留（方案 B：多 Worker 实例）

当单 pod `maxConcurrent: 8` 不足时（MiniMax 并发限速或 CPU 瓶颈），扩容路径：

1. 为额外实例注册独立 Matrix 账号（`@graph-worker-2`, `@graph-worker-3`）
2. 更新 `AGENTS.md`，Manager 知道多个 Worker 实例
3. Manager SOUL.md 新增轮询调度逻辑（维护 worker pool，选最少任务的实例）
4. K8s 改用 StatefulSet，每个副本配置独立 Matrix 凭证 ConfigMap

触发时机：平均排队等待时间 > 10s 或单 pod CPU 持续 > 70%。

---

## 改动文件清单

```
mcp-servers/honeybadge-nebula-mcp/server.py     # transport="streamable-http"
mcp-servers/honeybadge-audit-mcp/server.py      # transport="streamable-http"
mcp-servers/honeybadge-cache-mcp/server.py      # transport="streamable-http"

deploy/hiclaw/init-workers.sh                   # openclaw.json + mcporter.json 模板更新

deploy/hiclaw/manager-config/                   # 新增目录
  skills/fast-query/fast-query.sh               # 新增 fast-query 脚本
  SOUL.md                                       # 新增 fast-query 路由规则（第 5 条）

deploy/k8s/hiclaw/manager.yaml                  # 挂载 fast-query-skill ConfigMap
```
