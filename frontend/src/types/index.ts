// WebSocket 消息协议
export interface WSMessage {
  type: 'query' | 'response' | 'stream' | 'progress' | 'error' | 'heartbeat';
  payload: unknown;
  trace_id?: string;
  timestamp: number;
}

export interface QueryRequest {
  type: 'query';
  payload: {
    question: string;
    session_id: string;
  };
}

export interface StreamChunk {
  type: 'stream';
  payload: {
    content: string;        // 增量文本
    phase: 'thinking' | 'cypher' | 'executing' | 'summarizing';
    done: boolean;
  };
  trace_id: string;
}

export interface ProgressUpdate {
  type: 'progress';
  payload: {
    step: string;           // 当前步骤描述
    step_number: number;    // 步骤序号 (1-based)
    total_steps: number;    // 总步骤数
    detail?: string;
  };
  trace_id: string;
}

export interface QueryResponse {
  type: 'response';
  payload: {
    summary: string;        // AI 摘要
    raw_data: Record<string, unknown>[];  // 原始数据
    columns: string[];      // 列名
    cypher: string;         // 执行的 nGQL
    trace_id: string;
    execution_time_ms: number;
    row_count: number;
  };
}

export interface ErrorResponse {
  type: 'error';
  payload: {
    code: string;           // 错误码
    message: string;        // 错误消息
    trace_id?: string;
  };
}

// 会话
export interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  status: 'active' | 'archived';
}

export interface ChatMessage {
  id: string;
  session_id?: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  message_type: 'text' | 'query_result' | 'error';
  metadata?: {
    trace_id?: string;
    cypher?: string;
    raw_data?: Record<string, unknown>[];
    columns?: string[];
    execution_time_ms?: number;
  };
  created_at: string;
}

// 用户
export interface User {
  id: string;
  username: string;
  display_name: string;
  roles: string[];
  org_id?: number;
}

// 认证
export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  token: string;
  refresh_token: string;
  user: User;
}

export interface AuthState {
  token: string | null;
  refreshToken: string | null;
  user: User | null;
  isAuthenticated: boolean;
}
