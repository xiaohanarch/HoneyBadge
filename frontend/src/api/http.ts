import axios, { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from 'axios';
import { ElMessage } from 'element-plus';
import router from '@/router';
import type { LoginResponse } from '@/types';

const http: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求拦截器 - 添加认证 token
http.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('token');
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error: AxiosError) => {
    return Promise.reject(error);
  }
);

// 响应拦截器 - 处理错误和 token 刷新
http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    // 处理 401 未授权
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      const refreshToken = localStorage.getItem('refresh_token');
      if (refreshToken) {
        try {
          const response = await axios.post<LoginResponse>('/api/auth/refresh', {
            refresh_token: refreshToken,
          });
          const { token, refresh_token, user } = response.data;
          localStorage.setItem('token', token);
          localStorage.setItem('refresh_token', refresh_token);

          if (originalRequest.headers) {
            originalRequest.headers.Authorization = `Bearer ${token}`;
          }
          return http(originalRequest);
        } catch (refreshError) {
          // 刷新 token 失败，清除存储并跳转登录
          localStorage.removeItem('token');
          localStorage.removeItem('refresh_token');
          router.push('/login');
          ElMessage.error('登录已过期，请重新登录');
          return Promise.reject(refreshError);
        }
      } else {
        router.push('/login');
      }
    }

    // 处理其他错误
    if (error.response?.status === 403) {
      ElMessage.error('没有权限访问该资源');
    } else if (error.response?.status === 500) {
      ElMessage.error('服务器内部错误');
    } else if (!error.response) {
      ElMessage.error('网络连接失败，请检查网络');
    }

    return Promise.reject(error);
  }
);

export default http;

// 认证 API
export const authApi = {
  login: (username: string, password: string) =>
    http.post<LoginResponse>('/auth/login', { username, password }),

  logout: () => http.post('/auth/logout'),

  getCurrentUser: () => http.get('/auth/me'),

  refreshToken: (refreshToken: string) =>
    http.post<LoginResponse>('/auth/refresh', { refresh_token: refreshToken }),
};

// 会话 API
export const sessionApi = {
  getSessions: () => http.get('/sessions'),

  createSession: (title?: string) =>
    http.post('/sessions', { title }),

  getSession: (id: string) => http.get(`/sessions/${id}`),

  updateSession: (id: string, title: string) =>
    http.put(`/sessions/${id}`, { title }),

  deleteSession: (id: string) => http.delete(`/sessions/${id}`),

  getMessages: (id: string) => http.get(`/sessions/${id}/messages`),
};

// 系统 API
export const systemApi = {
  health: () => http.get('/health'),

  version: () => http.get('/version'),
};

// 审计 API
export const auditApi = {
  getAuditTrail: (traceId: string) => http.get(`/api/audit/${traceId}`),
};
