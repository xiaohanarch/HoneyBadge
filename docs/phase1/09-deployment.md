# Docker Compose 开发环境

> 版本：v1.0
> 创建日期：2026-04-04
> 依赖：所有其他模块文档

---

## 1. 服务总览

| 服务 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| nebula-metad | vesoft/nebula-metad | 9559 | NebulaGraph Meta 服务 |
| nebula-graphd | vesoft/nebula-graphd | 9669 | NebulaGraph Graph 服务 |
| nebula-storaged | vesoft/nebula-storaged | 9779 | NebulaGraph Storage 服务 |
| nebula-console | vesoft/nebula-console | - | nGQL 命令行（按需启动） |
| nebula-studio | vesoft/nebula-graph-studio | 7001 | NebulaGraph Web UI |
| redis | redis:7-alpine | 6379 | 缓存/会话状态 |
| postgres | postgres:16-alpine | 5432 | 审计日志/会话持久化/ODS |
| kafka | bitnami/kafka | 9092 | 消息队列 |
| minio | minio/minio | 9000,9001 | 对象存储 |
| higress | higress/all-in-one | 8080,8001 | API 网关 |
| prometheus | prom/prometheus | 9090 | 指标采集 |
| grafana | grafana/grafana | 3000 | 监控看板 |
| loki | grafana/loki | 3100 | 日志聚合 |
| promtail | grafana/promtail | 9080 | 日志采集 |
| jaeger | jaegertracing/all-in-one | 16686,6831 | 链路追踪 |
| conduit | matrixconduit/matrix-conduit | 6167 | Matrix Server |
| hiclaw-manager | honeybadge/manager | 8090 | HiClaw Manager |
| hiclaw-worker | honeybadge/worker | - | HiClaw Worker（多实例） |
| frontend | node:20-alpine | 5173 | Vue 3 开发服务器 |

---

## 2. docker-compose.yml

```yaml
version: "3.9"

services:
  # ============================================
  # NebulaGraph (单机模式: 1 metad + 1 graphd + 1 storaged)
  # ============================================
  nebula-metad:
    image: vesoft/nebula-metad:v3.8.0
    container_name: honeybadge-metad
    environment:
      USER: root
      TZ: Asia/Shanghai
    command:
      - --meta_server_addrs=nebula-metad:9559
      - --local_ip=nebula-metad
      - --ws_ip=nebula-metad
      - --port=9559
      - --ws_http_port=19559
      - --data_path=/data/meta
      - --log_dir=/logs
      - --v=0
      - --minloglevel=0
    volumes:
      - nebula-metad-data:/data/meta
      - nebula-metad-logs:/logs
    ports:
      - "9559:9559"
      - "19559:19559"
    networks:
      - honeybadge-net
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://nebula-metad:19559/status"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  nebula-storaged:
    image: vesoft/nebula-storaged:v3.8.0
    container_name: honeybadge-storaged
    environment:
      USER: root
      TZ: Asia/Shanghai
    command:
      - --meta_server_addrs=nebula-metad:9559
      - --local_ip=nebula-storaged
      - --ws_ip=nebula-storaged
      - --port=9779
      - --ws_http_port=19779
      - --data_path=/data/storage
      - --log_dir=/logs
      - --v=0
      - --minloglevel=0
    volumes:
      - nebula-storaged-data:/data/storage
      - nebula-storaged-logs:/logs
    ports:
      - "9779:9779"
      - "19779:19779"
    networks:
      - honeybadge-net
    depends_on:
      nebula-metad:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://nebula-storaged:19779/status"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  nebula-graphd:
    image: vesoft/nebula-graphd:v3.8.0
    container_name: honeybadge-graphd
    environment:
      USER: root
      TZ: Asia/Shanghai
    command:
      - --meta_server_addrs=nebula-metad:9559
      - --local_ip=nebula-graphd
      - --ws_ip=nebula-graphd
      - --port=9669
      - --ws_http_port=19669
      - --log_dir=/logs
      - --v=0
      - --minloglevel=0
    ports:
      - "9669:9669"
      - "19669:19669"
    networks:
      - honeybadge-net
    depends_on:
      nebula-storaged:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://nebula-graphd:19669/status"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  nebula-studio:
    image: vesoft/nebula-graph-studio:v3.10.0
    container_name: honeybadge-studio
    ports:
      - "7001:7001"
    networks:
      - honeybadge-net
    depends_on:
      nebula-graphd:
        condition: service_healthy
    restart: unless-stopped

  # ============================================
  # Redis
  # ============================================
  redis:
    image: redis:7-alpine
    container_name: honeybadge-redis
    command: redis-server --requirepass ${REDIS_PASSWORD} --maxmemory 512mb --maxmemory-policy allkeys-lru
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    networks:
      - honeybadge-net
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3
    restart: unless-stopped

  # ============================================
  # PostgreSQL (审计日志 + ODS + 会话)
  # ============================================
  postgres:
    image: postgres:16-alpine
    container_name: honeybadge-postgres
    environment:
      POSTGRES_USER: ${PG_USER}
      POSTGRES_PASSWORD: ${PG_PASSWORD}
      POSTGRES_DB: honeybadge
      TZ: Asia/Shanghai
    ports:
      - "5432:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./deploy/postgres/init.sql:/docker-entrypoint-initdb.d/01-init.sql
    networks:
      - honeybadge-net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${PG_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  # ============================================
  # Kafka (单节点 KRaft 模式，无 Zookeeper)
  # ============================================
  kafka:
    image: bitnami/kafka:3.7
    container_name: honeybadge-kafka
    environment:
      - KAFKA_CFG_NODE_ID=1
      - KAFKA_CFG_PROCESS_ROLES=broker,controller
      - KAFKA_CFG_CONTROLLER_QUORUM_VOTERS=1@kafka:9093
      - KAFKA_CFG_LISTENERS=PLAINTEXT://:9092,CONTROLLER://:9093
      - KAFKA_CFG_ADVERTISED_LISTENERS=PLAINTEXT://kafka:9092
      - KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
      - KAFKA_CFG_CONTROLLER_LISTENER_NAMES=CONTROLLER
      - KAFKA_CFG_AUTO_CREATE_TOPICS_ENABLE=true
    ports:
      - "9092:9092"
    volumes:
      - kafka-data:/bitnami/kafka
    networks:
      - honeybadge-net
    restart: unless-stopped

  # ============================================
  # MinIO
  # ============================================
  minio:
    image: minio/minio:latest
    container_name: honeybadge-minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_PASSWORD}
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio-data:/data
    networks:
      - honeybadge-net
    restart: unless-stopped

  # ============================================
  # Higress 网关
  # ============================================
  higress:
    image: higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/all-in-one:latest
    container_name: honeybadge-gateway
    ports:
      - "8080:8080"
      - "8001:8001"
    environment:
      - HIGRESS_ADMIN_USER=admin
      - HIGRESS_ADMIN_PASSWORD=${GATEWAY_ADMIN_PASSWORD}
    volumes:
      - ./deploy/gateway/config:/data/config
    networks:
      - honeybadge-net
    depends_on:
      - redis
    restart: unless-stopped

  # ============================================
  # 可观测性
  # ============================================
  prometheus:
    image: prom/prometheus:v2.51.0
    container_name: honeybadge-prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=30d'
    ports:
      - "9090:9090"
    volumes:
      - ./deploy/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
      - ./deploy/prometheus/rules:/etc/prometheus/rules
      - prometheus-data:/prometheus
    networks:
      - honeybadge-net
    restart: unless-stopped

  grafana:
    image: grafana/grafana:11.0.0
    container_name: honeybadge-grafana
    environment:
      GF_SECURITY_ADMIN_USER: ${GRAFANA_USER}
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD}
    ports:
      - "3000:3000"
    volumes:
      - grafana-data:/var/lib/grafana
      - ./deploy/grafana/provisioning:/etc/grafana/provisioning
      - ./deploy/grafana/dashboards:/var/lib/grafana/dashboards
    networks:
      - honeybadge-net
    depends_on:
      - prometheus
      - loki
    restart: unless-stopped

  loki:
    image: grafana/loki:3.0.0
    container_name: honeybadge-loki
    command: -config.file=/etc/loki/loki-config.yaml
    ports:
      - "3100:3100"
    volumes:
      - ./deploy/loki/loki-config.yaml:/etc/loki/loki-config.yaml
      - loki-data:/loki
    networks:
      - honeybadge-net
    restart: unless-stopped

  promtail:
    image: grafana/promtail:3.0.0
    container_name: honeybadge-promtail
    command: -config.file=/etc/promtail/promtail-config.yaml
    volumes:
      - ./deploy/promtail/promtail-config.yaml:/etc/promtail/promtail-config.yaml
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - honeybadge-net
    depends_on:
      - loki
    restart: unless-stopped

  jaeger:
    image: jaegertracing/all-in-one:1.56
    container_name: honeybadge-jaeger
    environment:
      COLLECTOR_OTLP_ENABLED: "true"
    ports:
      - "16686:16686"   # Jaeger UI
      - "6831:6831/udp" # Agent (Thrift compact)
      - "4317:4317"     # OTLP gRPC
      - "4318:4318"     # OTLP HTTP
    networks:
      - honeybadge-net
    restart: unless-stopped

  # ============================================
  # Matrix Server (Conduit)
  # ============================================
  conduit:
    image: matrixconduit/matrix-conduit:latest
    container_name: honeybadge-matrix
    environment:
      CONDUIT_SERVER_NAME: matrix.local
      CONDUIT_DATABASE_BACKEND: rocksdb
      CONDUIT_ALLOW_REGISTRATION: "true"
      CONDUIT_PORT: 6167
    ports:
      - "6167:6167"
    volumes:
      - conduit-data:/var/lib/conduit
    networks:
      - honeybadge-net
    restart: unless-stopped

  # ============================================
  # HiClaw (Manager + Worker)
  # ============================================
  hiclaw-manager:
    build:
      context: .
      dockerfile: deploy/hiclaw/Dockerfile.manager
    container_name: honeybadge-manager
    environment:
      - LLM_ENDPOINT=${LLM_ENDPOINT}
      - LLM_API_KEY=${LLM_API_KEY}
      - LLM_MODEL_NAME=${LLM_MODEL_NAME}
      - MATRIX_HOMESERVER_URL=http://conduit:6167
      - MATRIX_BOT_TOKEN=${MATRIX_BOT_TOKEN}
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
      - NEBULA_GRAPHD_HOST=nebula-graphd
      - NEBULA_GRAPHD_PORT=9669
      - PG_DSN=postgresql://${PG_USER}:${PG_PASSWORD}@postgres:5432/honeybadge
      - JAEGER_AGENT_HOST=jaeger
      - JAEGER_AGENT_PORT=6831
    ports:
      - "8090:8090"
    networks:
      - honeybadge-net
    depends_on:
      nebula-graphd:
        condition: service_healthy
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
      conduit:
        condition: service_started
    restart: unless-stopped

  hiclaw-graph-worker:
    build:
      context: .
      dockerfile: deploy/hiclaw/Dockerfile.worker
    container_name: honeybadge-graph-worker
    environment:
      - WORKER_GROUP=graph
      - WORKER_SKILLS=cypher_query
      - LLM_ENDPOINT=${LLM_ENDPOINT}
      - LLM_API_KEY=${LLM_API_KEY}
      - LLM_MODEL_NAME=${LLM_MODEL_NAME}
      - MATRIX_HOMESERVER_URL=http://conduit:6167
      - MATRIX_BOT_TOKEN=${MATRIX_WORKER_TOKEN}
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
      - NEBULA_GRAPHD_HOST=nebula-graphd
      - NEBULA_GRAPHD_PORT=9669
      - NEBULA_USER=${NEBULA_USER}
      - NEBULA_PASSWORD=${NEBULA_PASSWORD}
      - PG_DSN=postgresql://${PG_USER}:${PG_PASSWORD}@postgres:5432/honeybadge
      - JAEGER_AGENT_HOST=jaeger
    networks:
      - honeybadge-net
    depends_on:
      - hiclaw-manager
    restart: unless-stopped

  # ============================================
  # 前端开发服务器
  # ============================================
  frontend:
    image: node:20-alpine
    container_name: honeybadge-frontend
    working_dir: /app
    command: sh -c "npm install && npm run dev -- --host 0.0.0.0"
    ports:
      - "5173:5173"
    volumes:
      - ./frontend:/app
      - frontend-node-modules:/app/node_modules
    networks:
      - honeybadge-net
    restart: unless-stopped

# ============================================
# Volumes
# ============================================
volumes:
  nebula-metad-data:
  nebula-metad-logs:
  nebula-storaged-data:
  nebula-storaged-logs:
  redis-data:
  postgres-data:
  kafka-data:
  minio-data:
  prometheus-data:
  grafana-data:
  loki-data:
  conduit-data:
  frontend-node-modules:

# ============================================
# Networks
# ============================================
networks:
  honeybadge-net:
    driver: bridge
```

---

## 3. 环境变量配置

```bash
# .env.example

# ============================================
# LLM
# ============================================
LLM_PROVIDER=qwen                      # qwen / glm / openai
LLM_ENDPOINT=https://dashscope.aliyuncs.com/compatible-mode
LLM_API_KEY=sk-your-api-key-here
LLM_MODEL_NAME=qwen-max

# ============================================
# NebulaGraph
# ============================================
NEBULA_USER=root
NEBULA_PASSWORD=nebula

# ============================================
# PostgreSQL
# ============================================
PG_USER=honeybadge
PG_PASSWORD=change-me-in-production

# ============================================
# Redis
# ============================================
REDIS_PASSWORD=change-me-in-production

# ============================================
# MinIO
# ============================================
MINIO_USER=minioadmin
MINIO_PASSWORD=change-me-in-production

# ============================================
# Gateway
# ============================================
GATEWAY_ADMIN_PASSWORD=change-me-in-production

# ============================================
# Grafana
# ============================================
GRAFANA_USER=admin
GRAFANA_PASSWORD=change-me-in-production

# ============================================
# Matrix
# ============================================
MATRIX_BOT_TOKEN=matrix-bot-token
MATRIX_WORKER_TOKEN=matrix-worker-token

# ============================================
# JWT
# ============================================
JWT_SECRET=change-this-to-a-random-64-char-string
```

---

## 4. 初始化脚本

### 4.1 PostgreSQL 初始化

```sql
-- deploy/postgres/init.sql

-- 审计日志表
CREATE TABLE IF NOT EXISTS audit_query_log (
  id              BIGSERIAL PRIMARY KEY,
  trace_id        VARCHAR(64) NOT NULL UNIQUE,
  user_id         VARCHAR(64) NOT NULL,
  session_id      VARCHAR(64),
  user_question   TEXT NOT NULL,
  generated_ngql  TEXT,
  ngql_attempts   INT DEFAULT 1,
  validation_errors JSONB,
  execution_time_ms INT,
  result_row_count  INT,
  raw_result      JSONB,
  llm_summary     TEXT,
  llm_model       VARCHAR(64),
  total_tokens    INT,
  prompt_tokens   INT,
  completion_tokens INT,
  total_time_ms   INT,
  status          VARCHAR(20) NOT NULL,
  error_message   TEXT,
  org_id          BIGINT,
  dept_id         BIGINT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_trace ON audit_query_log(trace_id);
CREATE INDEX idx_audit_user ON audit_query_log(user_id, created_at DESC);
CREATE INDEX idx_audit_created ON audit_query_log(created_at DESC);
CREATE INDEX idx_audit_status ON audit_query_log(status, created_at DESC);

-- 会话表
CREATE TABLE IF NOT EXISTS chat_sessions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         VARCHAR(64) NOT NULL,
  session_id      VARCHAR(64) NOT NULL UNIQUE,
  title           VARCHAR(256),
  room_id         VARCHAR(256),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  archived_at     TIMESTAMPTZ,
  message_count   INT DEFAULT 0,
  status          VARCHAR(20) DEFAULT 'active'
);

CREATE INDEX idx_sessions_user ON chat_sessions(user_id, status);
CREATE INDEX idx_sessions_updated ON chat_sessions(updated_at DESC);

-- 消息表
CREATE TABLE IF NOT EXISTS chat_messages (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id      VARCHAR(64) NOT NULL REFERENCES chat_sessions(session_id),
  role            VARCHAR(20) NOT NULL,
  content         TEXT NOT NULL,
  message_type    VARCHAR(20) DEFAULT 'text',
  metadata        JSONB,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_messages_session ON chat_messages(session_id, created_at);

-- ETL 运行日志
CREATE TABLE IF NOT EXISTS etl_run_log (
  id              BIGSERIAL PRIMARY KEY,
  batch_id        VARCHAR(64) NOT NULL UNIQUE,
  status          VARCHAR(20) NOT NULL,
  start_time      TIMESTAMP NOT NULL,
  end_time        TIMESTAMP,
  total_records   BIGINT,
  passed_records  BIGINT,
  failed_records  BIGINT,
  quarantined     BIGINT,
  import_duration_sec INT,
  error_summary   JSONB,
  created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ETL 隔离区
CREATE TABLE IF NOT EXISTS etl_quarantine (
  id              BIGSERIAL PRIMARY KEY,
  batch_id        VARCHAR(64) NOT NULL,
  source_table    VARCHAR(64) NOT NULL,
  source_id       VARCHAR(128),
  error_type      VARCHAR(30) NOT NULL,
  error_detail    JSONB NOT NULL,
  severity        VARCHAR(10) NOT NULL,
  resolved        BOOLEAN DEFAULT false,
  resolved_by     VARCHAR(64),
  resolved_at     TIMESTAMP,
  created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 简化用户表 (Phase 1 基础认证)
CREATE TABLE IF NOT EXISTS users (
  id              VARCHAR(64) PRIMARY KEY,
  username        VARCHAR(64) NOT NULL UNIQUE,
  password_hash   VARCHAR(256) NOT NULL,
  display_name    VARCHAR(128),
  roles           VARCHAR(256) DEFAULT 'user',
  org_id          BIGINT,
  dept_id         BIGINT,
  status          VARCHAR(20) DEFAULT 'active',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 插入测试用户
INSERT INTO users (id, username, password_hash, display_name, roles, org_id, dept_id)
VALUES ('user_001', 'admin', '$2b$12$placeholder_hash', '管理员', 'admin,user', 1001, 2001)
ON CONFLICT (id) DO NOTHING;
```

### 4.2 NebulaGraph 初始化

```bash
#!/bin/bash
# deploy/nebula/init-schema.sh

echo "Waiting for NebulaGraph to be ready..."
sleep 15

echo "Creating space and schema..."
nebula-console -addr nebula-graphd -port 9669 -u root -p nebula -f /scripts/init-schema.ngql

echo "Creating indexes..."
nebula-console -addr nebula-graphd -port 9669 -u root -p nebula -f /scripts/init-indexes.ngql

echo "Rebuilding indexes..."
sleep 5
nebula-console -addr nebula-graphd -port 9669 -u root -p nebula -f /scripts/rebuild-indexes.ngql

echo "Done!"
```

---

## 5. 开发工作流

### 5.1 启动

```bash
# 首次启动
cp .env.example .env
# 编辑 .env，填入 LLM API Key 等

# 启动全部服务
docker compose up -d

# 检查服务状态
docker compose ps

# 初始化 NebulaGraph Schema（首次或 Schema 变更后）
docker compose exec nebula-graphd nebula-console \
  -addr nebula-graphd -port 9669 -u root -p nebula \
  -f /scripts/init-schema.ngql
```

### 5.2 停止

```bash
# 停止全部服务（保留数据）
docker compose stop

# 停止并删除容器（保留数据卷）
docker compose down

# 停止并删除全部（含数据卷）
docker compose down -v
```

### 5.3 日志查看

```bash
# 查看特定服务日志
docker compose logs -f hiclaw-manager
docker compose logs -f hiclaw-graph-worker

# 查看 NebulaGraph 日志
docker compose logs -f nebula-graphd
```

### 5.4 数据重置

```bash
# 重置 NebulaGraph 数据
docker compose stop nebula-graphd nebula-storaged nebula-metad
docker volume rm honeybadge_nebula-metad-data honeybadge_nebula-storaged-data
docker compose up -d nebula-metad nebula-storaged nebula-graphd
# 重新执行 Schema 初始化

# 重置 PostgreSQL 数据
docker compose stop postgres
docker volume rm honeybadge_postgres-data
docker compose up -d postgres

# 重置全部
docker compose down -v
docker compose up -d
```

### 5.5 常用开发命令

```bash
# 连接 NebulaGraph Console
docker compose exec nebula-graphd nebula-console \
  -addr nebula-graphd -port 9669 -u root -p nebula

# 连接 PostgreSQL
docker compose exec postgres psql -U honeybadge -d honeybadge

# 连接 Redis
docker compose exec redis redis-cli -a ${REDIS_PASSWORD}

# 重建单个服务
docker compose up -d --build hiclaw-manager
```

### 5.6 Web UI 访问

| 服务 | URL | 默认账号 |
|------|-----|---------|
| 前端 | http://localhost:5173 | admin / (见 .env) |
| NebulaGraph Studio | http://localhost:7001 | root / nebula |
| Grafana | http://localhost:3000 | admin / (见 .env) |
| Jaeger UI | http://localhost:16686 | - |
| Higress Console | http://localhost:8001 | admin / (见 .env) |
| MinIO Console | http://localhost:9001 | (见 .env) |
| Prometheus | http://localhost:9090 | - |
