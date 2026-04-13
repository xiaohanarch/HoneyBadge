# HoneyBadge E2E Test Suite

自动化端到端测试套件，覆盖认证、聊天、会话管理、用户隔离、权限系统、反幻觉框架、MCP服务、基础设施和可观测性。

## 测试覆盖

| 测试文件 | 测试用例 | 覆盖范围 |
|---------|---------|---------|
| `test_01_auth.py` | TC-001 ~ TC-008 | 用户认证、登录、登出、路由守卫 |
| `test_02_chat.py` | TC-101 ~ TC-112 | 聊天功能、流式响应、结果展示 |
| `test_03_session.py` | TC-201 ~ TC-208 | 会话管理、增删改查 |
| `test_04_isolation.py` | TC-301 ~ TC-308 | 用户隔离、多租户数据隔离 |
| `test_05_permissions.py` | TC-401 ~ TC-408 | 权限系统、角色访问控制 |
| `test_06_antihal.py` | TC-501 ~ TC-510 | 反幻觉框架 (L1-L5) |
| `test_07_mcp.py` | TC-601 ~ TC-608 | MCP 服务健康检查 |
| `test_08_infra.py` | TC-701 ~ TC-712 | 基础设施健康检查 |
| `test_09_observability.py` | TC-801 ~ TC-811 | 可观测性栈 (Prometheus/Grafana/Loki) |

**总计: 85+ 测试用例**

## 本地运行

### 前置条件

```bash
# 1. 安装 Python 依赖
pip install -r tests/e2e/requirements.txt

# 2. 安装 Playwright 浏览器
playwright install chromium
playwright install-deps

# 3. 确保 Docker 运行中
docker ps
```

### 运行所有测试

```bash
# Linux/macOS
./scripts/run-e2e-tests.sh

# Windows
.\scripts\run-e2e-tests.bat
```

### 运行特定测试

```bash
# 按标记过滤
pytest tests/e2e/ -m auth -v
pytest tests/e2e/ -m "chat and not slow" -v

# 按文件过滤
pytest tests/e2e/test_01_auth.py -v
pytest tests/e2e/test_02_chat.py tests/e2e/test_03_session.py -v

# 使用脚本
./scripts/run-e2e-tests.sh --filter auth    # 仅认证测试
./scripts/run-e2e-tests.sh --filter chat   # 仅聊天测试
./scripts/run-e2e-tests.sh --filter infra   # 仅基础设施测试
```

### 仅启动/停止基础设施

```bash
# 仅启动基础设施
./scripts/run-e2e-tests.sh --setup-only

# 跳过基础设施启动（假设已运行）
./scripts/run-e2e-tests.sh --skip-setup

# 仅停止基础设施
./scripts/run-e2e-tests.sh --teardown-only
```

## GitHub Actions

### 自动触发

E2E 测试在以下情况自动运行:

- PR 创建或更新到 `main` 或 `master` 分支
- `main/master` 分支有代码推送
- 手动触发 (workflow_dispatch)

### 查看测试结果

1. 访问 `https://github.com/<owner>/<repo>/actions`
2. 点击最新的 E2E Tests workflow run
3. 查看 "Test Summary" 部分

### 配置通知

测试失败时，自动发送通知到 Slack/Teams/Email。

在 GitHub仓库设置中添加以下 Secrets:

| Secret 名称 | 说明 |
|------------|------|
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL |
| `TEAMS_WEBHOOK_URL` | Microsoft Teams Webhook URL |
| `SMTP_*` | 邮件通知配置 (SMTP_SERVER, SMTP_USERNAME, 等) |

参见 `.github/workflows/.e2e-secrets.example` 获取完整配置示例。

## 测试标记

| 标记 | 说明 |
|-----|------|
| `e2e` | 所有 E2E 测试 |
| `auth` | 认证相关测试 |
| `chat` | 聊天功能测试 |
| `session` | 会话管理测试 |
| `isolation` | 用户隔离测试 |
| `permission` | 权限系统测试 |
| `antihal` | 反幻觉框架测试 |
| `mcp` | MCP 服务测试 |
| `infra` | 基础设施测试 |
| `observability` | 可观测性测试 |
| `slow` | 慢速测试 |

## 调试

### 查看详细输出

```bash
pytest tests/e2e/ -v -s --tb=long
```

### 仅运行失败的测试

```bash
pytest tests/e2e/ --lf
```

### 生成 HTML 报告

```bash
pytest tests/e2e/ --html=test-report.html --self-contained-html
```

## 贡献

添加新测试时:

1. 在适当的 `test_*.py` 文件中添加测试用例
2. 使用现有 fixtures (`admin_logged_in`, `wait_for_chat_ready`, 等)
3. 遵循 TC-XXX 命名规范
4. 添加文档注释说明测试目的
