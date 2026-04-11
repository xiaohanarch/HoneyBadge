import { ref, computed } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { authApi } from '@/api/http';
import { useAuthStore } from '@/stores/auth';
import type { User, MatrixLoginResponse } from '@/types';

export function useAuth() {
  const router = useRouter();
  const authStore = useAuthStore();
  const loading = ref(false);

  const isAuthenticated = computed(() => authStore.isAuthenticated);
  const currentUser = computed(() => authStore.user);

  async function login(username: string, password: string): Promise<boolean> {
    loading.value = true;
    try {
      const authUrl = import.meta.env.VITE_AUTH_URL || 'http://localhost:8091';
      const resp = await fetch(`${authUrl}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      if (!resp.ok) {
        throw new Error('Invalid credentials');
      }
      const data: MatrixLoginResponse = await resp.json();

      // Store tokens
      localStorage.setItem('token', data.roles_jwt);
      localStorage.setItem('matrix_token', data.matrix_access_token);
      localStorage.setItem('matrix_user_id', data.matrix_user_id);
      localStorage.setItem('matrix_homeserver', data.matrix_homeserver);

      // Update stores
      authStore.setAuth(data.roles_jwt, '', data.user);
      authStore.setMatrixAuth(
        data.matrix_access_token,
        data.matrix_homeserver,
        data.matrix_user_id,
        data.roles_jwt
      );

      ElMessage.success(`欢迎回来，${data.user.display_name}`);
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
      localStorage.removeItem('matrix_token');
      localStorage.removeItem('matrix_user_id');
      localStorage.removeItem('matrix_homeserver');

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
      localStorage.removeItem('matrix_token');
      localStorage.removeItem('matrix_user_id');
      localStorage.removeItem('matrix_homeserver');
      authStore.clearAuth();
      return null;
    }
  }

  function checkAuth(): boolean {
    const token = localStorage.getItem('token');
    const matrixToken = localStorage.getItem('matrix_token');
    const matrixUserId = localStorage.getItem('matrix_user_id');
    const matrixHomeserver = localStorage.getItem('matrix_homeserver');

    if (token && authStore.user) {
      authStore.setAuth(token, '', authStore.user);
      if (matrixToken && matrixUserId && matrixHomeserver) {
        authStore.setMatrixAuth(matrixToken, matrixHomeserver, matrixUserId, token);
      }
      return true;
    }

    return false;
  }

  async function checkGoogleSSOEnabled(): Promise<boolean> {
    try {
      const authUrl = import.meta.env.VITE_AUTH_URL || 'http://localhost:8091';
      const resp = await fetch(`${authUrl}/auth/google/config`);
      if (!resp.ok) return false;
      const data = await resp.json();
      return data.enabled === true;
    } catch {
      return false;
    }
  }

  async function handleGoogleCallback(): Promise<boolean> {
    // After Google redirects back, browser lands on frontend with tokens in URL fragment
    // Format: http://localhost:3000/login#matrix_access_token=...&roles_jwt=...
    const hash = window.location.hash;
    if (!hash || !hash.startsWith('#')) return false;

    try {
      const params = new URLSearchParams(hash.substring(1));
      const data = {
        matrix_access_token: params.get('matrix_access_token') || '',
        matrix_user_id: params.get('matrix_user_id') || '',
        matrix_homeserver: params.get('matrix_homeserver') || '',
        roles_jwt: params.get('roles_jwt') || '',
        user: {
          id: params.get('user.id') || '',
          username: params.get('user.username') || '',
          display_name: params.get('user.display_name') || '',
          roles: (params.get('user.roles') || '').split(',').filter(Boolean),
          org_id: parseInt(params.get('user.org_id') || '1', 10),
        },
      };

      // Validate response structure
      if (!data.roles_jwt || !data.matrix_access_token || !data.user.id) {
        throw new Error('Invalid response structure');
      }

      // Same processing as demo login
      localStorage.setItem('token', data.roles_jwt);
      localStorage.setItem('matrix_token', data.matrix_access_token);
      localStorage.setItem('matrix_user_id', data.matrix_user_id);
      localStorage.setItem('matrix_homeserver', data.matrix_homeserver);
      authStore.setAuth(data.roles_jwt, '', data.user);
      authStore.setMatrixAuth(data.matrix_access_token, data.matrix_homeserver, data.matrix_user_id, data.roles_jwt);
      ElMessage.success(`欢迎，${data.user.display_name}`);
      // Clean URL fragment
      window.history.replaceState({}, '', '/login');
      router.push('/chat');
      return true;
    } catch (error) {
      console.error('Google callback failed:', error);
      ElMessage.error('Google 登录失败');
      window.history.replaceState({}, '', '/login');
      return false;
    }
  }

  return {
    loading,
    isAuthenticated,
    currentUser,
    login,
    logout,
    fetchCurrentUser,
    checkAuth,
    checkGoogleSSOEnabled,
    handleGoogleCallback,
  };
}
