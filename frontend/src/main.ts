import { createApp } from 'vue';
import { createPinia } from 'pinia';
import ElementPlus from 'element-plus';
import 'element-plus/dist/index.css';
import * as ElementPlusIconsVue from '@element-plus/icons-vue';

import App from './App.vue';
import router from './router';

const app = createApp(App);

// 注册所有 Element Plus 图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component);
}

// Pinia 状态管理
const pinia = createPinia();
app.use(pinia);

// Vue Router
app.use(router);

// Element Plus
app.use(ElementPlus);

// 挂载应用
app.mount('#app');
