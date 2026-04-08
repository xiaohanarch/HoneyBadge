import { ref, onUnmounted } from 'vue';
import type { WSMessage } from '@/types';

export interface UseWebSocketOptions {
  url: string;
  token: string;
  onMessage?: (msg: WSMessage) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (error: Event) => void;
}

export interface UseWebSocketReturn {
  connected: typeof connected;
  connect: () => void;
  disconnect: () => void;
  send: (message: WSMessage) => void;
  reconnectAttempts: typeof reconnectAttempts;
}

const connected = ref(false);
const reconnectAttempts = ref(0);
const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000];
const HEARTBEAT_INTERVAL = 30000;

let ws: WebSocket | null = null;
let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

export function useWebSocket(options: UseWebSocketOptions): UseWebSocketReturn {
  const { url, onMessage, onConnect, onDisconnect, onError } = options;

  function connect() {
    if (ws && ws.readyState === WebSocket.OPEN) {
      return;
    }

    // Always read the latest token from localStorage at connect time
    const currentToken = localStorage.getItem('token') || options.token;
    ws = new WebSocket(`${url}?token=${currentToken}`);

    ws.onopen = () => {
      connected.value = true;
      reconnectAttempts.value = 0;
      startHeartbeat();
      onConnect?.();
    };

    ws.onclose = (event) => {
      connected.value = false;
      stopHeartbeat();
      onDisconnect?.();

      if (!event.wasClean && reconnectAttempts.value < MAX_RECONNECT_ATTEMPTS) {
        scheduleReconnect();
      }
    };

    ws.onerror = (error) => {
      connected.value = false;
      onError?.(error);
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WSMessage;
        onMessage?.(msg);
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };
  }

  function startHeartbeat() {
    stopHeartbeat();
    heartbeatTimer = setInterval(() => {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: 'heartbeat',
          payload: {},
          timestamp: Date.now(),
        }));
      }
    }, HEARTBEAT_INTERVAL);
  }

  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
  }

  function scheduleReconnect() {
    const delay = RECONNECT_DELAYS[
      Math.min(reconnectAttempts.value, RECONNECT_DELAYS.length - 1)
    ];

    reconnectTimer = setTimeout(() => {
      reconnectAttempts.value++;
      connect();
    }, delay);
  }

  function send(message: WSMessage) {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(message));
    } else {
      console.warn('WebSocket is not connected');
    }
  }

  function disconnect() {
    stopHeartbeat();

    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }

    if (ws) {
      ws.close(1000, 'Client disconnect');
      ws = null;
    }

    connected.value = false;
  }

  onUnmounted(() => {
    disconnect();
  });

  return {
    connected,
    connect,
    disconnect,
    send,
    reconnectAttempts,
  };
}
