<template>
  <div class="chat-message" :class="[`message-${message.role}`]">
    <div class="message-avatar">
      <el-avatar v-if="message.role === 'user'" :size="36" :icon="UserFilled" />
      <el-avatar v-else-if="message.role === 'assistant'" :size="36" :icon="ChatDotRound" />
      <el-avatar v-else :size="36" :icon="WarnTriangleFilled" />
    </div>

    <div class="message-content">
      <div class="message-header">
        <span class="message-role">
          {{ roleLabel }}
        </span>
        <span class="message-time">
          {{ formatTime(message.created_at) }}
        </span>
      </div>

      <div class="message-body">
        <!-- 文本消息 -->
        <div v-if="message.message_type === 'text'" class="message-text">
          <StreamingText :content="message.content" :is-streaming="isStreaming" />
        </div>

        <!-- 查询结果消息 -->
        <div v-else-if="message.message_type === 'query_result'" class="message-result">
          <div class="summary">
            <MarkdownText :content="message.content" />
          </div>

          <!-- 原始数据 -->
          <el-collapse v-if="message.metadata?.raw_data?.length" class="data-collapse">
            <el-collapse-item title="原始数据" name="raw-data">
              <QueryResult
                :data="message.metadata.raw_data"
                :columns="message.metadata.columns || []"
              />
            </el-collapse-item>
          </el-collapse>

          <!-- 执行查询 -->
          <el-collapse v-if="message.metadata?.cypher" class="cypher-collapse">
            <el-collapse-item title="执行查询" name="cypher">
              <CypherBlock :code="message.metadata.cypher" />
            </el-collapse-item>
          </el-collapse>

          <!-- 元信息 -->
          <div class="meta-info">
            <el-tooltip content="点击查看审计详情">
              <router-link
                v-if="message.metadata?.trace_id"
                :to="{ path: '/audit', query: { trace_id: message.metadata.trace_id } }"
                class="trace-id-link"
              >
                审计ID: {{ message.metadata.trace_id }}
              </router-link>
              <span v-else class="trace-id">审计ID: N/A</span>
            </el-tooltip>
            <el-tooltip content="点击复制 Trace ID">
              <span class="trace-id" @click="copyTraceId">
                📋
              </span>
            </el-tooltip>
            <span class="execution-time">
              执行时间: {{ formatExecutionTime(message.metadata?.execution_time_ms) }}
            </span>
          </div>
        </div>

        <!-- 错误消息 -->
        <div v-else-if="message.message_type === 'error'" class="message-error">
          <el-alert type="error" :closable="false">
            <template #title>
              <span>{{ message.content }}</span>
            </template>
          </el-alert>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { ElMessage } from 'element-plus';
import { UserFilled, ChatDotRound, WarnTriangleFilled } from '@element-plus/icons-vue';
import StreamingText from './StreamingText.vue';
import MarkdownText from './MarkdownText.vue';
import QueryResult from './QueryResult.vue';
import CypherBlock from './CypherBlock.vue';
import type { ChatMessage } from '@/types';

const props = defineProps<{
  message: ChatMessage;
}>();

const isStreaming = computed(() => false); // 可根据需要扩展

const roleLabel = computed(() => {
  switch (props.message.role) {
    case 'user':
      return '用户';
    case 'assistant':
      return '助手';
    case 'system':
      return '系统';
    default:
      return '';
  }
});

function formatTime(timestamp: string): string {
  const date = new Date(timestamp);
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatExecutionTime(ms?: number): string {
  if (ms == null) return 'N/A';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(3)}s`;
}

async function copyTraceId() {
  const traceId = props.message.metadata?.trace_id;
  if (traceId) {
    try {
      await navigator.clipboard.writeText(traceId);
      ElMessage.success('Trace ID 已复制');
    } catch {
      ElMessage.error('复制失败');
    }
  }
}
</script>

<style scoped lang="scss">
.chat-message {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;

  &.message-user {
    flex-direction: row-reverse;

    .message-content {
      align-items: flex-end;
    }

    .message-body {
      background: #409eff;
      color: white;
      border-radius: 16px 16px 4px 16px;
    }
  }

  &.message-assistant {
    .message-body {
      background: white;
      border-radius: 16px 16px 16px 4px;
      box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
    }
  }

  &.message-system {
    .message-body {
      background: #fdf6ec;
      border-radius: 16px;
    }
  }
}

.message-avatar {
  flex-shrink: 0;
}

.message-content {
  display: flex;
  flex-direction: column;
  max-width: 80%;
}

.message-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  font-size: 12px;

  .message-role {
    color: #909399;
  }

  .message-time {
    color: #c0c4cc;
  }
}

.message-body {
  padding: 12px 16px;
}

.message-text {
  line-height: 1.6;
  white-space: pre-wrap;
}

.message-result {
  .summary {
    margin-bottom: 16px;
    line-height: 1.6;
  }

  .data-collapse,
  .cypher-collapse {
    margin-bottom: 12px;
  }

  .meta-info {
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    font-size: 12px;
    color: #909399;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid #f0f0f0;

    .trace-id,
    .trace-id-link {
      cursor: pointer;
      color: #409eff;
      text-decoration: none;

      &:hover {
        color: #66b1ff;
      }
    }

    .execution-time {
      color: #67c23a;
    }
  }
}

.message-error {
  :deep(.el-alert) {
    padding: 8px 16px;

    .el-alert__title {
      font-size: 14px;
    }
  }
}
</style>
