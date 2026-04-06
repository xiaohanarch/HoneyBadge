import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { User, AuthState } from '@/types';

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(null);
  const refreshToken = ref<string | null>(null);
  const user = ref<User | null>(null);

  const isAuthenticated = computed(() => !!token.value && !!user.value);

  function setAuth(newToken: string, newRefreshToken: string, newUser: User) {
    token.value = newToken;
    refreshToken.value = newRefreshToken;
    user.value = newUser;
  }

  function setToken(newToken: string) {
    token.value = newToken;
  }

  function setUser(newUser: User) {
    user.value = newUser;
  }

  function clearAuth() {
    token.value = null;
    refreshToken.value = null;
    user.value = null;
  }

  function getAuthState(): AuthState {
    return {
      token: token.value,
      refreshToken: refreshToken.value,
      user: user.value,
      isAuthenticated: isAuthenticated.value,
    };
  }

  return {
    token,
    refreshToken,
    user,
    isAuthenticated,
    setAuth,
    setToken,
    setUser,
    clearAuth,
    getAuthState,
  };
});
