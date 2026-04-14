"""
Playwright E2E Test Configuration and Fixtures
HoneyBadge - Enterprise Knowledge Graph Assistant
"""
import os
import pytest
from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext


def _wait_for_textarea_enabled(page_obj, timeout=60000):
    """Wait for chat textarea to be visible and enabled."""
    page_obj.wait_for_function(
        """() => {
            const ta = document.querySelector('.el-textarea textarea, .chat-input textarea');
            return ta && !ta.disabled;
        }""",
        timeout=timeout,
    )


def send_query_on_page(page_obj, query: str, timeout: int = 60000):
    """Send a chat query on any page object (standalone helper, not fixture-bound)."""
    _wait_for_textarea_enabled(page_obj, timeout=timeout)
    textarea = page_obj.locator(".el-textarea textarea, .chat-input textarea").first
    textarea.fill(query)
    textarea.press("Enter")
    page_obj.wait_for_selector(".chat-message, .message", timeout=timeout)
    page_obj.wait_for_timeout(3000)


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
        page.wait_for_selector('.el-input', timeout=15000)
        page.fill('input[placeholder="用户名"]', username)
        page.fill('input[placeholder="密码"]', password)
        page.click('button:has-text("登 录")')
        page.wait_for_url(f"{BASE_URL}/chat", timeout=30000)
        page.wait_for_timeout(2000)  # Wait for Matrix connection
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
        page.wait_for_selector(".el-textarea textarea, .chat-input textarea", timeout=15000)
        page.wait_for_timeout(2000)  # Wait for Matrix to connect
    return _wait


@pytest.fixture
def send_chat_query(page: Page):
    """Factory fixture to send a chat query."""
    def _send(query: str, timeout: int = 60000):
        # Wait for textarea to be enabled (may be disabled during LLM response)
        _wait_for_textarea_enabled(page, timeout=timeout)
        textarea = page.locator(".el-textarea textarea, .chat-input textarea").first
        textarea.fill(query)
        textarea.press("Enter")
        # Wait for response to appear
        page.wait_for_selector(".chat-message, .message", timeout=timeout)
        page.wait_for_timeout(3000)  # Wait for response to render
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
        p.wait_for_selector('.el-input', timeout=15000)
        p.fill('input[placeholder="用户名"]', username)
        p.fill('input[placeholder="密码"]', password)
        p.click('button:has-text("登 录")')
        p.wait_for_url(f"{BASE_URL}/chat", timeout=30000)
        p.wait_for_timeout(2000)

        # Create a new session if none exists
        new_session_btn = p.locator('button:has-text("新对话"), button:has-text("New Chat")')
        if new_session_btn.count() > 0 and new_session_btn.first.is_visible():
            new_session_btn.first.click()
            p.wait_for_timeout(1000)

        pages.append(p)
        contexts.append(context)
        return p

    yield _create
    for p in pages:
        p.close()
    for c in contexts:
        c.close()
