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
    // After Google redirects back with ?code=xxx&state=yyy,
    // the browser lands on LoginView. We detect this and process tokens.
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const state = params.get('state');
    if (!code || !state) return false;

    try {
      const authUrl = import.meta.env.VITE_AUTH_URL || 'http://localhost:8091';
      const resp = await fetch(`${authUrl}/auth/google/callback?code=${code}&state=${state}`);
      if (!resp.ok) {
        ElMessage.error('Google 登录失败');
        return false;
      }
      const data = await resp.json();
      // Same processing as demo login
      localStorage.setItem('token', data.roles_jwt);
      localStorage.setItem('matrix_token', data.matrix_access_token);
      localStorage.setItem('matrix_user_id', data.matrix_user_id);
      localStorage.setItem('matrix_homeserver', data.matrix_homeserver);
      authStore.setAuth(data.roles_jwt, '', data.user);
      authStore.setMatrixAuth(data.matrix_access_token, data.matrix_homeserver, data.matrix_user_id, data.roles_jwt);
      ElMessage.success(`欢迎，${data.user.display_name}`);
      // Clean URL params
      window.history.replaceState({}, '', '/login');
      router.push('/chat');
      return true;
    } catch (error) {
      console.error('Google callback failed:', error);
      ElMessage.error('Google 登录失败');
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
