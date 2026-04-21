"""
Playwright E2E Test Configuration and Fixtures
HoneyBadge - Enterprise Knowledge Graph Assistant
"""
import os
import re
import pytest
from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext
from tests.e2e.selectors import (
    LOGIN_USERNAME, LOGIN_PASSWORD, LOGIN_BUTTON,
    CHAT_TEXTAREA, MSG_ASSISTANT, MSG_USER, MESSAGES_CONTAINER,
    TRACE_ID_LINK, CYPHER_COLLAPSE_HEADER, CYPHER_CODE,
    DATA_COLLAPSE_HEADER, DATA_ROWS, DATA_TABLE,
    NEW_CHAT_BUTTON, SESSION_ITEM, INPUT_CONTAINER,
)


def _wait_for_textarea_enabled(page_obj, timeout=60000):
    """Wait for chat textarea to be visible and enabled."""
    page_obj.wait_for_function(
        """() => {
            const ta = document.querySelector('.input-container .el-textarea__inner');
            return ta && !ta.disabled;
        }""",
        timeout=timeout,
    )


def _wait_for_new_response(page_obj, existing_count: int, timeout: int = 60000):
    """Wait for a NEW assistant message to appear with meaningful content (>10 chars)."""
    page_obj.wait_for_function(
        f"""() => {{
            const msgs = document.querySelectorAll('.chat-message.message-assistant');
            if (msgs.length <= {existing_count}) return false;
            const last = msgs[msgs.length - 1];
            const body = last.querySelector('.message-body') || last;
            return body && body.textContent.trim().length > 10;
        }}""",
        timeout=timeout,
    )
    page_obj.wait_for_timeout(200)


def send_query_on_page(page_obj, query: str, timeout: int = 60000):
    """Send a chat query on any page object (standalone helper, not fixture-bound)."""
    _wait_for_textarea_enabled(page_obj, timeout=timeout)
    textarea = page_obj.locator(CHAT_TEXTAREA).first
    existing_count = page_obj.locator(MSG_ASSISTANT).count()
    textarea.fill(query)
    textarea.press("Enter")
    _wait_for_new_response(page_obj, existing_count, timeout=timeout)


# Configuration
BASE_URL = os.getenv("BASE_URL", "http://localhost:3000")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8090")
AUTH_BASE_URL = os.getenv("AUTH_BASE_URL", "http://localhost:8091")

# Demo Users
DEMO_USERS = {
    "admin": {"username": "admin", "password": "admin123", "roles": ["admin"], "org_id": 1000},
    "analyst": {"username": "analyst", "password": "analyst123", "roles": ["analyst"], "org_id": 1000},
    "auditor": {"username": "auditor", "password": "auditor123", "roles": ["auditor"], "org_id": 1000},
    "procurement_lead": {"username": "procurement_lead", "password": "lead123", "roles": ["analyst"], "org_id": 1000},
    "subsidiary_lead": {"username": "subsidiary_lead", "password": "lead123", "roles": ["analyst"], "org_id": 1021},
}


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "e2e: end-to-end tests")
    config.addinivalue_line("markers", "auth: authentication tests")
    config.addinivalue_line("markers", "chat: chat functionality tests")
    config.addinivalue_line("markers", "isolation: user isolation tests")
    config.addinivalue_line("markers", "permission: permission tests")
    config.addinivalue_line("markers", "infra: infrastructure tests")
    config.addinivalue_line("markers", "observability: observability tests")
    config.addinivalue_line("markers", "slow: slow running tests")
    config.addinivalue_line("markers", "routing: worker routing tests")


@pytest.fixture(scope="session")
def browser():
    """Launch browser for entire test session."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture(scope="function")
def page(browser: Browser):
    """Create a new page for each test."""
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
    )
    page = context.new_page()
    page.set_default_timeout(30000)  # 30 seconds default
    yield page
    page.close()
    context.close()


@pytest.fixture(scope="function")
def clean_context(browser: Browser):
    """Clean browser context for isolation tests."""
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
    )
    yield context
    context.close()


@pytest.fixture
def api_client():
    """HTTP API client for direct backend testing."""
    import httpx
    client = httpx.Client(base_url=API_BASE_URL, timeout=30)
    yield client
    client.close()


@pytest.fixture
def auth_api_client():
    """HTTP API client for auth service testing."""
    import httpx
    client = httpx.Client(base_url=AUTH_BASE_URL, timeout=30)
    yield client
    client.close()


@pytest.fixture
def login_as(page: Page):
    """Factory fixture to login as any user."""
    def _login(username: str, password: str):
        page.goto(f"{BASE_URL}/login")
        page.wait_for_selector(LOGIN_BUTTON, timeout=15000)
        page.fill(LOGIN_USERNAME, username)
        page.fill(LOGIN_PASSWORD, password)
        page.click(LOGIN_BUTTON)
        page.wait_for_url(f"{BASE_URL}/chat", timeout=30000)
        _wait_for_textarea_enabled(page, timeout=15000)
        return page
    return _login


@pytest.fixture
def admin_logged_in(page: Page, login_as):
    """Page authenticated as admin user."""
    login_as("admin", "admin123")
    return page


@pytest.fixture
def analyst_logged_in(page: Page, login_as):
    """Page authenticated as analyst user."""
    login_as("analyst", "analyst123")
    return page


@pytest.fixture
def auditor_logged_in(page: Page, login_as):
    """Page authenticated as auditor user."""
    login_as("auditor", "auditor123")
    return page


@pytest.fixture
def subsidiary_lead_logged_in(page: Page, login_as):
    """Page authenticated as subsidiary_lead user."""
    login_as("subsidiary_lead", "lead123")
    return page


@pytest.fixture
def wait_for_chat_ready(page: Page):
    """Wait for chat interface to be fully loaded."""
    def _wait():
        _wait_for_textarea_enabled(page, timeout=15000)
    return _wait


@pytest.fixture
def send_chat_query(page: Page):
    """Factory fixture to send a chat query and wait for response."""
    def _send(query: str, timeout: int = 60000):
        _wait_for_textarea_enabled(page, timeout=timeout)
        textarea = page.locator(CHAT_TEXTAREA).first
        existing_count = page.locator(MSG_ASSISTANT).count()
        textarea.fill(query)
        textarea.press("Enter")
        _wait_for_new_response(page, existing_count, timeout=timeout)
    return _send


@pytest.fixture
def create_user_page(browser: Browser):
    """Factory to create a new browser context+page logged in as a specific user."""
    pages = []
    contexts = []

    def _create(username: str, password: str):
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )
        p = context.new_page()
        p.set_default_timeout(30000)
        p.goto(f"{BASE_URL}/login")
        p.wait_for_selector(LOGIN_BUTTON, timeout=15000)
        p.fill(LOGIN_USERNAME, username)
        p.fill(LOGIN_PASSWORD, password)
        p.click(LOGIN_BUTTON)
        p.wait_for_url(f"{BASE_URL}/chat", timeout=30000)
        _wait_for_textarea_enabled(p, timeout=30000)

        new_session_btn = p.locator(NEW_CHAT_BUTTON)
        if new_session_btn.count() > 0 and new_session_btn.first.is_visible():
            new_session_btn.first.click()
            _wait_for_textarea_enabled(p, timeout=10000)

        pages.append(p)
        contexts.append(context)
        return p

    yield _create
    for p in pages:
        p.close()
    for c in contexts:
        c.close()


@pytest.fixture
def send_query_and_get_response(page: Page):
    """Send query, wait for full response, return structured data."""
    def _send(query: str, timeout: int = 60000):
        _wait_for_textarea_enabled(page, timeout=timeout)
        textarea = page.locator(CHAT_TEXTAREA).first
        existing_count = page.locator(MSG_ASSISTANT).count()
        textarea.fill(query)
        textarea.press("Enter")
        _wait_for_new_response(page, existing_count, timeout=timeout)

        last_msg = page.locator(MSG_ASSISTANT).last
        text = last_msg.inner_text()

        trace_id = None
        trace_link = last_msg.locator(TRACE_ID_LINK)
        if trace_link.count() > 0:
            trace_text = trace_link.first.inner_text()
            match = re.search(r'TRC-[\w-]+', trace_text)
            if match:
                trace_id = match.group(0)

        has_cypher = last_msg.locator(CYPHER_COLLAPSE_HEADER).count() > 0
        has_data_table = last_msg.locator(DATA_COLLAPSE_HEADER).count() > 0

        data_row_count = 0
        if has_data_table:
            last_msg.locator(DATA_COLLAPSE_HEADER).click()
            page.wait_for_timeout(500)
            data_row_count = last_msg.locator(DATA_ROWS).count()

        return {
            "text": text,
            "trace_id": trace_id,
            "has_cypher": has_cypher,
            "has_data_table": has_data_table,
            "data_row_count": data_row_count,
        }
    return _send


@pytest.fixture
def expand_cypher_block(page: Page):
    """Click cypher collapse header on last assistant message, return code text."""
    def _expand():
        last_msg = page.locator(MSG_ASSISTANT).last
        header = last_msg.locator(CYPHER_COLLAPSE_HEADER)
        if header.count() == 0:
            pytest.skip("No Cypher collapse block in response")
        header.click()
        page.wait_for_timeout(500)
        code = last_msg.locator(CYPHER_CODE)
        if code.count() == 0:
            return ""
        return code.first.inner_text()
    return _expand


@pytest.fixture
def expand_data_table(page: Page):
    """Click data collapse header on last assistant message, return row count."""
    def _expand():
        last_msg = page.locator(MSG_ASSISTANT).last
        header = last_msg.locator(DATA_COLLAPSE_HEADER)
        if header.count() == 0:
            pytest.skip("No data collapse block in response")
        header.click()
        page.wait_for_timeout(500)
        return last_msg.locator(DATA_ROWS).count()
    return _expand


@pytest.fixture
def audit_api_client():
    """HTTP client for audit API queries."""
    import httpx
    client = httpx.Client(base_url=API_BASE_URL, timeout=30)
    yield client
    client.close()
