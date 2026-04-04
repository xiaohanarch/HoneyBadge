<template>
  <div class="cypher-block">
    <div class="code-header">
      <span class="code-lang">nGQL</span>
      <el-button
        size="small"
        :icon="CopyDocument"
        @click="handleCopy"
      >
        {{ copied ? '已复制' : '复制' }}
      </el-button>
    </div>
    <pre class="code-content"><code>{{ code }}</code></pre>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { ElMessage } from 'element-plus';
import { CopyDocument } from '@element-plus/icons-vue';

const props = defineProps<{
  code: string;
}>();

const copied = ref(false);

async function handleCopy() {
  try {
    await navigator.clipboard.writeText(props.code);
    copied.value = true;
    ElMessage.success('代码已复制');
    setTimeout(() => {
      copied.value = false;
    }, 2000);
  } catch {
    ElMessage.error('复制失败');
  }
}
</script>

<style scoped lang="scss">
.cypher-block {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
}

.code-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #f5f7fa;
  border-bottom: 1px solid #e4e7ed;

  .code-lang {
    font-size: 12px;
    font-weight: 600;
    color: #409eff;
    text-transform: uppercase;
  }
}

.code-content {
  margin: 0;
  padding: 16px;
  background: #1e1e1e;
  color: #d4d4d4;
  font-family: 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.5;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;

  code {
    font-family: inherit;
  }
}
</style>
