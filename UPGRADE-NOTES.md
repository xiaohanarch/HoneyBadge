# UPGRADE-NOTES — HiClaw v1.1.0 → v1.1.2

> 本文件记录升级过程中的实际行为差异，事后合并回 `docs/1.1.2-upgrade-plan.md` 的"实测记录"章节。

## 环境信息

- 升级日期：（待填）
- 操作人：（待填）
- 起始版本：HiClaw v1.1.0（image tag `hiclaw-{embedded,manager,worker}:v1.1.0`）
- 目标版本：HiClaw v1.1.2
- 部署形态：☐ 本地 docker-compose  ☐ K8s/k3s  ☐ ECS
- Baseline 快照：`docs/baselines/v1.1.0/`（见该目录 README 获取方法）

---

## 阶段 1 验证记录

### 1.1 v1.1.2 image 拉取

```
# 记录实际拉取的 digest
docker images | grep hiclaw
```

- `hiclaw-embedded:v1.1.2` digest：（待填）
- `hiclaw-manager:v1.1.2` digest：（待填）
- `hiclaw-worker:v1.1.2` digest：（待填）
- 多架构支持确认：☐ amd64  ☐ arm64

### 1.2 mcpServers CRD schema diff（**硬 blocker**）

对比方法：在 v1.1.0 和 v1.1.2 下分别导出 worker `openclaw.json`，diff `mcpServers` 字段结构。

```bash
# v1.1.0 baseline（已存于 docs/baselines/v1.1.0/）
# v1.1.2 导出
docker exec honeybadge-graph-worker cat /root/hiclaw-fs/agents/graph-worker/openclaw.json > /tmp/openclaw-v1.1.2.json
jq '.mcpServers' docs/baselines/v1.1.0/graph-worker-openclaw.json > /tmp/mcp-v1.1.0.json
jq '.mcpServers' /tmp/openclaw-v1.1.2.json > /tmp/mcp-v1.1.2.json
diff /tmp/mcp-v1.1.0.json /tmp/mcp-v1.1.2.json
```

**Schema 变化记录**：

- 变化摘要：（待填）
- 对 WS-19（Manager mcporter.json 直接写入）的影响：（待填）
- 对 WS-20（Worker mcporter.json 注册）的影响：（待填）
- 需要修改的文件：（待填）
- `pytest -c pytest.ini -m mcp` 结果：☐ 通过  ☐ 失败

### 1.3 Workaround 验证记录

#### can-remove-now 组

| ID | 验证结果 | 实际行为 | 删除确认 |
|----|---------|---------|---------|
| WS-02 memorySearch pop | ☐ 模板不再注入  ☐ 仍注入 | | ☐ 已删 |
| WS-04 Manager baseUrl 模板 | ☐ 模板生成正确  ☐ 仍空 host | | ☐ 已删 |
| WS-06 allowedConsumers 重建 | ☐ 重启后保留  ☐ 仍清空 | | ☐ 已删 |
| WS-12 immutable-field shim | ☐ 已迁移  ☐ 需保留 | | ☐ 已删 |
| WS-13 /root/openclaw.json 符号链接 | ☐ 死代码确认  ☐ 仍被读 | | ☐ 已删 |
| WS-14 hot-reload deadlock 注释 | — | | ☐ 已删 |

#### needs-verification 组

| ID | 验证结果 | 实际行为 | 删除确认 |
|----|---------|---------|---------|
| WS-01 reasoning: true pop | ☐ 模板不再注入  ☐ 仍注入 | | ☐ 已删 / ☐ 保留 |
| WS-03 worker baseUrl rewrite | ☐ 生成正确  ☐ 仍错误 | | ☐ 已删 / ☐ 保留 |
| WS-09 Matrix port 修正 | ☐ 正确 6167  ☐ 仍错误 | | ☐ 已删 / ☐ 保留 |
| WS-11 dangerouslyAllowPrivateNetwork | ☐ 已传播  ☐ 未传播 | | ☐ 已删 / ☐ 保留 |
| WS-19 Manager mcporter.json | 见 1.2 | | ☐ 已删 / ☐ 保留 |
| WS-20 Worker mcporter.json | 见 1.2 | | ☐ 已删 / ☐ 保留 |

### 1.4 Team Leader skill alias 检查

```bash
# 查 v1.1.2 release notes 确认被移除的 alias 名
grep -r "<旧 alias 名>" hiclaw/manager/agent/ hiclaw/workers/*/agent/ skills/*/SKILL.md
```

- 被移除的 alias 名：（待填）
- 本项目引用情况：☐ 无引用  ☐ 有引用（列出位置）
- 更新确认：☐ 不需要  ☐ 已更新

### 1.5 MinIO endpoint 验证

```bash
docker exec honeybadge-graph-worker sh -c 'echo $MINIO_ENDPOINT'
```

- 实际值：（待填）
- 预期：`:9000`（不是 `:8080`）
- 结果：☐ 通过  ☐ 失败

### 1.6 E2E 全量回归

```bash
./scripts/run-e2e-tests.sh
```

| 测试组 | 通过数 | 失败数 | 备注 |
|--------|--------|--------|------|
| auth | | | |
| chat | | | |
| session | | | |
| isolation | | | |
| permission | | | |
| antihal | | | |
| mcp | | | |
| infra | | | |
| observability | | | |
| **合计** | | | |

---

## 阶段 2 验证记录

### 2.1 K8s/ECS 迁移

- `workers-registry.json` → CRD 自动迁移：☐ 成功  ☐ 失败
- ECS 8GB 内存占用（`kubectl top pod`）：（待填）
- `init-workers.yaml` Job 是否还需要：☐ 删除  ☐ 保留
- K8s 409 重试自愈测试：☐ 通过  ☐ 失败
- Controller reconcile 保留 runtime mutation：☐ 通过  ☐ 失败

### 2.2 文档同步

- [ ] `README.md:84,354` 版本号 v1.0.9 → v1.1.2
- [ ] `CLAUDE.md` "容器重建后 DM allowlist 重置"段落修正
- [ ] `CLAUDE.md` MinIO endpoint 端口修正
- [ ] `CLAUDE.md` "aigw-local.hiclaw.io:8080" 适用性确认

---

## 意外发现 / 风险新增

（记录计划外的发现，例如新 bug、新 workaround、文档与实际不符等）

- （待填）

---

## 回滚记录

- 是否触发回滚：☐ 否  ☐ 是
- 回滚原因：（待填）
- 回滚步骤：（待填）
- 回滚后状态：（待填）
