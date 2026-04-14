import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { authApi } from '@/api/http';

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
    path: '/audit',
    name: 'Audit',
    component: () => import('@/views/AuditView.vue'),
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
router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore();
  const requiresAuth = to.meta.requiresAuth !== false;

  if (requiresAuth && !authStore.isAuthenticated) {
    // 检查 localStorage 中是否有 token
    const token = localStorage.getItem('token');
    const refreshToken = localStorage.getItem('refresh_token');

    if (token) {
      // token 存在，恢复 auth state
      authStore.setToken(token);

      // 获取用户信息来完成 auth 恢复
      try {
        const response = await authApi.getCurrentUser();
        const user = response.data as any;
        authStore.setAuth(token, refreshToken || '', user);

        // 恢复 Matrix auth state（登录时存储在 localStorage）
        const matrixToken = localStorage.getItem('matrix_token');
        const matrixHomeserver = localStorage.getItem('matrix_homeserver');
        const matrixUserId = localStorage.getItem('matrix_user_id');
        if (matrixToken && matrixHomeserver && matrixUserId) {
          authStore.setMatrixAuth(matrixToken, matrixHomeserver, matrixUserId, token);
        }

        next();
      } catch {
        // token 无效，清除并跳转登录
        localStorage.removeItem('token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('matrix_token');
        localStorage.removeItem('matrix_user_id');
        localStorage.removeItem('matrix_homeserver');
        authStore.clearAuth();
        next('/login');
      }
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
