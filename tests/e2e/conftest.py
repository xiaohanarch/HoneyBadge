"""
Playwright E2E Test Configuration and Fixtures
HoneyBadge - Enterprise Knowledge Graph Assistant
"""
import datetime
import json
import os
import re
import subprocess
import time
import pytest
from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext
from tests.e2e.selectors import (
    LOGIN_USERNAME, LOGIN_PASSWORD, LOGIN_BUTTON,
    CHAT_TEXTAREA, MSG_ASSISTANT, MSG_USER, MESSAGES_CONTAINER,
    TRACE_ID_LINK, CYPHER_COLLAPSE_HEADER, CYPHER_CODE,
    DATA_COLLAPSE_HEADER, DATA_ROWS, DATA_TABLE,
    NEW_CHAT_BUTTON, SESSION_ITEM, INPUT_CONTAINER,
)

MANAGER_CONTAINER = "honeybadge-hiclaw-manager"
SESSION_DIR = "/root/manager-workspace/.openclaw/agents/main/sessions"


def reset_manager_sessions():
    """Clear all Manager OpenClaw sessions and restart the container.

    The Manager LLM (glm-5.2) enters repetition loops after 5-10 queries in
    the same session.  E2E permission tests send 20+ queries to the same DM
    rooms, accumulating context that triggers the loop.  This function:
      1. Deletes all session transcript files (*.jsonl)
      2. Resets sessions.json to an empty store
      3. Restarts the Manager container so in-memory session caches are freed
      4. Waits for the OpenClaw process to come back up

    Call this between tests that would otherwise inherit a bloated session.
    """
    # 1. Delete session transcript files
    subprocess.run(
        ["docker", "exec", MANAGER_CONTAINER, "bash", "-c",
         f"rm -f {SESSION_DIR}/*.jsonl"],
        capture_output=True, timeout=10,
    )

    # 2. Reset sessions.json to empty
    subprocess.run(
        ["docker", "exec", MANAGER_CONTAINER, "bash", "-c",
         f'echo "{{}}" > {SESSION_DIR}/sessions.json'],
        capture_output=True, timeout=10,
    )

    # 3. Restart the Manager container
    subprocess.run(
        ["docker", "restart", MANAGER_CONTAINER],
        capture_output=True, timeout=30,
    )

    # 4. Wait for the OpenClaw process to be running
    for _ in range(30):
        result = subprocess.run(
            ["docker", "exec", MANAGER_CONTAINER, "pgrep", "-f", "openclaw"],
            capture_output=True, timeout=5,
        )
        if result.returncode == 0:
            break
        time.sleep(1)
    else:
        print("[reset_manager_sessions] WARNING: Manager process not detected after 30s")

    # 5. Wait for the Matrix client to connect to the homeserver.
    #    The Manager takes ~22s after restart to join rooms and connect to
    #    the gateway.  Without this wait, the first query after restart may
    #    time out because the Matrix message isn't delivered.
    #    We use a fixed wait because docker logs --tail=N only shows the last
    #    N lines, which may not include the startup "connected to gateway" msg.
    time.sleep(25)


def _wait_for_textarea_enabled(page_obj, timeout=60000):
    """Wait for chat textarea to be visible and enabled."""
    page_obj.wait_for_function(
        """() => {
            const ta = document.querySelector('.input-container .el-textarea__inner');
            return ta && !ta.disabled;
        }""",
        timeout=timeout,
    )


def _wait_for_current_session(page_obj, timeout=30000):
    """Wait until the chat store has a non-null currentSessionId.

    Without this, addMessage / prepareAssistantMessage / finalizeAssistantMessage
    in stores/chat.ts silently no-op because they early-return when
    currentSessionId is null. This causes test queries to send (Manager replies
    correctly) but the frontend never renders any message.
    """
    page_obj.wait_for_function(
        """() => {
            try {
                const app = document.querySelector('#app').__vue_app__;
                const store = app.config.globalProperties.$pinia._s.get('chat');
                return !!store && !!store.currentSessionId;
            } catch (e) {
                return false;
            }
        }""",
        timeout=timeout,
    )


def _wait_for_msg_count_stable(page_obj, stable_ms=3000, timeout_ms=30000):
    """Wait for the assistant message count to be stable for `stable_ms` milliseconds.

    matrix-js-sdk backfills DM room history asynchronously after login. Old
    contract-002 messages from previous test runs can appear in the DOM *after*
    ``existing_count`` is captured, making the settle wait mistake them for new
    messages. This function waits until the count stops changing for 3 seconds,
    ensuring ``existing_count`` includes all backfilled messages.

    Special case: when the count is 0, the stability window is extended to 10s.
    A count of 0 that has been stable for 3s often means the Matrix initial sync
    hasn't started delivering backfilled messages yet — not that the room is
    genuinely empty. Waiting 10s gives the sync enough time to begin delivering
    messages, at which point the count changes and the normal 3s window applies.

    Returns the stable message count (or the current count on timeout).
    """
    page_obj.evaluate("() => { window.__hbStableCount = undefined; window.__hbStableTs = 0; window.__hbStableStart = Date.now(); }")
    try:
        page_obj.wait_for_function(
            f"""() => {{
                const count = document.querySelectorAll('.chat-message.message-assistant').length;
                const now = Date.now();
                if (window.__hbStableCount !== count) {{
                    window.__hbStableCount = count;
                    window.__hbStableTs = now;
                    return false;
                }}
                // When count is 0, require 5s stability — Matrix sync may
                // not have started delivering backfilled messages yet.  Trace_id
                // filtering in the settle condition handles late backfill.
                const requiredMs = count === 0 ? 5000 : {stable_ms};
                return (now - window.__hbStableTs) >= requiredMs;
            }}""",
            timeout=timeout_ms,
            polling=500,
        )
    except Exception:
        pass  # proceed with whatever count we have
    return page_obj.locator(MSG_ASSISTANT).count()


def _wait_for_response_settled(page_obj, existing_count: int, timeout_ms: int = 120000,
                               min_wait_ms: int = 5000, query_send_ts: int = 0):
    """Stage-2 wait: settle on the actual response, not Manager's dispatch ack/preamble.

    Waits up to `timeout_ms` for ANY of:
      1. Structured worker reply (cypher-collapse or data-collapse header in a new message)
         — only after `min_wait_ms` AND only if the message's trace_id timestamp is
           >= ``query_send_ts`` (or has no trace_id).  This is the primary defense
           against stale DM history: matrix-js-sdk backfills old contract-002 messages
           from previous test runs, and they carry trace_ids with timestamps BEFORE
           the current query was sent.  By parsing the trace_id's embedded timestamp
           (format: TRC-YYYYMMDD-HHMMSS-xxxxx), we reliably distinguish stale from new.
      2. Denial marker text (权限不足/permission denied/无权/Forbidden/access denied)
         — always immediate so permission tests fail fast.
      3. Last new-message body length (>100 chars) stable for 10000ms (streaming finished)
         — only after `min_wait_ms` AND only if the last message's trace_id timestamp
           is >= ``query_send_ts`` (or has no trace_id).

    Exits silently on timeout — callers must let the test assertion fail naturally.
    Debug info is printed to stdout via ``[SETTLE]`` prefix.
    """
    page_obj.evaluate(
        f"() => {{ window.__hbStability = null; window.__hbSettleReason = ''; "
        f"window.__hbSettleStart = Date.now(); "
        f"window.__hbQuerySendTs = {query_send_ts}; }}"
    )
    try:
        page_obj.wait_for_function(
            f"""() => {{
                const msgs = document.querySelectorAll('.chat-message.message-assistant');
                if (msgs.length <= {existing_count}) return false;

                const elapsed = Date.now() - (window.__hbSettleStart || 0);
                const querySendTs = window.__hbQuerySendTs || 0;

                // Parse trace_id timestamp: TRC-YYYYMMDD-HHMMSS-xxxxx → epoch ms
                function parseTraceTs(elem) {{
                    var link = elem.querySelector('.trace-id-link');
                    if (!link) return -1;  // no trace_id — treat as new
                    var m = (link.textContent || '').match(/TRC-(\\d{{4}})(\\d{{2}})(\\d{{2}})-(\\d{{2}})(\\d{{2}})(\\d{{2}})/);
                    if (!m) return -1;
                    return new Date(+m[1], +m[2]-1, +m[3], +m[4], +m[5], +m[6]).getTime();
                }}

                function isStale(elem) {{
                    if (!querySendTs) return false;  // no query_ts — don't filter
                    var ts = parseTraceTs(elem);
                    return ts > 0 && ts < querySendTs;
                }}

                // 1: structured worker contract-002 (cypher/data collapse)
                //    Gated by min_wait_ms AND trace_id timestamp check.
                if (elapsed >= {min_wait_ms}) {{
                    for (let i = {existing_count}; i < msgs.length; i++) {{
                        const m = msgs[i];
                        if (m.querySelector('.data-collapse .el-collapse-item__header') ||
                            m.querySelector('.cypher-collapse .el-collapse-item__header')) {{
                            if (isStale(m)) continue;  // stale backfill — keep waiting
                            window.__hbSettleReason = 'cond1_structured idx=' + i + ' total=' + msgs.length + ' existing=' + {existing_count};
                            return true;
                        }}
                    }}
                }}

                // 2: denial markers (permission tests fail fast — no min_wait)
                const denial = /权限不足|permission denied|无权|forbidden|access denied/i;
                for (let i = {existing_count}; i < msgs.length; i++) {{
                    if (isStale(msgs[i])) continue;
                    const body = msgs[i].querySelector('.message-body') || msgs[i];
                    if (denial.test(body.textContent)) {{
                        window.__hbSettleReason = 'cond2_denial idx=' + i;
                        return true;
                    }}
                }}

                // 3: streaming stable — last new-message body length unchanged
                //    for 10s.  Only fires if text > 100 chars AND min_wait_ms
                //    has elapsed AND last message is NOT stale.
                if (elapsed >= {min_wait_ms}) {{
                    const last = msgs[msgs.length - 1];
                    if (isStale(last)) return false;  // last message is stale — keep waiting
                    const body = last.querySelector('.message-body') || last;
                    const len = body ? body.textContent.trim().length : 0;
                    if (len < 100) return false;
                    const now = Date.now();
                    if (!window.__hbStability || window.__hbStability.len !== len) {{
                        window.__hbStability = {{ len: len, ts: now }};
                        return false;
                    }}
                    if ((now - window.__hbStability.ts) >= 10000) {{
                        window.__hbSettleReason = 'cond3_stable len=' + len + ' elapsed=' + elapsed;
                        return true;
                    }}
                }}

                return false;
            }}""",
            timeout=timeout_ms,
            polling=200,
        )
        reason = page_obj.evaluate("() => window.__hbSettleReason || 'unknown'")
        print(f"[SETTLE] exited: {reason}")
    except Exception as e:
        print(f"[SETTLE] exception after {timeout_ms}ms: {type(e).__name__}: {str(e)[:200]}")


def _wait_for_new_response(page_obj, existing_count: int, timeout: int = 120000,
                            settle_timeout_ms: int = 240000,
                            min_wait_ms: int = 5000, query_send_ts: int = 0):
    """Wait for the assistant's actual response (not the Manager dispatch ack/preamble).

    Two-stage wait:
      Stage 1: any NEW assistant message with body text >10 chars (existing semantics)
      Stage 2: response settled — Worker contract-002, denial marker, or text stable

    Stage 2 runs for up to `settle_timeout_ms` (120s default for glm-5.2);
    pass `settle_timeout_ms=0` to skip it (legacy callers that only need the
    first-message signal).
    `min_wait_ms` gates conditions 1 and 3 in Stage 2 to skip stale DM history.
    `query_send_ts` is the Unix timestamp (ms) when the query was sent; cond1
    and cond3 use it to parse trace_id timestamps and skip stale backfilled
    messages whose trace_id was generated before the query.
    """
    # Stage 1 timeout: use at least 240s.  After reset_manager restarts the
    # Manager, it reprocesses backfilled DM messages for 60-90s before getting
    # to the new query.  With glm-5.2 at ~30-60s per LLM step, total time from
    # query to first response can be 2-3 minutes.
    stage1_timeout = max(timeout, 240000)
    page_obj.wait_for_function(
        f"""() => {{
            const msgs = document.querySelectorAll('.chat-message.message-assistant');
            if (msgs.length <= {existing_count}) return false;
            const last = msgs[msgs.length - 1];
            const body = last.querySelector('.message-body') || last;
            return body && body.textContent.trim().length > 10;
        }}""",
        timeout=stage1_timeout,
    )
    if settle_timeout_ms > 0:
        _wait_for_response_settled(page_obj, existing_count, timeout_ms=settle_timeout_ms,
                                   min_wait_ms=min_wait_ms,
                                   query_send_ts=query_send_ts)
    page_obj.wait_for_timeout(200)


def send_query_on_page(page_obj, query: str, timeout: int = 120000):
    """Send a chat query on any page object (standalone helper, not fixture-bound)."""
    _wait_for_textarea_enabled(page_obj, timeout=timeout)
    textarea = page_obj.locator(CHAT_TEXTAREA).first
    existing_count = _wait_for_msg_count_stable(page_obj)
    query_send_ts = int(time.time() * 1000)
    textarea.fill(query)
    textarea.press("Enter")
    _wait_for_new_response(page_obj, existing_count, timeout=timeout,
                           query_send_ts=query_send_ts)


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
        # --disable-web-security disables CORS enforcement so the frontend
        # (localhost:3000) can reach the Matrix homeserver (localhost:7167 via SSH tunnel).
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-web-security", "--allow-running-insecure-content"],
        )
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

    # Patch Matrix homeserver URL so the local Playwright browser uses the SSH tunnel
    # (port 7167 forwarded locally) instead of the blocked external NodePort 30167.
    matrix_local = os.getenv("MATRIX_HOMESERVER_LOCAL", "http://localhost:7167")

    def _patch_login(route):
        response = route.fetch()
        try:
            body = response.json()
            if "matrix_homeserver" in body:
                body["matrix_homeserver"] = matrix_local
            route.fulfill(
                status=response.status,
                content_type="application/json",
                body=json.dumps(body),
            )
        except Exception:
            route.fulfill(response=response)

    page.route("**/login", _patch_login)

    # Debug: log requests to matrix/7167 to verify connectivity
    page.on("request", lambda req: print(f"[NET] {req.method} {req.url[:80]}") if any(x in req.url for x in ["7167", "30167", "matrix", "_matrix"]) else None)
    page.on("console", lambda msg: print(f"[CON] {msg.type}: {msg.text[:120]}") if msg.type in ("error", "warning") else None)

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
        # Start a new chat session so existing_count begins at 0 (avoids reading stale historical messages)
        new_session_btn = page.locator(NEW_CHAT_BUTTON)
        if new_session_btn.count() > 0 and new_session_btn.first.is_visible():
            new_session_btn.first.click()
            _wait_for_textarea_enabled(page, timeout=15000)
        # Race-guard: chat store's addMessage/prepareAssistantMessage/finalizeAssistantMessage
        # silently no-op until currentSessionId is set. Wait for it to settle.
        _wait_for_current_session(page, timeout=30000)
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
def reset_manager():
    """Reset Manager OpenClaw sessions before the test.

    Clears all session transcript files and restarts the Manager container
    so the LLM starts with a clean context.  Use this fixture in permission
    tests that send many queries to the same DM room — glm-5.2 enters
    repetition loops after 5-10 accumulated turns.

    Usage: add ``reset_manager`` as a parameter to the test method.
    The fixture runs before the test body (and before page/admin_logged_in
    fixtures that depend on it).
    """
    reset_manager_sessions()


@pytest.fixture
def send_chat_query(page: Page):
    """Factory fixture to send a chat query and wait for response."""
    def _send(query: str, timeout: int = 120000):
        _wait_for_textarea_enabled(page, timeout=timeout)
        textarea = page.locator(CHAT_TEXTAREA).first
        existing_count = _wait_for_msg_count_stable(page)
        query_send_ts = int(time.time() * 1000)
        textarea.fill(query)
        textarea.press("Enter")
        _wait_for_new_response(page, existing_count, timeout=timeout,
                               query_send_ts=query_send_ts)
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
        _wait_for_current_session(p, timeout=30000)

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
    def _send(query: str, timeout: int = 120000):
        _wait_for_textarea_enabled(page, timeout=timeout)
        textarea = page.locator(CHAT_TEXTAREA).first
        existing_count = _wait_for_msg_count_stable(page)
        query_send_ts = int(time.time() * 1000)
        textarea.fill(query)
        textarea.press("Enter")
        # _wait_for_new_response now waits past the Manager dispatch ack: it returns
        # only after the response has settled (structured worker reply, denial marker,
        # or stable text length). No separate 120s wait needed here.
        _wait_for_new_response(page, existing_count, timeout=timeout,
                               query_send_ts=query_send_ts)

        all_msgs = page.locator(MSG_ASSISTANT)
        total = all_msgs.count()
        # The Manager sends a plain-text dispatch acknowledgement first (fills the
        # placeholder at index `existing_count`), then the Worker's contract 002
        # arrives as a subsequent message carrying the actual data table / cypher.
        # Scan the NEW messages (from existing_count to end) and pick the one
        # that actually contains structured-data UI AND has a trace_id whose
        # embedded timestamp is >= query_send_ts (i.e. not stale backfill).
        # Fall back to the last message.
        data_msg = None
        for i in range(existing_count, total):
            candidate = all_msgs.nth(i)
            if candidate.locator(DATA_COLLAPSE_HEADER).count() > 0 \
               or candidate.locator(CYPHER_COLLAPSE_HEADER).count() > 0:
                # Skip stale messages whose trace_id timestamp predates the query
                trace_link = candidate.locator(TRACE_ID_LINK)
                if trace_link.count() > 0:
                    trace_text = trace_link.first.inner_text()
                    trace_match = re.search(r'TRC-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})', trace_text)
                    if trace_match:
                        y, mo, d, h, mi, s = (int(x) for x in trace_match.groups())
                        trace_ts = int(datetime.datetime(y, mo, d, h, mi, s).timestamp() * 1000)
                        if trace_ts < query_send_ts:
                            continue  # Stale backfilled message — keep scanning
                data_msg = candidate
                break
        if data_msg is None:
            data_msg = all_msgs.last

        text = data_msg.inner_text()

        trace_id = None
        trace_link = data_msg.locator(TRACE_ID_LINK)
        if trace_link.count() > 0:
            trace_text = trace_link.first.inner_text()
            match = re.search(r'TRC-[\w-]+', trace_text)
            if match:
                trace_id = match.group(0)

        has_cypher = data_msg.locator(CYPHER_COLLAPSE_HEADER).count() > 0
        has_data_table = data_msg.locator(DATA_COLLAPSE_HEADER).count() > 0

        data_row_count = 0
        if has_data_table:
            data_msg.locator(DATA_COLLAPSE_HEADER).click()
            page.wait_for_timeout(500)
            data_row_count = data_msg.locator(DATA_ROWS).count()

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
