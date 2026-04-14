"""
Central CSS selector constants for HoneyBadge E2E tests.
Aligned to actual frontend DOM: ChatMessage.vue, ChatView.vue, LoginView.vue,
QueryResult.vue, CypherBlock.vue.
"""

# =============================================================================
# Login (LoginView.vue)
# =============================================================================
LOGIN_USERNAME = 'input[autocomplete="username"]'
LOGIN_PASSWORD = 'input[type="password"]'
LOGIN_BUTTON = '.login-button'
LOGIN_FORM = '.login-form'
SSO_BUTTON = '.sso-button'
LOGIN_CONTAINER = '.login-container'

# =============================================================================
# Chat Layout (ChatView.vue)
# =============================================================================
CHAT_LAYOUT = '.chat-layout'
CHAT_HEADER = '.chat-header'
CONNECTION_TAG = '.chat-header .el-tag'
CONNECTION_SUCCESS = '.el-tag.el-tag--success'
SIDEBAR = '.sidebar'
SESSION_LIST = '.session-list'
SESSION_ITEM = '.session-item'
SESSION_ACTIVE = '.session-item.active'
SESSION_TITLE = '.session-title'
SESSION_ACTIONS = '.session-actions'
NEW_CHAT_BUTTON = 'button:has-text("新对话")'
USER_AVATAR = '.user-avatar'
LOGOUT_ITEM = '.el-dropdown-item:has-text("退出登录")'

# =============================================================================
# Messages (ChatMessage.vue)
# =============================================================================
MSG_ASSISTANT = '.chat-message.message-assistant'
MSG_USER = '.chat-message.message-user'
MSG_ERROR = '.chat-message.message-error'
MSG_SYSTEM = '.chat-message.message-system'
MSG_TEXT = '.message-body .message-text'
MSG_RESULT = '.message-body .message-result'
MSG_BODY = '.message-body'
MSG_ROLE = '.message-role'
MSG_TIME = '.message-time'
MESSAGES_CONTAINER = '.messages-container'

# =============================================================================
# Result Elements (QueryResult.vue, CypherBlock.vue)
# =============================================================================
META_INFO = '.meta-info'
TRACE_ID_LINK = '.trace-id-link'
EXECUTION_TIME = '.execution-time'
CYPHER_COLLAPSE = '.cypher-collapse'
CYPHER_COLLAPSE_HEADER = '.cypher-collapse .el-collapse-item__header'
CYPHER_CODE = '.code-content code'
CYPHER_LANG = '.code-lang'
DATA_COLLAPSE = '.data-collapse'
DATA_COLLAPSE_HEADER = '.data-collapse .el-collapse-item__header'
DATA_TABLE = '.query-result .el-table'
DATA_ROWS = '.el-table__body tr'
DATA_CELLS = '.el-table__body td'
DATA_HEADERS = '.el-table__header th'
MORE_ROWS = '.more-rows'
SUMMARY = '.summary'

# =============================================================================
# Input Area (ChatView.vue)
# =============================================================================
INPUT_AREA = '.input-area'
INPUT_CONTAINER = '.input-container'
CHAT_TEXTAREA = '.input-container .el-textarea__inner'
SEND_BUTTON = '.send-button'

# =============================================================================
# Progress (ChatView.vue)
# =============================================================================
PROGRESS_AREA = '.progress-area'
