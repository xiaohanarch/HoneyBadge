<template>
  <div class="audit-view">
    <div class="audit-header">
      <h2>审计查询</h2>
      <el-input
        v-model="traceIdInput"
        placeholder="输入 Trace ID"
        style="width: 400px"
        clearable
        @keyup.enter="queryAudit"
      >
        <template #append>
          <el-button :loading="loading" @click="queryAudit">查询</el-button>
        </template>
      </el-input>
    </div>

    <el-card v-if="error" class="error-card">
      <el-alert type="error" :closable="false">{{ error }}</el-alert>
    </el-card>

    <div v-if="auditData" class="audit-content">
      <el-descriptions title="审计记录" :column="2" border>
        <el-descriptions-item label="Trace ID">
          {{ auditData.trace_id }}
        </el-descriptions-item>
        <el-descriptions-item label="会话ID">
          {{ auditData.session_id }}
        </el-descriptions-item>
        <el-descriptions-item label="用户问题">
          {{ auditData.question }}
        </el-descriptions-item>
        <el-descriptions-item label="执行时间">
          {{ formatDateTime(auditData.created_at) }}
        </el-descriptions-item>
        <el-descriptions-item label="执行时长">
          {{ auditData.execution_time_ms }}ms
        </el-descriptions-item>
        <el-descriptions-item label="LLM模型">
          {{ auditData.llm_model }}
        </el-descriptions-item>
        <el-descriptions-item label="执行Cypher" :span="2">
          <code class="cypher-code">{{ auditData.cypher }}</code>
        </el-descriptions-item>
        <el-descriptions-item label="摘要" :span="2">
          {{ auditData.summary }}
        </el-descriptions-item>
      </el-descriptions>

      <el-card v-if="auditData.rows && auditData.rows.length" class="result-card">
        <template #header>
          <span>查询结果 ({{ auditData.rows.length }} 条)</span>
        </template>
        <el-table :data="auditData.rows" stripe max-height="400">
          <el-table-column
            v-for="col in auditData.columns"
            :key="col"
            :prop="col"
            :label="col"
            min-width="120"
            show-overflow-tooltip
          />
        </el-table>
      </el-card>
    </div>

    <div v-else-if="!loading && !error" class="empty-state">
      <el-empty description="输入 Trace ID 查询审计详情" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage } from 'element-plus';
import { auditApi } from '@/api/http';

const route = useRoute();
const traceIdInput = ref('');
const auditData = ref<any>(null);
const loading = ref(false);
const error = ref('');

onMounted(() => {
  const traceId = route.query.trace_id as string;
  if (traceId) {
    traceIdInput.value = traceId;
    queryAudit();
  }
});

async function queryAudit() {
  const traceId = traceIdInput.value.trim();
  if (!traceId) {
    ElMessage.warning('请输入 Trace ID');
    return;
  }

  loading.value = true;
  error.value = '';
  auditData.value = null;

  try {
    const response = await auditApi.getAuditTrail(traceId);
    auditData.value = response.data;
  } catch (err: any) {
    error.value = err?.response?.data?.message || '查询失败';
    ElMessage.error(error.value);
  } finally {
    loading.value = false;
  }
}

function formatDateTime(ts: string): string {
  if (!ts) return 'N/A';
  const d = new Date(ts);
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    fractionalSecondDigits: 3,
  });
}
</script>

<style scoped lang="scss">
.audit-view {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}

.audit-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;

  h2 {
    margin: 0;
    font-size: 20px;
    font-weight: 600;
  }
}

.error-card {
  margin-bottom: 16px;
}

.audit-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.cypher-code {
  display: block;
  background: #f5f7fa;
  padding: 8px 12px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-all;
}

.empty-state {
  padding: 60px 0;
}
</style>
