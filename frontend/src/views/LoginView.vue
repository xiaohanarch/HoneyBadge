<template>
  <div class="login-container">
    <div class="login-box">
      <div class="login-header">
        <div class="logo">
          <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M32 4L58 18V46L32 60L6 46V18L32 4Z" stroke="#409EFF" stroke-width="2" fill="none"/>
            <path d="M32 20L44 26V38L32 44L20 38V26L32 20Z" fill="#409EFF"/>
            <circle cx="32" cy="32" r="6" fill="white"/>
          </svg>
        </div>
        <h1 class="title">HoneyBadge</h1>
        <p class="subtitle">Enterprise Knowledge Graph Assistant</p>
      </div>

      <el-form
        ref="loginFormRef"
        :model="loginForm"
        :rules="loginRules"
        class="login-form"
        @submit.prevent="handleLogin"
      >
        <el-form-item prop="username">
          <el-input
            v-model="loginForm.username"
            placeholder="用户名"
            size="large"
            :prefix-icon="User"
            autocomplete="username"
          />
        </el-form-item>

        <el-form-item prop="password">
          <el-input
            v-model="loginForm.password"
            type="password"
            placeholder="密码"
            size="large"
            :prefix-icon="Lock"
            autocomplete="current-password"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            size="large"
            :loading="loading"
            class="login-button"
            @click="handleLogin"
          >
            登 录
          </el-button>
        </el-form-item>
      </el-form>

      <div class="login-divider">
        <span class="divider-text">或</span>
      </div>

      <el-button
        v-if="ssoEnabled"
        type="default"
        size="large"
        class="sso-button"
        :loading="ssoLoading"
        @click="handleSSOLogin"
      >
        登录 with Google
      </el-button>
      <el-button
        v-else
        type="default"
        size="large"
        class="sso-button"
        disabled
        title="Google SSO 未启用"
      >
        Google SSO (未配置)
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage, FormInstance, FormRules } from 'element-plus';
import { User, Lock } from '@element-plus/icons-vue';
import { useAuth } from '@/composables/useAuth';

const router = useRouter();
const { login, loading, checkGoogleSSOEnabled, handleGoogleCallback } = useAuth();

const ssoEnabled = ref(false);
const ssoLoading = ref(false);

onMounted(async () => {
  // Check if this is a Google callback
  const params = new URLSearchParams(window.location.search);
  if (params.has('code')) {
    const success = await handleGoogleCallback();
    if (success) return;
  }
  // Check if Google SSO is enabled
  ssoEnabled.value = await checkGoogleSSOEnabled();
});

function handleSSOLogin() {
  window.location.href = `${import.meta.env.VITE_AUTH_URL || 'http://localhost:8091'}/auth/google`;
}

const loginFormRef = ref<FormInstance>();
const loginForm = reactive({
  username: '',
  password: '',
});

const loginRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, max: 50, message: '用户名长度在 2 到 50 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 100, message: '密码长度至少 6 个字符', trigger: 'blur' },
  ],
};

async function handleLogin() {
  if (!loginFormRef.value) return;

  await loginFormRef.value.validate(async (valid) => {
    if (valid) {
      const success = await login(loginForm.username, loginForm.password);
      if (success) {
        router.push('/chat');
      }
    }
  });
}
</script>

<style scoped lang="scss">
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.login-box {
  width: 400px;
  padding: 40px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}

.login-header {
  text-align: center;
  margin-bottom: 32px;
}

.logo {
  margin-bottom: 16px;
}

.title {
  font-size: 28px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 8px 0;
}

.subtitle {
  font-size: 14px;
  color: #909399;
  margin: 0;
}

.login-form {
  margin-bottom: 16px;
}

.login-button {
  width: 100%;
}

.login-divider {
  display: flex;
  align-items: center;
  margin: 20px 0;

  &::before,
  &::after {
    content: '';
    flex: 1;
    height: 1px;
    background: #dcdfe6;
  }

  .divider-text {
    padding: 0 16px;
    color: #909399;
    font-size: 14px;
  }
}

.sso-button {
  width: 100%;
}
</style>
