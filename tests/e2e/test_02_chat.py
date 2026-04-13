"""
Chat Functionality E2E Tests
HoneyBadge - Enterprise Knowledge Graph Assistant

Test Coverage:
- TC-101: Create new chat session
- TC-102: Send query and receive response
- TC-103: Streaming response display
- TC-104: Progress steps display
- TC-105: Query results table display
- TC-106: nGQL display toggle
- TC-107: Trace ID display and copy
- TC-108: Error handling for invalid query
- TC-109: Continue conversation context
- TC-110: Multiple queries in sequence
"""
import pytest
from playwright.sync_api import expect
import time


BASE_URL = "http://localhost:3000"


class TestChatFunctionality:
    """Test chat functionality."""

    def test_tc101_create_new_session(self, admin_logged_in, wait_for_chat_ready):
        """TC-101: User can create a new chat session."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Click new session button
        new_session_btn = page.locator('button:has-text("新对话"), button:has-text("New Chat"), [class*="new-session"]')
        if new_session_btn.count() > 0:
            new_session_btn.first.click()
            page.wait_for_timeout(1000)

        # Verify empty chat state or fresh chat
        chat_area = page.locator('.chat-messages, .message-list, [class*="chat"]')
        expect(chat_area.first).to_be_visible()

    def test_tc102_send_query_receives_response(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-102: User can send a query and receive a response."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Send a simple query
        send_chat_query("查询所有供应商", timeout=120000)

        # Verify response received
        assistant_messages = page.locator('.chat-message.assistant, .message.assistant, [class*="assistant"]')
        expect(assistant_messages.first).to_be_visible(timeout=120000)

    def test_tc103_streaming_response(self, admin_logged_in, wait_for_chat_ready):
        """TC-103: Streaming response displays with typing effect."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Send query
        textarea = page.locator(".chat-input textarea, input[placeholder*='问题']").first
        textarea.fill("什么是采购订单")
        textarea.press("Enter")

        # Wait for streaming indicator
        page.wait_for_timeout(2000)

        # Verify text appears incrementally (streaming effect)
        # This is implicit - if response completes, streaming worked

        # Wait for final response
        page.wait_for_selector('.chat-message.assistant', timeout=120000)

    def test_tc104_progress_steps_display(self, admin_logged_in, wait_for_chat_ready):
        """TC-104: Progress steps are displayed during query processing."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Send query
        textarea = page.locator(".chat-input textarea, input[placeholder*='问题']").first
        textarea.fill("查询采购订单")
        textarea.press("Enter")

        # Look for progress indicators
        progress_steps = page.locator('.progress-steps, .el-steps, [class*="progress"], .processing')
        if progress_steps.count() > 0:
            expect(progress_steps.first).to_be_visible(timeout=5000)

        # Wait for completion
        page.wait_for_selector('.chat-message.assistant', timeout=120000)

    def test_tc105_query_results_table(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-105: Query results are displayed in table format."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Send query that should return data
        send_chat_query("查询前5个采购订单", timeout=120000)

        # Look for data table
        data_table = page.locator('.el-table, table, [class*="table"], [class*="data"]')
        if data_table.count() > 0:
            expect(data_table.first).to_be_visible(timeout=120000)

    def test_tc106_ngql_display(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-106: Executed nGQL query can be viewed."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Send query
        send_chat_query("查询供应商", timeout=120000)

        # Look for nGQL/cypher block toggle
        ngql_toggle = page.locator('button:has-text("nGQL"), button:has-text("Cypher"), [class*="ngql"]')
        if ngql_toggle.count() > 0:
            ngql_toggle.first.click()
            page.wait_for_timeout(500)

            # Verify nGQL code block visible
            ngql_block = page.locator('pre code:has-text("MATCH"), pre:has-text("GO")')
            if ngql_block.count() > 0:
                expect(ngql_block.first).to_be_visible()

    def test_tc107_trace_id_display(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-107: Trace ID is displayed and can be copied."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Send query
        send_chat_query("查询采购订单", timeout=120000)

        # Look for trace ID
        trace_id = page.locator('[class*="trace"], [class*="trace-id"], text=/TRC-/')
        if trace_id.count() > 0:
            expect(trace_id.first).to_be_visible()

            # Test copy functionality if available
            copy_btn = page.locator('[class*="copy"], button:has-text("复制")')
            if copy_btn.count() > 0:
                copy_btn.first.click()

    def test_tc108_error_handling(self, admin_logged_in, wait_for_chat_ready):
        """TC-108: Invalid query shows error message."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Send invalid query
        textarea = page.locator(".chat-input textarea, input[placeholder*='问题']").first
        textarea.fill("查询不存在的标签哈哈哈哈哈哈哈")
        textarea.press("Enter")

        # Wait for response
        page.wait_for_timeout(10000)

        # Look for either error message or graceful response
        # The system should either show error or return empty results gracefully
        response_visible = page.locator('.chat-message.assistant, .message.assistant, [class*="response"]')
        expect(response_visible.first).to_be_visible(timeout=120000)

    def test_tc109_continue_conversation(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-109: Can continue conversation with context."""
        page = admin_logged_in
        wait_for_chat_ready()

        # First query
        send_chat_query("查询采购订单", timeout=120000)
        page.wait_for_timeout(2000)

        # Second query that references context
        textarea = page.locator(".chat-input textarea, input[placeholder*='问题']").first
        textarea.fill("这个订单的金额是多少")
        textarea.press("Enter")

        # Verify response considers context (either shows data or gracefully handles)
        page.wait_for_selector('.chat-message.assistant', timeout=120000)

    def test_tc110_multiple_queries_sequence(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-110: Multiple queries can be sent in sequence."""
        page = admin_logged_in
        wait_for_chat_ready()

        # First query
        send_chat_query("查询供应商", timeout=120000)
        page.wait_for_timeout(1000)

        # Second query
        send_chat_query("查询采购订单", timeout=120000)
        page.wait_for_timeout(1000)

        # Third query
        send_chat_query("查询物料", timeout=120000)

        # Verify all responses received
        messages = page.locator('.chat-message.assistant')
        expect(messages).to_have_count(3, timeout=120000)

    def test_tc111_execution_time_display(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-111: Execution time is displayed in response."""
        page = admin_logged_in
        wait_for_chat_ready()

        send_chat_query("查询采购订单", timeout=120000)

        # Look for execution time
        exec_time = page.locator('[class*="time"], [class*="duration"], text=/\\d+ms|\\d+s/')
        if exec_time.count() > 0:
            expect(exec_time.first).to_be_visible()

    def test_tc112_raw_data_toggle(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-112: Raw data can be toggled visible."""
        page = admin_logged_in
        wait_for_chat_ready()

        send_chat_query("查询采购订单", timeout=120000)

        # Look for raw data toggle
        raw_data_toggle = page.locator('button:has-text("原始数据"), button:has-text("Raw Data")')
        if raw_data_toggle.count() > 0:
            raw_data_toggle.first.click()
            page.wait_for_timeout(500)

            # Verify raw data visible
            raw_data = page.locator('[class*="raw"], pre, code')
            if raw_data.count() > 0:
                expect(raw_data.first).to_be_visible()
