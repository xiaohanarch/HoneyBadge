<template>
  <div class="query-result">
    <el-table
      :data="displayData"
      stripe
      border
      size="small"
      max-height="400"
      style="width: 100%"
    >
      <el-table-column
        v-for="col in displayColumns"
        :key="col"
        :prop="col"
        :label="col"
        min-width="120"
        show-overflow-tooltip
      />
    </el-table>

    <div v-if="totalRows > displayRows" class="more-rows">
      <span>共 {{ totalRows }} 条记录，仅显示前 {{ displayRows }} 条</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';

const props = defineProps<{
  data: Record<string, unknown>[];
  columns: string[];
}>();

const displayRows = 100;

const displayData = computed(() => {
  return props.data.slice(0, displayRows);
});

const displayColumns = computed(() => {
  if (props.columns.length > 0) {
    return props.columns;
  }
  // 如果没有传入 columns，从数据中推断
  if (props.data.length > 0) {
    return Object.keys(props.data[0]);
  }
  return [];
});

const totalRows = computed(() => props.data.length);
</script>

<style scoped lang="scss">
.query-result {
  :deep(.el-table) {
    font-size: 13px;

    .el-table__header th {
      background-color: #f5f7fa;
      color: #606266;
      font-weight: 600;
    }
  }

  .more-rows {
    text-align: center;
    padding: 8px;
    color: #909399;
    font-size: 12px;
    background: #f5f7fa;
    border-radius: 4px;
    margin-top: 8px;
  }
}
</style>
