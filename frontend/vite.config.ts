import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import AutoImport from 'unplugin-auto-import/vite';
import Components from 'unplugin-vue-components/vite';
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers';
import { resolve } from 'path';

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
      imports: ['vue', 'vue-router', 'pinia'],
      dts: 'src/auto-imports.d.ts',
    }),
    Components({
      resolvers: [ElementPlusResolver()],
      dts: 'src/components.d.ts',
    }),
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  optimizeDeps: {
    include: [
      'element-plus',
      'element-plus/es',
      '@element-plus/icons-vue',
      'marked',
      'axios',
      'vue',
      'vue-router',
      'pinia',
      // Pre-include Element Plus component styles to prevent mid-session reloads
      'element-plus/es/components/base/style/css',
      'element-plus/es/components/form/style/css',
      'element-plus/es/components/button/style/css',
      'element-plus/es/components/form-item/style/css',
      'element-plus/es/components/input/style/css',
      'element-plus/es/components/steps/style/css',
      'element-plus/es/components/step/style/css',
      'element-plus/es/components/avatar/style/css',
      'element-plus/es/components/tag/style/css',
      'element-plus/es/components/scrollbar/style/css',
      'element-plus/es/components/empty/style/css',
      'element-plus/es/components/dropdown/style/css',
      'element-plus/es/components/dropdown-menu/style/css',
      'element-plus/es/components/dropdown-item/style/css',
      'element-plus/es/components/icon/style/css',
      'element-plus/es/components/alert/style/css',
      'element-plus/es/components/tooltip/style/css',
      'element-plus/es/components/collapse/style/css',
      'element-plus/es/components/collapse-item/style/css',
      'element-plus/es/components/table/style/css',
      'element-plus/es/components/table-column/style/css',
      'element-plus/es/components/message/style/css',
      'element-plus/es/components/message-box/style/css',
    ],
  },
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8090',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8090',
        ws: true,
      },
    },
  },
});
