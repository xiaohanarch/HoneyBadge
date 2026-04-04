# Higress 网关设计

> 版本：v1.0
> 创建日期：2026-04-04
> 依赖：`05-frontend.md`（前端路由需求）, `02-hiclaw-orchestration.md`（后端服务）

---

## 1. 部署配置

### 1.1 Docker Compose 服务定义

```yaml
# docker-compose.yml 中的 Higress 服务
higress:
  image: higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/all-in-one:latest
  container_name: honeybadge-gateway
  ports:
    - "8080:8080"     # HTTP 入口
    - "8443:8443"     # HTTPS 入口（Phase 2 启用）
    - "8001:8001"     # Higress Console
  environment:
    - HIGRESS_ADMIN_USER=admin
    - HIGRESS_ADMIN_PASSWORD=${GATEWAY_ADMIN_PASSWORD}
  volumes:
    - ./gateway/config:/data/config
  networks:
    - honeybadge-net
  depends_on:
    - hiclaw-manager
  restart: unless-stopped
```

---

## 2. 路由规则

### 2.1 路由表

| 路径匹配 | 上游服务 | 协议 | 说明 |
|---------|---------|------|------|
| `/ws/*` | hiclaw-manager:8090 | WebSocket | 聊天主通道 |
| `/api/auth/*` | hiclaw-manager:8090 | HTTP | 认证服务（Manager 内置） |
| `/api/sessions/*` | hiclaw-manager:8090 | HTTP | 会话管理（Manager 内置） |
| `/api/health` | hiclaw-manager:8090 | HTTP | 健康检查 |
| `/api/version` | 静态响应 | HTTP | 版本信息 |
| `/*` | frontend:5173 | HTTP | 前端静态资源（开发环境）|

### 2.2 Higress 路由配置

```yaml
# gateway/config/routes.yaml
apiVersion: networking.higress.io/v1
kind: HTTPRoute
metadata:
  name: websocket-route
spec:
  hostnames:
    - "honeybadge.local"
  rules:
    # WebSocket 路由
    - matches:
        - path:
            type: PathPrefix
            value: /ws
      backendRefs:
        - name: hiclaw-manager
          port: 8090

    # 认证 API（Manager 内置处理）
    - matches:
        - path:
            type: PathPrefix
            value: /api/auth
      backendRefs:
        - name: hiclaw-manager
          port: 8090

    # 会话 API（Manager 内置处理）
    - matches:
        - path:
            type: PathPrefix
            value: /api/sessions
      backendRefs:
        - name: hiclaw-manager
          port: 8090

    # 健康检查
    - matches:
        - path:
            type: Exact
            value: /api/health
      backendRefs:
        - name: hiclaw-manager
          port: 8090

    # 前端
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - name: frontend
          port: 5173
```

---

## 3. Phase 1 基础认证

Phase 1 使用简单 JWT token 认证，不对接 SSO。

### 3.1 认证流程

```
1. 用户 POST /api/auth/login {username, password}
2. auth-service 验证 → 返回 JWT token
3. 前端将 token 存入 localStorage
4. 后续请求通过 Header: Authorization: Bearer <token>
5. WebSocket 连接通过 URL 参数: /ws/chat?token=<token>
6. Higress 网关校验 token 有效性
```

### 3.2 Higress 认证插件配置

```yaml
# gateway/config/auth.yaml
apiVersion: extensions.higress.io/v1alpha1
kind: WasmPlugin
metadata:
  name: jwt-auth
spec:
  url: oci://higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/jwt-auth:latest
  phase: AUTHN
  matchRules:
    # 排除不需要认证的路径
    - exclude:
        - /api/auth/login
        - /api/health
        - /api/version
      config:
        consumers:
          - name: honeybadge-user
            issuer: honeybadge
            jwks: |
              {
                "keys": [{
                  "kty": "oct",
                  "kid": "honeybadge-key",
                  "k": "${JWT_SECRET_BASE64}"
                }]
              }
```

### 3.3 JWT Token 结构

```json
{
  "sub": "user_001",
  "name": "张三",
  "roles": ["user"],
  "org_id": 1001,
  "dept_id": 2001,
  "iat": 1712188800,
  "exp": 1712275200
}
```

---

## 4. SSO 预留设计

### 4.1 OAuth2/OIDC 集成点标记

```yaml
# 以下配置 Phase 1 注释保留，Phase 2 启用

# gateway/config/sso-placeholder.yaml
# apiVersion: extensions.higress.io/v1alpha1
# kind: WasmPlugin
# metadata:
#   name: oauth2-proxy
# spec:
#   url: oci://higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/oauth2:latest
#   phase: AUTHN
#   config:
#     provider: generic-oidc
#     client_id: "${SSO_CLIENT_ID}"
#     client_secret: "${SSO_CLIENT_SECRET}"
#     issuer_url: "${SSO_ISSUER_URL}"      # 企业 SSO 的 OIDC 发现端点
#     redirect_url: "https://honeybadge.company.com/oauth2/callback"
#     scopes: ["openid", "profile", "email"]
#     token_endpoint_auth_method: client_secret_post
```

### 4.2 用户身份透传 Header 约定

无论使用 JWT 还是 SSO，网关统一向后端服务透传以下 Header：

| Header | 说明 | 来源 |
|--------|------|------|
| `X-User-Id` | 用户唯一标识 | JWT sub / SSO user_id |
| `X-User-Name` | 用户显示名 | JWT name / SSO display_name |
| `X-User-Roles` | 角色列表（逗号分隔） | JWT roles / SSO groups |
| `X-User-Org` | 组织 ID | JWT org_id / SSO org |
| `X-User-Dept` | 部门 ID | JWT dept_id / SSO dept |
| `X-Request-Id` | 请求追踪 ID | 网关自动生成 UUID |

```yaml
# gateway/config/header-transform.yaml
apiVersion: extensions.higress.io/v1alpha1
kind: WasmPlugin
metadata:
  name: header-transform
spec:
  url: oci://higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/transformer:latest
  phase: UNSPECIFIED
  config:
    reqAdd:
      - "X-Request-Id: ${request_id}"
    reqSet:
      # 从 JWT claims 提取并设置
      - "X-User-Id: ${jwt.sub}"
      - "X-User-Name: ${jwt.name}"
      - "X-User-Roles: ${jwt.roles}"
      - "X-User-Org: ${jwt.org_id}"
      - "X-User-Dept: ${jwt.dept_id}"
```

---

## 5. 限流配置

### 5.1 全局限流

```yaml
# gateway/config/rate-limit.yaml
apiVersion: extensions.higress.io/v1alpha1
kind: WasmPlugin
metadata:
  name: rate-limit
spec:
  url: oci://higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/key-rate-limit:latest
  config:
    # 全局限流
    limit_by_header: X-User-Id
    limit_by_per_header:
      qps: 10           # 每用户每秒 10 请求
    limit_by_per_ip:
      qps: 100          # 每 IP 每秒 100 请求（防刷）
```

### 5.2 WebSocket 连接数限制

```yaml
# WebSocket 特殊限流
websocket_limits:
  max_connections_per_user: 3     # 每用户最多 3 个 WS 连接
  max_connections_total: 500      # 系统总 WS 连接数
  idle_timeout: 300s              # 5 分钟无消息断开
  max_message_size: 64KB          # 单条消息最大 64KB
```

---

## 6. CORS 配置

```yaml
# gateway/config/cors.yaml
apiVersion: extensions.higress.io/v1alpha1
kind: WasmPlugin
metadata:
  name: cors
spec:
  url: oci://higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/cors:latest
  config:
    allow_origins:
      - "http://localhost:3000"          # 开发环境
      - "http://localhost:5173"          # Vite dev server
      - "https://honeybadge.company.com" # 生产环境（Phase 2）
    allow_methods:
      - GET
      - POST
      - PUT
      - DELETE
      - OPTIONS
    allow_headers:
      - Authorization
      - Content-Type
      - X-Request-Id
    expose_headers:
      - X-Request-Id
    allow_credentials: true
    max_age: 86400
```

---

## 7. WebSocket 代理配置

```yaml
# Higress WebSocket 代理特殊配置
websocket_proxy:
  # 升级协议
  upgrade_type: websocket
  # 后端超时
  connect_timeout: 5s
  read_timeout: 120s       # Agent 执行可能较长
  write_timeout: 30s
  # Sticky session（确保同一用户路由到同一 Manager）
  session_affinity:
    type: cookie
    cookie_name: HONEYBADGE_SESSION
    ttl: 3600
```
