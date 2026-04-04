import { ref, computed } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { authApi } from '@/api/http';
import { useAuthStore } from '@/stores/auth';
import type { User, LoginResponse } from '@/types';

export function useAuth() {
  const router = useRouter();
  const authStore = useAuthStore();
  const loading = ref(false);

  const isAuthenticated = computed(() => authStore.isAuthenticated);
  const currentUser = computed(() => authStore.user);

  async function login(username: string, password: string): Promise<boolean> {
    loading.value = true;

    try {
      const response = await authApi.login(username, password);
      const { token, refresh_token, user } = response.data;

      // 存储 token
      localStorage.setItem('token', token);
      localStorage.setItem('refresh_token', refresh_token);

      // 更新 store
      authStore.setAuth(token, refresh_token, user);

      ElMessage.success(`欢迎回来，${user.display_name}`);
      router.push('/chat');

      return true;
    } catch (error) {
      console.error('Login failed:', error);
      ElMessage.error('用户名或密码错误');
      return false;
    } finally {
      loading.value = false;
    }
  }

  async function logout() {
    try {
      await authApi.logout();
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      // 清除本地存储
      localStorage.removeItem('token');
      localStorage.removeItem('refresh_token');

      // 重置 store
      authStore.clearAuth();

      router.push('/login');
      ElMessage.success('已退出登录');
    }
  }

  async function fetchCurrentUser(): Promise<User | null> {
    const token = localStorage.getItem('token');
    if (!token) {
      return null;
    }

    try {
      const response = await authApi.getCurrentUser();
      const user = response.data as unknown as User;
      authStore.setUser(user);
      return user;
    } catch (error) {
      console.error('Failed to fetch current user:', error);
      // Token 可能过期，清除
      localStorage.removeItem('token');
      localStorage.removeItem('refresh_token');
      authStore.clearAuth();
      return null;
    }
  }

  function checkAuth(): boolean {
    const token = localStorage.getItem('token');
    const refreshToken = localStorage.getItem('refresh_token');

    if (token && refreshToken) {
      authStore.setAuth(token, refreshToken, authStore.user!);
      return true;
    }

    return false;
  }

  return {
    loading,
    isAuthenticated,
    currentUser,
    login,
    logout,
    fetchCurrentUser,
    checkAuth,
  };
}
