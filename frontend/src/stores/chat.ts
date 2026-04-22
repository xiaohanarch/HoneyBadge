import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import { generateTraceId as uuidv4 } from '@/api/matrix';
import type {
  ChatMessage,
  ChatSession,
  ProgressUpdate,
  QueryResponse,
} from '@/types';

interface ProgressState {
  step: string;
  stepNumber: number;
  totalSteps: number;
  detail?: string;
}

export const useChatStore = defineStore('chat', () => {
  const sessions = ref<ChatSession[]>([]);
  const currentSessionId = ref<string | null>(null);
  const messages = ref<ChatMessage[]>([]);
  const loading = ref(false);
  const streamingContent = ref('');
  const streamingPhase = ref<'thinking' | 'cypher' | 'executing' | 'summarizing'>('thinking');
  const progress = ref<ProgressState | null>(null);
  const error = ref<string | null>(null);

  const currentSession = computed(() =>
    sessions.value.find((s) => s.id === currentSessionId.value)
  );

  const currentMessages = computed(() =>
    messages.value.filter((m) => m.session_id === currentSessionId.value)
  );

  function setSessions(newSessions: ChatSession[]) {
    sessions.value = newSessions;
  }

  function addSession(session: ChatSession) {
    sessions.value.unshift(session);
  }

  function removeSession(sessionId: string) {
    const index = sessions.value.findIndex((s) => s.id === sessionId);
    if (index > -1) {
      sessions.value.splice(index, 1);
    }
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = sessions.value[0]?.id || null;
    }
  }

  function setCurrentSession(sessionId: string) {
    currentSessionId.value = sessionId;
  }

  function setMessages(sessionId: string, newMessages: ChatMessage[]) {
    // 按会话ID存储消息
    messages.value = messages.value.filter((m) => m.session_id !== sessionId);
    messages.value.push(...newMessages.map((m) => ({ ...m, session_id: sessionId })));
  }

  function addMessage(message: ChatMessage) {
    const sessionId = currentSessionId.value;
    if (sessionId) {
      messages.value.push({ ...message, session_id: sessionId });
    }
  }

  function prepareAssistantMessage() {
    const sessionId = currentSessionId.value;
    if (!sessionId) return;

    const assistantMessage: ChatMessage = {
      id: uuidv4(),
      role: 'assistant',
      content: '',
      message_type: 'text',
      created_at: new Date().toISOString(),
    };
    messages.value.push({ ...assistantMessage, session_id: sessionId });
    streamingContent.value = '';
    progress.value = null;
    error.value = null;
  }

  function appendStreamContent(content: string) {
    streamingContent.value += content;

    // 更新最后一条助手消息
    const sessionId = currentSessionId.value;
    if (sessionId) {
      const lastAssistantMessage = [...messages.value]
        .reverse()
        .find((m) => m.session_id === sessionId && m.role === 'assistant');

      if (lastAssistantMessage) {
        lastAssistantMessage.content = streamingContent.value;
      }
    }
  }

  function setStreamPhase(phase: 'thinking' | 'cypher' | 'executing' | 'summarizing') {
    streamingPhase.value = phase;
  }

  function updateProgress(progressUpdate: ProgressState) {
    progress.value = progressUpdate;
  }

  function finalizeAssistantMessage(data: {
    summary: string;
    rawData: Record<string, unknown>[];
    columns: string[];
    cypher: string;
    traceId: string;
    executionTimeMs: number;
    rowCount: number;
  }) {
    const sessionId = currentSessionId.value;
    if (!sessionId) return;

    const lastAssistantMessage = [...messages.value]
      .reverse()
      .find((m) => m.session_id === sessionId && m.role === 'assistant');

    if (lastAssistantMessage) {
      lastAssistantMessage.content = data.summary;
      lastAssistantMessage.message_type = 'query_result';
      lastAssistantMessage.metadata = {
        cypher: data.cypher,
        raw_data: data.rawData,
        columns: data.columns,
        trace_id: data.traceId,
        execution_time_ms: data.executionTimeMs,
      };
    }

    streamingContent.value = '';
    progress.value = null;
  }

  function setError(errorMessage: string) {
    error.value = errorMessage;

    const sessionId = currentSessionId.value;
    if (sessionId) {
      const lastAssistantMessage = [...messages.value]
        .reverse()
        .find((m) => m.session_id === sessionId && m.role === 'assistant');

      if (lastAssistantMessage) {
        lastAssistantMessage.content = errorMessage;
        lastAssistantMessage.message_type = 'error';
      }
    }
  }

  function setLoading(isLoading: boolean) {
    loading.value = isLoading;
  }

  function clearCurrentMessages() {
    const sessionId = currentSessionId.value;
    if (sessionId) {
      messages.value = messages.value.filter((m) => m.session_id !== sessionId);
    }
  }

  return {
    sessions,
    currentSessionId,
    messages,
    loading,
    streamingContent,
    streamingPhase,
    progress,
    error,
    currentSession,
    currentMessages,
    setSessions,
    addSession,
    removeSession,
    setCurrentSession,
    setMessages,
    addMessage,
    prepareAssistantMessage,
    appendStreamContent,
    setStreamPhase,
    updateProgress,
    finalizeAssistantMessage,
    setError,
    setLoading,
    clearCurrentMessages,
  };
});
