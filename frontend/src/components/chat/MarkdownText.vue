<template>
  <div class="markdown-text" v-html="renderedContent"></div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { marked } from 'marked';

const props = defineProps<{
  content: string;
}>();

// 配置 marked
marked.setOptions({
  breaks: true,
  gfm: true,
});

const renderedContent = computed(() => {
  return marked.parse(props.content, { async: false }) as string;
});
</script>

<style scoped lang="scss">
.markdown-text {
  line-height: 1.6;

  :deep(h1),
  :deep(h2),
  :deep(h3),
  :deep(h4),
  :deep(h5),
  :deep(h6) {
    margin-top: 16px;
    margin-bottom: 8px;
    font-weight: 600;
    color: #303133;
  }

  :deep(p) {
    margin: 8px 0;
  }

  :deep(ul),
  :deep(ol) {
    padding-left: 24px;
    margin: 8px 0;
  }

  :deep(li) {
    margin: 4px 0;
  }

  :deep(code) {
    background: #f0f0f0;
    padding: 2px 6px;
    border-radius: 4px;
    font-family: 'Fira Code', 'Consolas', monospace;
    font-size: 0.9em;
  }

  :deep(pre) {
    background: #1e1e1e;
    color: #d4d4d4;
    padding: 16px;
    border-radius: 8px;
    overflow-x: auto;

    code {
      background: transparent;
      padding: 0;
      color: inherit;
    }
  }

  :deep(blockquote) {
    border-left: 4px solid #409eff;
    margin: 8px 0;
    padding: 8px 16px;
    background: #f5f7fa;
    color: #606266;
  }

  :deep(table) {
    border-collapse: collapse;
    width: 100%;
    margin: 8px 0;

    th,
    td {
      border: 1px solid #e4e7ed;
      padding: 8px 12px;
    }

    th {
      background: #f5f7fa;
      font-weight: 600;
    }
  }

  :deep(a) {
    color: #409eff;
    text-decoration: none;

    &:hover {
      text-decoration: underline;
    }
  }

  :deep(hr) {
    border: none;
    border-top: 1px solid #e4e7ed;
    margin: 16px 0;
  }
}
</style>
