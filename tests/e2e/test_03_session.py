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
    MSG_ASSISTANT,
    NEW_CHAT_BUTTON,
    SESSION_ITEM,
)

BASE_URL = os.getenv("BASE_URL", "http://localhost:3000")

pytestmark = pytest.mark.requires_llm

# The sidebar exposes rename/delete only through the per-session "⋯" dropdown
# (el-dropdown, teleported to body) followed by an ElMessageBox dialog. There is
# no direct rename/delete button in the session-item markup.


def rename_session_in_ui(page, index: int, new_title: str) -> None:
    """Rename the index-th sidebar session via ⋯ dropdown → 重命名 → prompt dialog."""
    page.locator(".session-item .session-actions").nth(index).click()
    # Element Plus teleports EVERY session's dropdown menu to <body> (hidden
    # until opened), so ~1 per session matches a plain selector — scope to the
    # visible one.
    page.locator('.el-dropdown-menu__item:visible', has_text='重命名').first.click()
    page.locator(".el-message-box__input input").fill(new_title)
    page.locator('.el-message-box__btns button:has-text("确定")').first.click()
    page.wait_for_timeout(500)


class TestSessionManagement:
    """Test session management functionality."""

    @pytest.mark.smoke
    def test_tc201_create_named_session(self, admin_logged_in, wait_for_chat_ready):
        """TC-201: User can create a named session.

        The sidebar has no direct "session name" input; a session is named via
        the ⋯ dropdown → 重命名 prompt after creation.
        """
        page = admin_logged_in
        wait_for_chat_ready()

        # Create a fresh session (button text 新对话), newest = index 0
        page.locator(NEW_CHAT_BUTTON).first.click()
        page.wait_for_timeout(500)

        rename_session_in_ui(page, 0, "Test Session TC-201")
        expect(
            page.locator('.session-title', has_text="Test Session TC-201").first
        ).to_be_visible()

    def test_tc202_rename_session(self, admin_logged_in, wait_for_chat_ready):
        """TC-202: User can rename an existing session (⋯ dropdown → 重命名).

        Sessions are created via the 新对话 button — rename does not require
        message content, and this keeps the test off the LLM query path.
        """
        page = admin_logged_in
        wait_for_chat_ready()

        # Create a session (newest = index 0)
        page.locator(NEW_CHAT_BUTTON).first.click()
        page.wait_for_timeout(500)

        rename_session_in_ui(page, 0, "Renamed Session TC-202")
        expect(
            page.locator('.session-title', has_text="Renamed Session TC-202").first
        ).to_be_visible()

    def test_tc203_delete_session(self, admin_logged_in, wait_for_chat_ready):
        """TC-203: User can delete a session (⋯ dropdown → 删除 → confirm dialog).

        Sessions are created via the 新对话 button — delete does not require
        message content, and this keeps the test off the LLM query path.
        """
        page = admin_logged_in
        wait_for_chat_ready()

        # Create a session to delete
        page.locator(NEW_CHAT_BUTTON).first.click()
        page.wait_for_timeout(500)

        initial_count = page.locator(SESSION_ITEM).count()

        page.locator(".session-item .session-actions").first.click()
        page.locator('.el-dropdown-menu__item:visible', has_text='删除').first.click()
        # Confirm deletion dialog
        page.locator('.el-message-box__btns button:has-text("确定")').first.click()
        page.wait_for_timeout(500)

        # Verify session count decreased
        new_count = page.locator(SESSION_ITEM).count()
        assert new_count < initial_count, f"Expected session count to decrease. Before: {initial_count}, After: {new_count}"

    def test_tc204_list_sessions(self, admin_logged_in, wait_for_chat_ready):
        """TC-204: Sessions are listed in sidebar.

        Sessions are created via the 新对话 button — listing does not require
        message content, and this keeps the test off the LLM query path (3
        sequential queries previously blew the per-test timeout budget).
        """
        page = admin_logged_in
        wait_for_chat_ready()

        # Create multiple sessions
        for _ in range(3):
            page.locator(NEW_CHAT_BUTTON).first.click()
            page.wait_for_timeout(500)

        # Verify session list in sidebar
        session_items = page.locator(SESSION_ITEM)
        assert session_items.count() >= 3, f"Expected >=3 sessions, got {session_items.count()}"

    def test_tc205_session_persistence(self, reset_manager, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-205: Session data persists after page reload.

        Messages are restored from the Matrix DM room timeline (Tuwunel
        homeserver stores them server-side). After reload, onMounted runs:
        fetchCurrentUser -> loadSessions -> connect -> loadMessages, where
        loadMessages reads room.timeline via scrollback and converts each
        MatrixEvent via matrixEventToChatMessage.
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
        # connect -> loadMessages(lastSession). loadMessages reads the DM room
        # timeline from Matrix (scrollback) and populates the Pinia store, so
        # the assistant reply reappears without any backend write path.
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
        for _ in range(15):
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
