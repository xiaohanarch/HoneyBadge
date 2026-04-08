<template>
  <router-view />
</template>

<script setup lang="ts">
// Root component - router handles all views
</script>

<style lang="scss">
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html,
body,
#app {
  height: 100%;
  font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Hiragino Sans GB',
    'Microsoft YaHei', Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

// Element Plus 全局样式覆盖
.el-message {
  z-index: 9999 !important;
}
</style>
