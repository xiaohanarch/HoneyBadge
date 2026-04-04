<template>
  <div class="streaming-text">
    <span v-html="renderedContent"></span>
    <span v-if="isStreaming" class="cursor">▌</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { marked } from 'marked';

const props = defineProps<{
  content: string;
  isStreaming: boolean;
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
.streaming-text {
  line-height: 1.6;
  white-space: pre-wrap;

  .cursor {
    display: inline-block;
    animation: blink 1s infinite;
    color: #409eff;
  }
}

@keyframes blink {
  0%, 50% {
    opacity: 1;
  }
  51%, 100% {
    opacity: 0;
  }
}
</style>
