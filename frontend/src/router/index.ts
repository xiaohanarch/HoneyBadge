import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router';
import { useAuthStore } from '@/stores/auth';

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/chat',
    name: 'Chat',
    component: () => import('@/views/ChatView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/',
    redirect: '/chat',
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/chat',
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

// 路由守卫
router.beforeEach((to, from, next) => {
  const authStore = useAuthStore();
  const requiresAuth = to.meta.requiresAuth !== false;

  if (requiresAuth && !authStore.isAuthenticated) {
    // 检查 localStorage 中是否有 token
    const token = localStorage.getItem('token');
    if (token) {
      // token 存在，尝试恢复会话
      authStore.setToken(token);
      next();
    } else {
      next('/login');
    }
  } else if (to.path === '/login' && authStore.isAuthenticated) {
    // 已登录用户访问登录页，跳转到聊天
    next('/chat');
  } else {
    next();
  }
});

export default router;
