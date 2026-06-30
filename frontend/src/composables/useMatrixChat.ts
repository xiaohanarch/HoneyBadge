import { ref, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useChatStore } from '@/stores/chat'
import { useAuthStore } from '@/stores/auth'
import { sessionApi } from '@/api/http'
import {
  createMatrixClient,
  findOrCreateManagerDmRoom,
  sendQuery,
  generateTraceId as uuidv4,
  type MatrixClient,
} from '@/api/matrix'
import type { ChatMessage, ChatSession } from '@/types'

const MANAGER_USER_ID =
  import.meta.env.VITE_MANAGER_USER_ID || '@manager:matrix-local.hiclaw.io'

// Converts a Matrix room message event to a ChatMessage for history restore.
// Returns null for non-message events, worker progress updates, and empty bodies.
// Unlike handleRoomEvent, this does NOT filter by sender or queryStartTime —
// history loading wants all messages including the user's own.
function matrixEventToChatMessage(event: any): ChatMessage | null {
  if (event.getType() !== 'm.room.message') return null

  const content = event.getContent()
  const xhb = content['x-honeybadge']
  const sender = event.getSender()
  const ts: number = (event.getServerTs?.() as number) || Date.now()
  const created_at = new Date(ts).toISOString()
  const id = event.getId() || uuidv4()

  // User query (contract 001) — sent by the current user
  if (xhb?.contract === '001') {
    return {
      id,
      role: 'user',
      content: xhb.payload?.question || content.body || '',
      message_type: 'text',
      created_at,
    }
  }

  // Structured result (contract 002) — sent by Worker via Manager
  if (xhb?.contract === '002') {
    const payload = xhb.payload || {}
    return {
      id,
      role: 'assistant',
      content: payload.summary || content.body || '',
      message_type: 'query_result',
      created_at,
      metadata: {
        trace_id: xhb.trace_id || '',
        cypher: payload.cypher || '',
        raw_data: payload.raw_data || [],
        columns: payload.columns || [],
        execution_time_ms: payload.execution_time_ms || 0,
      },
    }
  }

  // Error (contract 003)
  if (xhb?.contract === '003') {
    return {
      id,
      role: 'assistant',
      content: xhb.payload?.message || '查询失败',
      message_type: 'error',
      created_at,
    }
  }

  // Plain text from Manager (no xhb) — text reply
  if (sender === MANAGER_USER_ID) {
    const body = content.body || ''
    if (!body) return null
    return {
      id,
      role: 'assistant',
      content: body,
      message_type: 'text',
      created_at,
    }
  }

  // Plain text from Worker (no xhb, not Manager) — transient progress update
  return null
}

export function useMatrixChat() {
  const chatStore = useChatStore()
  const authStore = useAuthStore()
  const loading = ref(false)
  const connected = ref(false)
  const reconnectAttempts = ref(0)

  // eslint-disable-next-line prefer-const
  let matrixClient: MatrixClient | null = null
  let dmRoomId: string | null = null
  let initPromise: Promise<boolean> | null = null
  // Timestamp (ms) of the most recent query send. Used to filter out stale DM room events
  // from previous conversations that Matrix may replay during sync.
  let queryStartTime: number = 0

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

      // Seed the stale-event cutoff to "client init time minus a small buffer".
      // Any DM-room event older than this came from a prior session/test run and
      // must be ignored, otherwise initial sync replays them as if they were new
      // assistant responses (corrupting the chat store and breaking E2E assertions).
      // sendQueryMessage() advances this on every send so older events stay filtered.
      queryStartTime = Date.now() - 5000

      // Use the room ID provisioned server-side during login if available,
      // otherwise fall back to the client-side discovery (first login, no cache).
      const preProvisionedRoomId = authStore.matrixDmRoomId
      if (preProvisionedRoomId) {
        // Start the client for sync/event listening, then use the known room.
        await matrixClient.startClient({ initialSyncLimit: 10 })
        dmRoomId = preProvisionedRoomId
      } else {
        dmRoomId = await findOrCreateManagerDmRoom(matrixClient, MANAGER_USER_ID)
      }

      // Listen for incoming events
      // @ts-ignore — Room.timeline event string is valid but sdk types are strict
      matrixClient.on('Room.timeline', handleRoomEvent)

      connected.value = true
      return true
    } catch (error: any) {
      console.error('Matrix init failed:', error)
      const statusCode = error?.httpStatus || error?.statusCode
      const errMsg = error?.data?.error || error?.message || '未知错误'
      if (statusCode === 401) {
        ElMessage.error(`Matrix 认证失败: ${errMsg}，请重新登录`)
      } else {
        ElMessage.error(`Matrix 连接失败: ${errMsg}`)
      }
      // Clean up failed client
      if (matrixClient) {
        try { matrixClient.stopClient() } catch {}
        matrixClient = null
      }
      return false
    }
  }

  async function ensureInitialized(): Promise<boolean> {
    if (matrixClient && dmRoomId) return true
    if (initPromise) return initPromise
    initPromise = initMatrix().finally(() => { initPromise = null })
    return initPromise
  }

  // Wait for the Matrix client to finish initial sync. The preProvisionedRoomId
  // path in initMatrix calls startClient but does NOT await sync PREPARED (unlike
  // findOrCreateManagerDmRoom which does). Reading room.timeline before sync
  // returns an incomplete/empty list, so loadMessages must wait here first.
  async function waitForMatrixSync(timeoutMs = 10000): Promise<void> {
    if (!matrixClient) return
    // Capture into a const so TS narrows for the closures below (the outer
    // matrixClient is a `let` that could be reassigned by disconnect()).
    const client = matrixClient
    const state = client.getSyncState()
    if (state === 'PREPARED') return

    return new Promise<void>((resolve) => {
      const timeoutId = setTimeout(() => {
        client.removeListener('sync' as any, onSync)
        resolve() // resolve anyway after timeout — room may still have partial timeline
      }, timeoutMs)

      const onSync = (state: string) => {
        if (state === 'PREPARED' || state === 'ERROR' || state === 'STOPPED') {
          clearTimeout(timeoutId)
          client.removeListener('sync' as any, onSync)
          resolve()
        }
      }
      client.on('sync' as any, onSync)
    })
  }

  // @ts-ignore — event/room are typed as any here for flexibility
  function handleRoomEvent(event: any, room: any, toStartOfTimeline: boolean) {
    if (toStartOfTimeline) return  // ignore historical replay on sync
    if (room?.roomId !== dmRoomId) return
    if (event.getType() !== 'm.room.message') return
    if (event.getSender() === authStore.matrixUserId) return // ignore own messages

    // Ignore events that predate the most recent query (stale DM room history).
    // 5 s clock-skew buffer is generous enough for NTP-synced servers.
    const eventTs: number = (event.getServerTs?.() as number) || 0
    if (eventTs > 0 && queryStartTime > 0 && eventTs < queryStartTime - 5000) return

    const content = event.getContent()
    const xhb = content['x-honeybadge']

    // Returns true when the last assistant placeholder is still empty (not yet filled).
    function isPlaceholderEmpty(): boolean {
      const msgs = chatStore.currentMessages
      const last = [...msgs].reverse().find((m: any) => m.role === 'assistant')
      return !last || (last.content === '' && !last.metadata?.raw_data?.length)
    }

    if (!xhb) {
      const body = content.body || ''
      if (!body) return
      if (event.getSender() === MANAGER_USER_ID) {
        if (isPlaceholderEmpty()) {
          // Placeholder not yet filled — write into it.
          chatStore.finalizeAssistantMessage({
            summary: body,
            rawData: [],
            columns: [],
            cypher: '',
            traceId: '',
            executionTimeMs: 0,
            rowCount: 0,
          })
        } else {
          // Placeholder already filled (e.g. contract 002 arrived first) — append as new reply.
          chatStore.addMessage({
            id: uuidv4(),
            role: 'assistant',
            content: body,
            message_type: 'text',
            created_at: new Date().toISOString(),
          } as any)
        }
        chatStore.setLoading(false)
      } else if (chatStore.loading) {
        // Plain text from Worker — progress update
        chatStore.appendStreamContent(body + '\n')
      }
      return
    }

    if (xhb.contract === '002') {
      // Structured result
      const payload = xhb.payload || {}
      if (isPlaceholderEmpty()) {
        chatStore.finalizeAssistantMessage({
          summary: payload.summary || content.body || '',
          rawData: payload.raw_data || [],
          columns: payload.columns || [],
          cypher: payload.cypher || '',
          traceId: xhb.trace_id || '',
          executionTimeMs: payload.execution_time_ms || 0,
          rowCount: payload.row_count || 0,
        })
      } else {
        // Append contract 002 as a new message (e.g. second result in same session).
        chatStore.addMessage({
          id: uuidv4(),
          role: 'assistant',
          content: payload.summary || content.body || '',
          message_type: 'query_result',
          created_at: new Date().toISOString(),
          metadata: {
            cypher: payload.cypher || '',
            raw_data: payload.raw_data || [],
            columns: payload.columns || [],
            trace_id: xhb.trace_id || '',
            execution_time_ms: payload.execution_time_ms || 0,
          },
        } as any)
      }
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
    const ok = await ensureInitialized()
    if (!ok) {
      ElMessage.error('Matrix 连接未就绪')
      return
    }

    const userMessage: ChatMessage = {
      id: uuidv4(),
      role: 'user',
      content: question,
      message_type: 'text',
      created_at: new Date().toISOString(),
    }
    chatStore.addMessage(userMessage)
    chatStore.prepareAssistantMessage()
    chatStore.setLoading(true)
    queryStartTime = Date.now()  // record send time; filter stale DM events in handleRoomEvent

    try {
      await sendQuery(matrixClient!, dmRoomId!, question, authStore.rolesJwt || '')
    } catch (error: any) {
      console.error('Send query failed:', error)
      const statusCode = error?.httpStatus || error?.statusCode
      const errMsg = error?.data?.error || error?.message || '未知错误'
      if (statusCode === 401) {
        chatStore.setError('Matrix 认证已过期，请重新登录')
        ElMessage.error('Matrix 认证已过期，请重新登录')
        // Reset so next attempt re-inits
        disconnect()
      } else {
        chatStore.setError(`发送消息失败: ${errMsg}`)
        ElMessage.error(`发送消息失败: ${errMsg}`)
      }
      chatStore.setLoading(false)
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
      const ok = await ensureInitialized()
      if (!ok || !matrixClient || !dmRoomId) return

      await waitForMatrixSync()

      const room = matrixClient.getRoom(dmRoomId)
      if (!room) {
        console.warn('DM room not found in client store:', dmRoomId)
        return
      }

      // Fetch up to 50 historical events. Idempotent — won't duplicate events
      // already in the timeline from initialSyncLimit: 10.
      await matrixClient.scrollback(room, 50)

      // room.timeline is oldest (index 0) to newest (last index)
      const messages: ChatMessage[] = []
      for (const event of room.timeline) {
        const msg = matrixEventToChatMessage(event)
        if (msg) messages.push(msg)
      }

      chatStore.setMessages(sessionId, messages)
    } catch (error) {
      console.error('Failed to load messages from Matrix:', error)
      // Leave messages empty — same as the old backend path which returned []
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

  async function connect() {
    await ensureInitialized()
  }

  function disconnect() {
    if (matrixClient) {
      matrixClient.removeListener('Room.timeline' as any, handleRoomEvent)
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
