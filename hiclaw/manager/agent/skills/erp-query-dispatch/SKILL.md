---
name: erp-query-dispatch
description: Dispatch ERP queries to Workers. Handles task creation, MinIO sync, state registration, and Matrix room dispatch.
assign_when: User asks about ERP data (供应商, 采购, 发票, 付款, 库存, 订单, 分析, 异常, fraud) or message starts with "erp问题"
---

# ERP Query Dispatch

Full dispatch procedure for ERP questions. Uses `dispatch-to-worker.sh` to send @mentions to the correct Worker room via Matrix API.

## Step 1 — Route to Worker

Determine the target worker based on the user's intent:

| Intent keywords | Worker | Skill to invoke |
|----------------|--------|-----------------|
| 查询/查找/搜索/列出/多少/哪个/供应商/采购/发票/付款/库存/收货/物料/订单 | `graph-worker` | `cypher-query` |
| 分析/趋势/异常/检测/对比/统计/fraud/三方匹配 | `analytics-worker` | `anomaly-detection` |
| 分析/趋势/对比/统计 (non-fraud) | `analytics-worker` | `multi-step-analysis` |
| Ambiguous but likely ERP-related | `graph-worker` | `cypher-query` |

Set variables:
```
WORKER_NAME="graph-worker"  # or "analytics-worker"
SKILL_NAME="cypher-query"   # or "anomaly-detection" / "multi-step-analysis"
```

## Step 2 — Create Task and Push to MinIO

Use `exec` to create the task directory, write meta.json + spec.md, and push to MinIO:

```bash
TASK_ID="task-$(date -u '+%Y%m%d-%H%M%S')"
TASK_DIR="/root/hiclaw-fs/shared/tasks/$TASK_ID"
WORKER_ROOM_ID=$(python3 -c "import json; r=json.load(open('/root/workers-registry.json')); print(r['workers']['$WORKER_NAME']['room_id'])")
mkdir -p "$TASK_DIR"

# Resolve user_mxid from x-hb-auth JWT (see "User Identity Propagation" in SOUL.md)
USER_ID="${user_id:-anonymous}"   # LLM substitutes the extracted username
USER_MXID="@${USER_ID}:matrix-local.hiclaw.io"

# Resolve the user's DM room via Manager's m.direct account data.
# This is the anchor that lets Step 6 forward the result back to the correct room.
export USER_MXID
USER_ROOM_ID=$(python3 << 'RESOLVE_EOF'
import json, urllib.request, urllib.parse, os
cfg = json.load(open("/root/manager-workspace/openclaw.json"))
token = cfg["channels"]["matrix"]["accessToken"]
mgr_uid = "@manager:matrix-local.hiclaw.io"
user_mxid = os.environ.get("USER_MXID", "")
enc_mgr = urllib.parse.quote(mgr_uid, safe="")
try:
    req = urllib.request.Request(
        f"http://127.0.0.1:6167/_matrix/client/v3/user/{enc_mgr}/account_data/m.direct",
        headers={"Authorization": "Bearer " + token}
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        m_direct = json.loads(r.read())
    rooms = m_direct.get(user_mxid, [])
    print(rooms[0] if rooms else "")
except Exception:
    print("")
RESOLVE_EOF
)

if [ -z "$USER_ROOM_ID" ]; then
    echo "WARNING: Could not resolve user DM room for $USER_MXID" >&2
fi

cat > "$TASK_DIR/meta.json" << EOF
{
  "task_id": "$TASK_ID",
  "type": "finite",
  "status": "assigned",
  "title": "<1-line summary>",
  "assigned_to": "$WORKER_NAME",
  "room_id": "$WORKER_ROOM_ID",
  "user_id": "$USER_ID",
  "user_mxid": "$USER_MXID",
  "user_room_id": "$USER_ROOM_ID",
  "created_at": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
}
EOF

cat > "$TASK_DIR/spec.md" << EOF
# Task: <user's question>
user_id: <username or "anonymous">
question: <exact question from the user>
## Expected Output
<describe what the worker should return>
EOF

mc cp "$TASK_DIR/meta.json" "hiclaw/hiclaw-storage/shared/tasks/$TASK_ID/meta.json"
mc cp "$TASK_DIR/spec.md" "hiclaw/hiclaw-storage/shared/tasks/$TASK_ID/spec.md"
```

## Step 3 — Register in state.json

```bash
bash /opt/hiclaw/agent/skills/task-management/scripts/manage-state.sh \
  --action add-finite \
  --task-id "$TASK_ID" \
  --title "<1-line summary>" \
  --assigned-to "$WORKER_NAME" \
  --room-id "$WORKER_ROOM_ID"
```

## Step 4 — Dispatch to Worker Room (CRITICAL)

**DO NOT @mention the worker in your reply.** Use `exec` to run the dispatch script — it sends the message directly to the Worker's dedicated Matrix room:

```bash
DISPATCH_SCRIPT="/opt/honeybadge/config/manager/agent/skills/erp-query-dispatch/scripts/dispatch-to-worker.sh"
bash "$DISPATCH_SCRIPT" \
  --worker "$WORKER_NAME" \
  --task-id "$TASK_ID" \
  --message "@${WORKER_NAME}:matrix-local.hiclaw.io Task $TASK_ID: <1-line summary>

Use your $SKILL_NAME skill. task-id: $TASK_ID, user_id: <username>"
```

- Output `DISPATCH_OK` → proceed to Step 5
- Output `DISPATCH_ERROR` → inform user the Worker is unavailable

## Step 5 — Acknowledge User

Reply to the user: "已转交给 $WORKER_NAME 处理，任务编号 $TASK_ID，预计需要1-2分钟"

**Then RETURN — do NOT wait for the Worker's response.**

## Step 6 — When Worker Replies, Forward to User (CRITICAL)

When a Worker @mentions you with completion in its worker room, **你必须用 `forward-to-user.sh` 把总结发到用户的 DM 房间**，绝不使用默认的 `message`/`replyMessage` 工具——因为它会把消息回给 worker 房间（用户看不到）。

```bash
FORWARD_SCRIPT="/opt/honeybadge/config/manager/agent/skills/erp-query-dispatch/scripts/forward-to-user.sh"
SUMMARY=$(cat << 'SUM'
✅ 任务 $TASK_ID 已完成

<Worker 结果的精炼摘要，不超过 200 字。完整报告见 MinIO>
SUM
)
FWD_OUT=$(echo "$SUMMARY" | bash "$FORWARD_SCRIPT" --task-id "$TASK_ID" --content -)
echo "$FWD_OUT"

if echo "$FWD_OUT" | grep -q "FORWARD_OK"; then
    # Mark as delivered so result-watcher does not send a duplicate
    touch "/tmp/.watcher-delivered-$TASK_ID"
fi
```

- 输出 `FORWARD_OK` → 任务闭环
- 输出 `FORWARD_ERROR` → 用 `message` 工具向 hb-admin 发错误通知

**绝对规则**：Worker 的任务结果永远不能通过 `message`/`replyMessage` 发——只能用 `forward-to-user.sh`。

**注意**：`result-watcher.sh` 是后台兜底进程，会在交付成功后检查 `/tmp/.watcher-delivered-$TASK_ID` 标记并退出，不会重复交付。
