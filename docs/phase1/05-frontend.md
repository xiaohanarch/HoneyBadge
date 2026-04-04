# Vue 3 前端设计

> 版本：v1.0
> 创建日期：2026-04-04
> 依赖：`07-gateway.md`（API 路由）, `02-hiclaw-orchestration.md`（WebSocket 协议）

---

## 1. 项目脚手架

```bash
# 创建项目
npm create vite@latest honeybadge-web -- --template vue-ts

# 核心依赖
npm install vue-router@4 pinia element-plus @element-plus/icons-vue
npm install axios
npm install -D @types/node sass unplugin-vue-components unplugin-auto-import
```

### 1.1 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue 3 | 3.5.x | 前端框架 |
| TypeScript | 5.x | 类型安全 |
| Vite | 6.x | 构建工具 |
| Vue Router | 4.x | 路由 |
| Pinia | 2.x | 状态管理 |
| Element Plus | 2.x | UI 组件库 |
| Axios | 1.x | HTTP 客户端 |

### 1.2 项目结构

```
src/
├── api/                    # API 调用层
│   ├── http.ts            # Axios 实例配置
│   ├── ws.ts              # WebSocket 客户端
│   ├── auth.ts            # 认证 API
│   └── session.ts         # 会话 API
├── components/             # 通用组件
│   ├── chat/
│   │   ├── ChatMessage.vue     # 单条消息
│   │   ├── ChatInput.vue       # 输入框
│   │   ├── StreamingText.vue   # 流式文本渲染
│   │   ├── QueryResult.vue     # 查询结果展示
│   │   ├── CypherBlock.vue     # nGQL 代码展示
│   │   └── DataTable.vue       # 原始数据表格
│   ├── layout/
│   │   ├── AppHeader.vue
│   │   ├── AppSidebar.vue
│   │   └── AppMain.vue
│   └── common/
│       ├── LoadingSpinner.vue
│       └── ErrorMessage.vue
├── composables/            # 组合式函数
│   ├── useWebSocket.ts
│   ├── useAuth.ts
│   └── useChat.ts
├── router/
│   └── index.ts
├── stores/
│   ├── auth.ts            # 认证状态
│   ├── chat.ts            # 聊天状态
│   └── session.ts         # 会话列表状态
├── types/
│   └── index.ts           # 类型定义
├── views/
│   ├── LoginView.vue
│   └── ChatView.vue
├── App.vue
└── main.ts
```

---

## 2. 页面结构

### 2.1 登录页（LoginView）

```
┌─────────────────────────────────────┐
│                                     │
│         HoneyBadge Logo             │
│                                     │
│    ┌───────────────────────────┐    │
│    │ 用户名                    │    │
│    └───────────────────────────┘    │
│    ┌───────────────────────────┐    │
│    │ 密码                      │    │
│    └───────────────────────────┘    │
│    ┌───────────────────────────┐    │
│    │         登  录            │    │
│    └───────────────────────────┘    │
│                                     │
│    ── 或 ──                         │
│    [ SSO 登录 ] (预留，Phase 1 禁用) │
│                                     │
└─────────────────────────────────────┘
```

Phase 1 简化认证：用户名 + 密码，后端生成 JWT token。预留 SSO 按钮和 OAuth2 回调路由。

### 2.2 主聊天界面（ChatView）

```
┌──────────────────────────────────────────────────────┐
│ [Logo] HoneyBadge            [用户头像] [退出]       │
├──────────┬───────────────────────────────────────────┤
│          │                                           │
│ 历史会话  │  Chat Area                                │
│          │                                           │
│ ┌──────┐ │  ┌─────────────────────────────────────┐ │
│ │ 新对话 │ │  │ User: 帮我找出疑似虚假交易          │ │
│ └──────┘ │  └─────────────────────────────────────┘ │
│          │                                           │
│ Today    │  ┌─────────────────────────────────────┐ │
│ ■ 查询供  │  │ AI: 正在生成查询... ◌               │ │
│   应商..  │  │                                     │ │
│ ■ 三单匹  │  │ AI 摘要:                            │ │
│   配分析  │  │ 发现3笔疑似异常交易...               │ │
│          │  │                                     │ │
│ Yesterday │  │ ┌─ 原始数据 ──────────────[展开]──┐ │ │
│ ■ BOM展   │  │ │ 订单号  │ 采购金额 │ 发票金额   │ │ │
│   开查询  │  │ │ PO-123 │ 100,000 │ 123,000   │ │ │
│          │  │ └─────────────────────────────────┘ │ │
│          │  │                                     │ │
│          │  │ ┌─ 执行查询 ──────────────[展开]──┐ │ │
│          │  │ │ MATCH (po:PurchaseOrder)...      │ │ │
│          │  │ └─────────────────────────────────┘ │ │
│          │  │                                     │ │
│          │  │ 审计ID: TRC-20260404-00147          │ │
│          │  └─────────────────────────────────────┘ │
│          │                                           │
│          │  ┌──────────────────────────────────[↑]┐ │
│          │  │ 请输入你的问题...                     │ │
│          │  └─────────────────────────────────────┘ │
└──────────┴───────────────────────────────────────────┘
```

---

## 3. TypeScript 类型定义

```typescript
// types/index.ts

// WebSocket 消息协议
export interface WSMessage {
  type: 'query' | 'response' | 'stream' | 'progress' | 'error' | 'heartbeat';
  payload: unknown;
  trace_id?: string;
  timestamp: number;
}

export interface QueryRequest {
  type: 'query';
  payload: {
    question: string;
    session_id: string;
  };
}

export interface StreamChunk {
  type: 'stream';
  payload: {
    content: string;        // 增量文本
    phase: 'thinking' | 'cypher' | 'executing' | 'summarizing';
    done: boolean;
  };
  trace_id: string;
}

export interface ProgressUpdate {
  type: 'progress';
  payload: {
    step: string;           // 当前步骤描述
    step_number: number;    // 步骤序号 (1-based)
    total_steps: number;    // 总步骤数
    detail?: string;
  };
  trace_id: string;
}

export interface QueryResponse {
  type: 'response';
  payload: {
    summary: string;        // AI 摘要
    raw_data: Record<string, unknown>[];  // 原始数据
    columns: string[];      // 列名
    cypher: string;         // 执行的 nGQL
    trace_id: string;
    execution_time_ms: number;
    row_count: number;
  };
}

export interface ErrorResponse {
  type: 'error';
  payload: {
    code: string;           // 错误码
    message: string;        // 错误消息
    trace_id?: string;
  };
}

// 会话
export interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  status: 'active' | 'archived';
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  message_type: 'text' | 'query_result' | 'error';
  metadata?: {
    trace_id?: string;
    cypher?: string;
    raw_data?: Record<string, unknown>[];
    columns?: string[];
    execution_time_ms?: number;
  };
  created_at: string;
}

// 用户
export interface User {
  id: string;
  username: string;
  display_name: string;
  roles: string[];
  org_id?: number;
}
```

---

## 4. WebSocket 客户端设计

### 4.1 连接管理

```typescript
// composables/useWebSocket.ts
import { ref, onUnmounted } from 'vue';

export function useWebSocket(url: string, token: string) {
  const ws = ref<WebSocket | null>(null);
  const connected = ref(false);
  const reconnectAttempts = ref(0);
  const MAX_RECONNECT_ATTEMPTS = 5;
  const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000]; // 指数退避
  const HEARTBEAT_INTERVAL = 30000; // 30 秒心跳
  let heartbeatTimer: number | null = null;
  let reconnectTimer: number | null = null;

  function connect() {
    ws.value = new WebSocket(`${url}?token=${token}`);

    ws.value.onopen = () => {
      connected.value = true;
      reconnectAttempts.value = 0;
      startHeartbeat();
    };

    ws.value.onclose = (event) => {
      connected.value = false;
      stopHeartbeat();
      if (!event.wasClean && reconnectAttempts.value < MAX_RECONNECT_ATTEMPTS) {
        scheduleReconnect();
      }
    };

    ws.value.onerror = () => {
      connected.value = false;
    };
  }

  function startHeartbeat() {
    heartbeatTimer = window.setInterval(() => {
      if (ws.value?.readyState === WebSocket.OPEN) {
        ws.value.send(JSON.stringify({
          type: 'heartbeat',
          payload: {},
          timestamp: Date.now()
        }));
      }
    }, HEARTBEAT_INTERVAL);
  }

  function stopHeartbeat() {
    if (heartbeatTimer) clearInterval(heartbeatTimer);
  }

  function scheduleReconnect() {
    const delay = RECONNECT_DELAYS[
      Math.min(reconnectAttempts.value, RECONNECT_DELAYS.length - 1)
    ];
    reconnectTimer = window.setTimeout(() => {
      reconnectAttempts.value++;
      connect();
    }, delay);
  }

  function send(message: WSMessage) {
    if (ws.value?.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify(message));
    }
  }

  function onMessage(handler: (msg: WSMessage) => void) {
    if (ws.value) {
      ws.value.onmessage = (event) => {
        const msg = JSON.parse(event.data) as WSMessage;
        handler(msg);
      };
    }
  }

  function disconnect() {
    stopHeartbeat();
    if (reconnectTimer) clearTimeout(reconnectTimer);
    ws.value?.close(1000, 'Client disconnect');
  }

  onUnmounted(disconnect);

  return { connected, connect, send, onMessage, disconnect };
}
```

### 4.2 流式输出渲染

```vue
<!-- components/chat/StreamingText.vue -->
<template>
  <div class="streaming-text">
    <span v-html="renderedContent"></span>
    <span v-if="isStreaming" class="cursor">▌</span>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { marked } from 'marked';

const props = defineProps<{
  content: string;
  isStreaming: boolean;
}>();

const renderedContent = computed(() => {
  return marked.parse(props.content, { breaks: true });
});
</script>
```

### 4.3 Agent 执行步骤进度展示

```vue
<!-- components/chat/ProgressSteps.vue -->
<template>
  <div class="progress-steps">
    <el-steps :active="currentStep" direction="vertical" :space="40">
      <el-step
        v-for="step in steps"
        :key="step.number"
        :title="step.title"
        :description="step.detail"
        :status="getStepStatus(step.number)"
      />
    </el-steps>
  </div>
</template>

<script setup lang="ts">
/*
  steps 示例:
  1. 理解问题
  2. 生成查询
  3. 校验查询
  4. 执行查询
  5. 生成摘要
*/
</script>
```

---

## 5. HTTP REST API

### 5.1 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 登录（用户名+密码），返回 JWT |
| POST | `/api/auth/logout` | 登出，失效 token |
| GET | `/api/auth/me` | 获取当前用户信息 |
| POST | `/api/auth/refresh` | 刷新 token |

### 5.2 会话管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sessions` | 获取用户会话列表 |
| POST | `/api/sessions` | 创建新会话 |
| GET | `/api/sessions/:id` | 获取会话详情 |
| PUT | `/api/sessions/:id` | 更新会话（改标题） |
| DELETE | `/api/sessions/:id` | 删除会话 |
| GET | `/api/sessions/:id/messages` | 获取会话消息历史 |

### 5.3 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/version` | 版本信息 |

---

## 6. UI 组件库选型

**选择：Element Plus**

| 对比项 | Element Plus | Naive UI |
|--------|-------------|----------|
| 生态成熟度 | 高（Element UI 延续） | 中 |
| 企业级组件 | 丰富（表格/表单/对话框） | 丰富 |
| TypeScript 支持 | 好 | 非常好 |
| 主题定制 | CSS 变量 | 好（主题编辑器） |
| 文档质量 | 好 | 好 |
| 团队熟悉度 | 高（Element UI 经验） | 低 |

**选择理由**：团队对 Element UI 系列更熟悉，企业级组件丰富，降低学习成本。

### 6.1 关键组件使用

| 组件 | 用途 |
|------|------|
| `ElMessage` | 操作提示 |
| `ElTable` | 原始数据展示 |
| `ElInput` | 查询输入框 |
| `ElDrawer` | 侧边栏历史会话 |
| `ElSteps` | Agent 执行步骤 |
| `ElTag` | 状态标签 |
| `ElCollapse` | 展开/收起原始数据和 nGQL |
| `ElTooltip` | trace_id 复制提示 |
| `ElEmpty` | 空状态展示 |
