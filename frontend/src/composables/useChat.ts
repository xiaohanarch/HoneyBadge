import { ref, computed } from 'vue';
import { ElMessage } from 'element-plus';
import { useChatStore } from '@/stores/chat';
import { useWebSocket } from './useWebSocket';
import { sessionApi } from '@/api/http';
import { generateTraceId as uuidv4 } from '@/api/matrix';
import type {
  ChatMessage,
  ChatSession,
  WSMessage,
  QueryRequest,
  StreamChunk,
  ProgressUpdate,
  QueryResponse,
  ErrorResponse,
} from '@/types';

export function useChat() {
  const chatStore = useChatStore();
  const wsUrl = ref(`${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`);
  const loading = ref(false);

  const { connected, connect, disconnect, send, reconnectAttempts } = useWebSocket({
    url: wsUrl.value,
    token: localStorage.getItem('token') || '',
    onMessage: handleMessage,
    onConnect: () => {
      console.log('WebSocket connected');
    },
    onDisconnect: () => {
      console.log('WebSocket disconnected');
    },
    onError: (error) => {
      console.error('WebSocket error:', error);
      ElMessage.error('WebSocket 连接错误');
    },
  });

  function handleMessage(msg: WSMessage) {
    switch (msg.type) {
      case 'stream':
        handleStreamChunk(msg as unknown as StreamChunk);
        break;
      case 'progress':
        handleProgressUpdate(msg as unknown as ProgressUpdate);
        break;
      case 'response':
        handleQueryResponse(msg as unknown as QueryResponse);
        break;
      case 'error':
        handleError(msg as unknown as ErrorResponse);
        break;
      case 'heartbeat':
        // 心跳响应，不需要处理
        break;
      default:
        console.warn('Unknown message type:', msg.type);
    }
  }

  function handleStreamChunk(chunk: StreamChunk) {
    chatStore.appendStreamContent(chunk.payload.content);
    chatStore.setStreamPhase(chunk.payload.phase);
  }

  function handleProgressUpdate(progress: ProgressUpdate) {
    chatStore.updateProgress({
      step: progress.payload.step,
      stepNumber: progress.payload.step_number,
      totalSteps: progress.payload.total_steps,
      detail: progress.payload.detail,
    });
  }

  function handleQueryResponse(response: QueryResponse) {
    chatStore.finalizeAssistantMessage({
      summary: response.payload.summary,
      rawData: response.payload.raw_data,
      columns: response.payload.columns,
      cypher: response.payload.cypher,
      traceId: response.payload.trace_id,
      executionTimeMs: response.payload.execution_time_ms,
      rowCount: response.payload.row_count,
    });
    chatStore.setLoading(false);
    ElMessage.success(`查询完成，返回 ${response.payload.row_count} 条记录`);
  }

  function handleError(error: ErrorResponse) {
    chatStore.setError(error.payload.message);
    chatStore.setLoading(false);
    ElMessage.error(`查询错误: ${error.payload.message}`);
  }

  async function sendQuery(question: string) {
    const sessionId = chatStore.currentSessionId;
    if (!sessionId) {
      ElMessage.error('请先创建会话');
      return;
    }

    // 添加用户消息
    const userMessage: ChatMessage = {
      id: uuidv4(),
      role: 'user',
      content: question,
      message_type: 'text',
      created_at: new Date().toISOString(),
    };
    chatStore.addMessage(userMessage);

    // 准备空白的助手消息用于流式更新
    chatStore.prepareAssistantMessage();

    // 发送查询请求
    const queryRequest: QueryRequest = {
      type: 'query',
      payload: {
        question,
        session_id: sessionId,
      },
    };

    chatStore.setLoading(true);

    if (!connected.value) {
      connect();
    }

    send({
      ...queryRequest,
      timestamp: Date.now(),
    });
  }

  async function loadSessions() {
    loading.value = true;
    try {
      const response = await sessionApi.getSessions();
      const sessions = response.data as unknown as ChatSession[];
      chatStore.setSessions(sessions);
    } catch (error) {
      console.error('Failed to load sessions:', error);
      ElMessage.error('加载会话列表失败');
    } finally {
      loading.value = false;
    }
  }

  async function createSession(title?: string): Promise<string | null> {
    try {
      const response = await sessionApi.createSession(title);
      const session = response.data as unknown as ChatSession;
      chatStore.addSession(session);
      chatStore.setCurrentSession(session.id);
      return session.id;
    } catch (error) {
      console.error('Failed to create session:', error);
      ElMessage.error('创建会话失败');
      return null;
    }
  }

  async function loadMessages(sessionId: string) {
    loading.value = true;
    try {
      const response = await sessionApi.getMessages(sessionId);
      const messages = response.data as unknown as ChatMessage[];
      chatStore.setMessages(sessionId, messages);
    } catch (error) {
      console.error('Failed to load messages:', error);
      ElMessage.error('加载消息历史失败');
    } finally {
      loading.value = false;
    }
  }

  async function deleteSession(sessionId: string) {
    try {
      await sessionApi.deleteSession(sessionId);
      chatStore.removeSession(sessionId);
      ElMessage.success('会话已删除');
    } catch (error) {
      console.error('Failed to delete session:', error);
      ElMessage.error('删除会话失败');
    }
  }

  return {
    connected,
    reconnectAttempts,
    loading,
    sendQuery,
    loadSessions,
    createSession,
    loadMessages,
    deleteSession,
    connect,
    disconnect,
  };
}
