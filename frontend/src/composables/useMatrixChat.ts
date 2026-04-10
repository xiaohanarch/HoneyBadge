import { ref, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useChatStore } from '@/stores/chat'
import { useAuthStore } from '@/stores/auth'
import { sessionApi } from '@/api/http'
import {
  createMatrixClient,
  findOrCreateManagerDmRoom,
  sendQuery,
  type MatrixClient,
} from '@/api/matrix'
import type { ChatMessage, ChatSession } from '@/types'

const MANAGER_USER_ID =
  import.meta.env.VITE_MANAGER_USER_ID || '@manager:matrix-local.hiclaw.io'

export function useMatrixChat() {
  const chatStore = useChatStore()
  const authStore = useAuthStore()
  const loading = ref(false)
  const connected = ref(false)
  const reconnectAttempts = ref(0)

  // eslint-disable-next-line prefer-const
  let matrixClient: MatrixClient | null = null
  let dmRoomId: string | null = null

  async function initMatrix(): Promise<boolean> {
    const token = authStore.matrixToken
    const homeserver = authStore.matrixHomeserver
    const userId = authStore.matrixUserId

    if (!token || !homeserver || !userId) {
      console.warn('Matrix auth not available')
      return false
    }

    try {
      matrixClient = createMatrixClient(homeserver, token, userId)
      dmRoomId = await findOrCreateManagerDmRoom(matrixClient, MANAGER_USER_ID)

      // Listen for incoming events
      // @ts-ignore — Room.timeline event string is valid but sdk types are strict
      matrixClient.on('Room.timeline', handleRoomEvent)

      connected.value = true
      return true
    } catch (error) {
      console.error('Matrix init failed:', error)
      ElMessage.error('Matrix 连接失败')
      return false
    }
  }

  // @ts-ignore — event/room are typed as any here for flexibility
  function handleRoomEvent(event: any, room: any) {
    if (room?.roomId !== dmRoomId) return
    if (event.getType() !== 'm.room.message') return
    if (event.getSender() === authStore.matrixUserId) return // ignore own messages

    const content = event.getContent()
    const xhb = content['x-honeybadge']

    if (!xhb) {
      // Plain text — progress update from Worker
      const body = content.body || ''
      if (body && chatStore.loading) {
        chatStore.appendStreamContent(body + '\n')
      }
      return
    }

    if (xhb.contract === '002') {
      // Result
      const payload = xhb.payload || {}
      chatStore.finalizeAssistantMessage({
        summary: payload.summary || content.body || '',
        rawData: payload.raw_data || [],
        columns: payload.columns || [],
        cypher: payload.cypher || '',
        traceId: xhb.trace_id || '',
        executionTimeMs: payload.execution_time_ms || 0,
        rowCount: payload.row_count || 0,
      })
      chatStore.setLoading(false)
      ElMessage.success(`查询完成，返回 ${payload.row_count || 0} 条记录`)
    } else if (xhb.contract === '003') {
      // Error
      chatStore.setError(xhb.payload?.message || '查询失败')
      chatStore.setLoading(false)
      ElMessage.error(`查询错误: ${xhb.payload?.message || '未知错误'}`)
    }
  }

  async function sendQueryMessage(question: string) {
    if (!matrixClient || !dmRoomId) {
      const ok = await initMatrix()
      if (!ok) {
        ElMessage.error('Matrix 连接未就绪')
        return
      }
    }

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: question,
      message_type: 'text',
      created_at: new Date().toISOString(),
    }
    chatStore.addMessage(userMessage)
    chatStore.prepareAssistantMessage()
    chatStore.setLoading(true)

    try {
      await sendQuery(matrixClient!, dmRoomId!, question, authStore.rolesJwt || '')
    } catch (error) {
      console.error('Send query failed:', error)
      chatStore.setError('发送消息失败')
      chatStore.setLoading(false)
      ElMessage.error('发送消息失败')
    }
  }

  async function loadSessions() {
    loading.value = true
    try {
      const response = await sessionApi.getSessions()
      const sessions = response.data as unknown as ChatSession[]
      chatStore.setSessions(sessions)
    } catch (error) {
      console.error('Failed to load sessions:', error)
      ElMessage.error('加载会话列表失败')
    } finally {
      loading.value = false
    }
  }

  async function createSession(title?: string): Promise<string | null> {
    try {
      const response = await sessionApi.createSession(title)
      const session = response.data as unknown as ChatSession
      chatStore.addSession(session)
      chatStore.setCurrentSession(session.id)
      return session.id
    } catch (error) {
      console.error('Failed to create session:', error)
      ElMessage.error('创建会话失败')
      return null
    }
  }

  async function loadMessages(sessionId: string) {
    loading.value = true
    try {
      const response = await sessionApi.getMessages(sessionId)
      const messages = response.data as unknown as ChatMessage[]
      chatStore.setMessages(sessionId, messages)
    } catch (error) {
      console.error('Failed to load messages:', error)
      ElMessage.error('加载消息历史失败')
    } finally {
      loading.value = false
    }
  }

  async function deleteSession(sessionId: string) {
    try {
      await sessionApi.deleteSession(sessionId)
      chatStore.removeSession(sessionId)
      ElMessage.success('会话已删除')
    } catch (error) {
      console.error('Failed to delete session:', error)
      ElMessage.error('删除会话失败')
    }
  }

  function connect() {
    initMatrix()
  }

  function disconnect() {
    if (matrixClient) {
      matrixClient.stopClient()
      matrixClient = null
      dmRoomId = null
      connected.value = false
    }
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    connected,
    reconnectAttempts,
    loading,
    sendQuery: sendQueryMessage,
    loadSessions,
    createSession,
    loadMessages,
    deleteSession,
    connect,
    disconnect,
  }
}
