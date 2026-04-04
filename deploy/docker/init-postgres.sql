-- HoneyBadge PostgreSQL Schema Initialization
-- Creates audit log tables for L5 full-chain audit logging

-- Create extension for UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Create honeybadge schema
CREATE SCHEMA IF NOT EXISTS honeybadge_audit;
SET search_path TO honeybadge_audit;

-- =============================================================================
-- Chat Sessions Table
-- =============================================================================

CREATE TABLE IF NOT EXISTS chat_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         VARCHAR(64) NOT NULL,
    session_id      VARCHAR(64) NOT NULL UNIQUE,
    title           VARCHAR(256),                          -- Session title
    room_id         VARCHAR(256),                          -- Matrix Room ID
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at     TIMESTAMPTZ,
    message_count   INT DEFAULT 0,
    status          VARCHAR(20) DEFAULT 'active'           -- active / archived / deleted
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON chat_sessions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON chat_sessions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_session_id ON chat_sessions(session_id);

-- =============================================================================
-- Chat Messages Table
-- =============================================================================

CREATE TABLE IF NOT EXISTS chat_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      VARCHAR(64) NOT NULL,
    role            VARCHAR(20) NOT NULL,                  -- user / assistant / system
    content         TEXT NOT NULL,
    message_type    VARCHAR(20) DEFAULT 'text',             -- text / cypher / data / error
    metadata        JSONB,                                  -- trace_id, cypher, raw_data etc.
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id, created_at);

-- =============================================================================
-- Audit Logs Table (L5 Anti-Hallucination Framework)
-- =============================================================================

CREATE TABLE IF NOT EXISTS audit_logs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id            VARCHAR(64) NOT NULL UNIQUE,
    question            TEXT NOT NULL,
    cypher              TEXT NOT NULL,
    raw_result          JSONB NOT NULL,                    -- Full query result
    summary             TEXT,                              -- AI-generated summary
    user_id             VARCHAR(64) NOT NULL,
    session_id          VARCHAR(64) NOT NULL,
    execution_time_ms   INT NOT NULL,
    row_count           INT NOT NULL,
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_trace_id ON audit_logs(trace_id);
CREATE INDEX IF NOT EXISTS idx_audit_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_session_id ON audit_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_logs(created_at DESC);

-- =============================================================================
-- Audit Log for Multi-Step Analytics
-- =============================================================================

CREATE TABLE IF NOT EXISTS analytics_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id            VARCHAR(64) NOT NULL UNIQUE,
    user_question       TEXT NOT NULL,
    analysis_type       VARCHAR(50),                        -- anomaly_detection / trend / comparison
    report              TEXT,
    steps_metadata      JSONB,                              -- Metadata about each step
    total_rows          INT DEFAULT 0,
    user_id             VARCHAR(64) NOT NULL,
    session_id          VARCHAR(64) NOT NULL,
    execution_time_ms   INT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_trace_id ON analytics_runs(trace_id);
CREATE INDEX IF NOT EXISTS idx_analytics_user_id ON analytics_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_analytics_created_at ON analytics_runs(created_at DESC);

-- =============================================================================
-- Function: Update timestamp trigger
-- =============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply trigger to sessions table
CREATE TRIGGER update_chat_sessions_updated_at
    BEFORE UPDATE ON chat_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- Comments
-- =============================================================================

COMMENT ON TABLE chat_sessions IS 'User chat sessions - tracks conversation context';
COMMENT ON TABLE chat_messages IS 'Individual messages within a chat session';
COMMENT ON TABLE audit_logs IS 'L5 Audit Log: Full chain (question -> cypher -> result -> summary)';
COMMENT ON TABLE analytics_runs IS 'Multi-step analytics run metadata and reports';
