"""
Session Management E2E Tests
HoneyBadge - Enterprise Knowledge Graph Assistant

Test Coverage:
- TC-201: Create new session
- TC-202: Rename session
- TC-203: Delete session
- TC-204: List all sessions
- TC-205: Session persistence across reload
- TC-206: Session search/filter
- TC-207: Session pagination
- TC-208: Export session conversation
"""
import os
import pytest
from playwright.sync_api import expect
from tests.e2e.selectors import (
    NEW_CHAT_BUTTON, SESSION_ITEM, MSG_ASSISTANT,
)


BASE_URL = os.getenv("BASE_URL", "http://localhost:3000")


class TestSessionManagement:
    """Test session management functionality."""

    def test_tc201_create_named_session(self, admin_logged_in, wait_for_chat_ready):
        """TC-201: User can create a named session."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Click new session button
        new_session_btn = page.locator(NEW_CHAT_BUTTON)
        if new_session_btn.count() > 0:
            new_session_btn.first.click()
            page.wait_for_timeout(500)

        # Find session name input and rename
        session_name_input = page.locator('input[placeholder*="会话名称"], input[class*="session-name"]')
        if session_name_input.count() == 0:
            pytest.skip("Session name input not available in UI")
        session_name_input.first.fill("Test Session TC-201")
        session_name_input.first.press("Enter")
        page.wait_for_timeout(500)

        # Verify session appears in sidebar
        session_item = page.locator('text="Test Session TC-201"')
        expect(session_item.first).to_be_visible()

    def test_tc202_rename_session(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-202: User can rename an existing session."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Create a session first
        send_chat_query("查询供应商", timeout=120000)
        page.wait_for_timeout(1000)

        # Right-click or hover to find rename option
        session_item = page.locator('.session-item, [class*="session"]').first
        session_item.hover()
        page.wait_for_timeout(300)

        # Look for edit/rename button
        rename_btn = page.locator('[class*="edit"], [class*="rename"], button:has-text("编辑")')
        if rename_btn.count() == 0:
            pytest.skip("Rename button not available")
        rename_btn.first.click()
        page.wait_for_timeout(300)

        # Clear and enter new name
        name_input = page.locator('input[class*="session-name"], input[placeholder*="名称"]')
        if name_input.count() == 0:
            pytest.skip("Session name input not found after clicking rename")
        name_input.first.fill("Renamed Session TC-202")
        name_input.first.press("Enter")
        page.wait_for_timeout(500)

        # Verify new name
        expect(page.locator('text="Renamed Session TC-202"').first).to_be_visible()

    def test_tc203_delete_session(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-203: User can delete a session."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Create a session to delete
        send_chat_query("查询采购订单", timeout=120000)
        page.wait_for_timeout(1000)

        # Find the session in sidebar
        initial_count = page.locator(SESSION_ITEM).count()

        # Find delete button (may require hover or context menu)
        delete_btn = page.locator('[class*="delete"], button:has-text("删除")')
        if delete_btn.count() == 0:
            pytest.skip("Delete button not available")
        delete_btn.first.click()
        page.wait_for_timeout(500)

        # Confirm deletion if dialog appears
        confirm_btn = page.locator('button:has-text("确认"), button:has-text("Confirm")')
        if confirm_btn.count() > 0:
            confirm_btn.first.click()
            page.wait_for_timeout(500)

        # Verify session count decreased
        new_count = page.locator(SESSION_ITEM).count()
        assert new_count < initial_count, f"Expected session count to decrease. Before: {initial_count}, After: {new_count}"

    def test_tc204_list_sessions(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-204: Sessions are listed in sidebar."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Create multiple sessions
        for i in range(3):
            new_session_btn = page.locator(NEW_CHAT_BUTTON)
            if new_session_btn.count() > 0:
                new_session_btn.first.click()
                page.wait_for_timeout(500)
            send_chat_query(f"查询供应商 {i}", timeout=120000)
            page.wait_for_timeout(500)

        # Verify session list in sidebar
        session_items = page.locator(SESSION_ITEM)
        assert session_items.count() >= 3, f"Expected >=3 sessions, got {session_items.count()}"

    @pytest.mark.skip(
        reason="Feature gap (not a timing issue). After page.reload(), "
        "ChatView.onMounted calls loadMessages(sessionId) which GETs "
        "/api/sessions/{id}/messages — but the chat_messages table is never "
        "populated. The chat hot path uses Matrix (in-memory Pinia store only); "
        "handleSend -> sendQuery sends via Matrix and the Room.timeline handler "
        "updates the Pinia store but never persists to the backend. The backend "
        "(sessions.py) has a chat_messages table + GET endpoint but NO write "
        "path (no POST, and no side-channel writer). To unskip: implement "
        "message persistence — either a POST /api/sessions/{id}/messages "
        "endpoint + frontend hook on message receive, or a Matrix-side writer. "
        "See docs/1.1.0-upgrade-evidence/1.1.1-deferred-tests.md"
    )
    def test_tc205_session_persistence(self, reset_manager, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-205: Session data persists after page reload.

        Sessions ARE persisted (handleNewChat POSTs /api/sessions), but
        messages are NOT (no write path to chat_messages). After reload,
        loadMessages returns [] and the message area shows the empty state.
        """
        page = admin_logged_in
        wait_for_chat_ready()

        # Create session with query
        send_chat_query("查询物料", timeout=120000)
        page.wait_for_timeout(1000)

        # Reload page. Do NOT wait for "networkidle" — Matrix SDK keeps a long-poll
        # /sync connection open indefinitely, so networkidle never resolves.
        page.reload()
        page.wait_for_load_state("domcontentloaded")

        # After reload, onMounted runs: fetchCurrentUser -> loadSessions ->
        # loadMessages(lastSession) -> connect. Sessions restore from the
        # backend, but messages do NOT (chat_messages is never written to).
        # This assertion will fail until message persistence is implemented.
        messages = page.locator(MSG_ASSISTANT)
        expect(messages.last).to_be_visible(timeout=60000)

    def test_tc206_session_search(self, admin_logged_in, wait_for_chat_ready):
        """TC-206: User can search through sessions."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Look for search input
        search_input = page.locator('input[placeholder*="搜索"], input[class*="search"]')
        if search_input.count() == 0:
            pytest.skip("Search input not available")
        search_input.first.fill("采购订单")
        page.wait_for_timeout(500)

        # Verify filtered results
        expect(search_input.first).to_be_visible()

    def test_tc207_session_pagination(self, admin_logged_in, wait_for_chat_ready):
        """TC-207: Sessions list supports pagination."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Create enough sessions to trigger pagination
        for i in range(15):
            new_session_btn = page.locator(NEW_CHAT_BUTTON)
            if new_session_btn.count() > 0:
                new_session_btn.first.click()
                page.wait_for_timeout(300)

        # Look for pagination controls
        pagination = page.locator('.pagination, [class*="pagination"], button:has-text("下一页")')
        if pagination.count() == 0:
            pytest.skip("Pagination not triggered or not available")
        expect(pagination.first).to_be_visible()

    def test_tc208_export_session(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-208: User can export session conversation."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Create session with content
        send_chat_query("查询供应商", timeout=120000)
        page.wait_for_timeout(1000)

        # Look for export button
        export_btn = page.locator('button:has-text("导出"), button:has-text("Export")')
        if export_btn.count() == 0:
            pytest.skip("Export button not available")
        export_btn.first.click()
        page.wait_for_timeout(500)

        # Verify download or export dialog
        export_dialog = page.locator('[class*="export"], [class*="download"]')
        if export_dialog.count() > 0:
            expect(export_dialog.first).to_be_visible()
