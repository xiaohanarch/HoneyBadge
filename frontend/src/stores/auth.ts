import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { User, AuthState } from '@/types';

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(null);
  const refreshToken = ref<string | null>(null);
  const user = ref<User | null>(null);

  // Matrix auth fields
  const matrixToken = ref<string | null>(null);
  const matrixHomeserver = ref<string | null>(null);
  const matrixUserId = ref<string | null>(null);
  const matrixDmRoomId = ref<string | null>(null);
  const rolesJwt = ref<string | null>(null);

  const isAuthenticated = computed(() => !!token.value && !!user.value);

  function setAuth(newToken: string, newRefreshToken: string, newUser: User) {
    token.value = newToken;
    refreshToken.value = newRefreshToken;
    user.value = newUser;
  }

  function setMatrixAuth(mToken: string, homeserver: string, userId: string, jwt: string, dmRoomId?: string) {
    matrixToken.value = mToken;
    matrixHomeserver.value = homeserver;
    matrixUserId.value = userId;
    rolesJwt.value = jwt;
    if (dmRoomId) {
      matrixDmRoomId.value = dmRoomId;
    }
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
    matrixToken.value = null;
    matrixHomeserver.value = null;
    matrixUserId.value = null;
    matrixDmRoomId.value = null;
    rolesJwt.value = null;
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
    matrixToken,
    matrixHomeserver,
    matrixUserId,
    matrixDmRoomId,
    rolesJwt,
    isAuthenticated,
    setAuth,
    setMatrixAuth,
    setToken,
    setUser,
    clearAuth,
    getAuthState,
  };
});
