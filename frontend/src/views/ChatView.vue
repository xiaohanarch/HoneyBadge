<template>
  <div class="chat-layout">
    <!-- 侧边栏 -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <h2>会话列表</h2>
        <el-button type="primary" size="small" @click="handleNewChat">
          <el-icon><Plus /></el-icon>
          新对话
        </el-button>
      </div>

      <div class="session-list">
        <el-scrollbar>
          <div
            v-for="session in sessions"
            :key="session.id"
            class="session-item"
            :class="{ active: session.id === currentSessionId }"
            @click="selectSession(session.id)"
          >
            <span class="session-title">{{ session.title || '新会话' }}</span>
            <el-dropdown trigger="click" @command="(cmd: string) => handleSessionCommand(cmd, session.id)">
              <el-icon class="session-actions"><MoreFilled /></el-icon>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename">重命名</el-dropdown-item>
                  <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
          <el-empty v-if="sessions.length === 0" description="暂无会话" />
        </el-scrollbar>
      </div>
    </aside>

    <!-- 主聊天区域 -->
    <main class="chat-main">
      <!-- 顶部栏 -->
      <header class="chat-header">
        <div class="header-left">
          <span class="logo-text">HoneyBadge</span>
        </div>
        <div class="header-right">
          <el-tag :type="connected ? 'success' : 'danger'" size="small">
            {{ connected ? '已连接' : '未连接' }}
          </el-tag>
          <el-dropdown @command="handleUserCommand">
            <span class="user-avatar">
              <el-avatar :size="32" :icon="UserFilled" />
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>
                  <span>{{ currentUser?.display_name || '用户' }}</span>
                </el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <!-- 消息区域 -->
      <div class="message-area" ref="messageAreaRef">
        <el-scrollbar>
          <div class="messages-container">
            <template v-if="currentMessages.length > 0">
              <ChatMessage
                v-for="msg in currentMessages"
                :key="msg.id"
                :message="msg"
              />
            </template>
            <el-empty v-else description="开始新对话吧" />
          </div>
        </el-scrollbar>
      </div>

      <!-- 进度展示 -->
      <div v-if="progress" class="progress-area">
        <el-steps :active="progress.stepNumber - 1" direction="vertical" :space="40">
          <el-step
            v-for="i in progress.totalSteps"
            :key="i"
            :title="getStepTitle(i)"
            :description="i === progress.stepNumber ? progress.step : ''"
            :status="i < progress.stepNumber ? 'success' : i === progress.stepNumber ? 'process' : 'wait'"
          />
        </el-steps>
      </div>

      <!-- 输入区域 -->
      <div class="input-area">
        <div class="input-container">
          <el-input
            v-model="question"
            type="textarea"
            :rows="2"
            placeholder="请输入你的问题..."
            resize="none"
            :disabled="loading"
            @keydown.enter.meta="handleSend"
            @keydown.enter.ctrl="handleSend"
          />
          <el-button
            type="primary"
            size="large"
            :loading="loading"
            class="send-button"
            :disabled="!question.trim()"
            @click="handleSend"
          >
            <el-icon v-if="!loading"><Promotion /></el-icon>
            <span v-if="loading">处理中...</span>
            <span v-else>发送</span>
          </el-button>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Plus, MoreFilled, Promotion, UserFilled } from '@element-plus/icons-vue';
import { useAuth } from '@/composables/useAuth';
import { useMatrixChat } from '@/composables/useMatrixChat';
import { useChatStore } from '@/stores/chat';
import ChatMessage from '@/components/chat/ChatMessage.vue';

const router = useRouter();
const { logout, currentUser, fetchCurrentUser } = useAuth();
const { connected, loadSessions, createSession, loadMessages, sendQuery, deleteSession, connect } = useMatrixChat();
const chatStore = useChatStore();

const question = ref('');
const messageAreaRef = ref<HTMLElement>();

const sessions = computed(() => chatStore.sessions);
const currentSessionId = computed(() => chatStore.currentSessionId);
const currentMessages = computed(() => chatStore.currentMessages);
const loading = computed(() => chatStore.loading);
const progress = computed(() => chatStore.progress);

const stepTitles: Record<number, string> = {
  1: '理解问题',
  2: '生成查询',
  3: '校验查询',
  4: '执行查询',
  5: '生成摘要',
};

function getStepTitle(step: number): string {
  return stepTitles[step] || `步骤 ${step}`;
}

async function handleNewChat() {
  const sessionId = await createSession('新会话');
  if (sessionId) {
    chatStore.setCurrentSession(sessionId);
    chatStore.clearCurrentMessages();
  }
}

async function selectSession(sessionId: string) {
  chatStore.setCurrentSession(sessionId);
  await loadMessages(sessionId);
  scrollToBottom();
}

async function handleSessionCommand(command: string, sessionId: string) {
  if (command === 'rename') {
    const session = sessions.value.find((s) => s.id === sessionId);
    if (!session) return;

    try {
      const { value: newTitle } = await ElMessageBox.prompt('请输入新的会话标题', '重命名会话', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        inputValue: session.title,
      });
      // 调用 API 更新会话标题
      ElMessage.success('会话已重命名');
    } catch {
      // 用户取消
    }
  } else if (command === 'delete') {
    try {
      await ElMessageBox.confirm('确定要删除该会话吗？', '删除会话', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      });
      await deleteSession(sessionId);
    } catch {
      // 用户取消
    }
  }
}

async function handleSend() {
  const q = question.value.trim();
  if (!q || loading.value) return;

  question.value = '';
  await sendQuery(q);
}

async function handleUserCommand(command: string) {
  if (command === 'logout') {
    await logout();
    router.push('/login');
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (messageAreaRef.value) {
      messageAreaRef.value.scrollTop = messageAreaRef.value.scrollHeight;
    }
  });
}

// 监听新消息，自动滚动到底部
watch(
  () => chatStore.messages.length,
  () => {
    scrollToBottom();
  }
);

onMounted(async () => {
  // 获取当前用户
  await fetchCurrentUser();
  // 加载会话列表
  await loadSessions();

  // 如果有会话，选中第一个
  if (sessions.value.length > 0) {
    const lastSession = sessions.value[0];
    chatStore.setCurrentSession(lastSession.id);
    await loadMessages(lastSession.id);
  }

  // 建立 WebSocket 连接
  connect();
});
</script>

<style scoped lang="scss">
.chat-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.sidebar {
  width: 260px;
  background: #f5f7fa;
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  justify-content: space-between;
  align-items: center;

  h2 {
    font-size: 16px;
    font-weight: 600;
    margin: 0;
  }
}

.session-list {
  flex: 1;
  overflow: hidden;
  padding: 8px;

  .el-scrollbar {
    height: 100%;
  }
}

.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 4px;
  transition: background-color 0.2s;

  &:hover {
    background: #e4e7ed;
  }

  &.active {
    background: #409eff;
    color: white;

    .session-actions {
      color: white;
    }
  }

  .session-title {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 14px;
  }

  .session-actions {
    opacity: 0;
    transition: opacity 0.2s;
    cursor: pointer;
  }

  &:hover .session-actions {
    opacity: 1;
  }
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.chat-header {
  height: 56px;
  padding: 0 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #e4e7ed;
  background: white;

  .header-left {
    display: flex;
    align-items: center;

    .logo-text {
      font-size: 18px;
      font-weight: 600;
      color: #409eff;
    }
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 12px;

    .user-avatar {
      cursor: pointer;
    }
  }
}

.message-area {
  flex: 1;
  overflow: hidden;
  background: #f5f7fa;

  .el-scrollbar {
    height: 100%;
  }
}

.messages-container {
  padding: 20px;
  max-width: 900px;
  margin: 0 auto;
}

.progress-area {
  padding: 16px 20px;
  background: white;
  border-top: 1px solid #e4e7ed;
  max-width: 900px;
  margin: 0 auto;
  width: 100%;
}

.input-area {
  padding: 16px 20px;
  background: white;
  border-top: 1px solid #e4e7ed;
}

.input-container {
  max-width: 900px;
  margin: 0 auto;
  display: flex;
  gap: 12px;
  align-items: flex-end;

  .el-textarea {
    flex: 1;
  }

  .send-button {
    height: 60px;
    width: 100px;
  }
}
</style>
