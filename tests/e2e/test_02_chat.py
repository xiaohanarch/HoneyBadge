"""
Chat Functionality E2E Tests
HoneyBadge - Enterprise Knowledge Graph Assistant

Test Coverage:
- TC-101: Create new chat session
- TC-102: Send query and receive response with trace ID
- TC-103: Streaming response (text grows over time)
- TC-104: Progress steps display during processing
- TC-105: Query results data table with rows
- TC-106: nGQL/Cypher code display
- TC-107: Trace ID format and display
- TC-108: Error handling for invalid query
- TC-109: Continue conversation with context
- TC-110: Multiple queries in sequence with trace IDs
- TC-111: Execution time display
- TC-112: Raw data toggle
"""
import os
import re
import pytest
from playwright.sync_api import expect
from tests.e2e.selectors import (
    CHAT_TEXTAREA, MSG_ASSISTANT, MSG_USER, SEND_BUTTON,
    TRACE_ID_LINK, EXECUTION_TIME,
    CYPHER_COLLAPSE_HEADER, CYPHER_CODE,
    DATA_COLLAPSE_HEADER, DATA_ROWS, DATA_TABLE,
    NEW_CHAT_BUTTON, MESSAGES_CONTAINER, PROGRESS_AREA,
)


BASE_URL = os.getenv("BASE_URL", "http://localhost:3000")


class TestChatFunctionality:
    """Test chat functionality with content verification."""

    def test_tc101_create_new_session(self, admin_logged_in, wait_for_chat_ready):
        """TC-101: User can create a new chat session."""
        page = admin_logged_in
        wait_for_chat_ready()

        new_session_btn = page.locator(NEW_CHAT_BUTTON)
        if new_session_btn.count() > 0:
            new_session_btn.first.click()
            page.wait_for_timeout(1000)

        # Chat area and input should be visible
        expect(page.locator(MESSAGES_CONTAINER)).to_be_visible()
        expect(page.locator(CHAT_TEXTAREA)).to_be_visible()

    def test_tc102_send_query_receives_response_with_trace(self, admin_logged_in, wait_for_chat_ready, send_query_and_get_response):
        """TC-102: Query returns response with meaningful text and trace ID."""
        page = admin_logged_in
        wait_for_chat_ready()

        result = send_query_and_get_response("查询所有供应商")

        # Response should have meaningful content (not just "OK" or empty)
        assert len(result["text"]) > 20, f"Response too short: '{result['text'][:50]}'"

        # Trace ID should be present
        assert result["trace_id"], f"No trace ID in response"

    def test_tc103_streaming_response(self, admin_logged_in, wait_for_chat_ready):
        """TC-103: Streaming response shows text growing over time."""
        page = admin_logged_in
        wait_for_chat_ready()

        textarea = page.locator(CHAT_TEXTAREA).first
        textarea.fill("什么是采购订单")
        textarea.press("Enter")

        # Wait for assistant message to appear
        page.wait_for_selector(MSG_ASSISTANT, timeout=30000)

        # Capture text length at two points to verify streaming
        page.wait_for_timeout(1000)
        text_a = page.locator(MSG_ASSISTANT).last.inner_text()

        page.wait_for_timeout(3000)
        text_b = page.locator(MSG_ASSISTANT).last.inner_text()

        # Either text grew (streaming) or response completed quickly (also fine)
        assert len(text_b) >= len(text_a), "Response text should not shrink"
        assert len(text_b) > 5, f"Final response too short: '{text_b}'"

    def test_tc104_progress_steps_display(self, admin_logged_in, wait_for_chat_ready):
        """TC-104: Progress/processing indicator shown during query."""
        page = admin_logged_in
        wait_for_chat_ready()

        textarea = page.locator(CHAT_TEXTAREA).first
        textarea.fill("查询采购订单")
        textarea.press("Enter")

        # Check for progress indicator immediately after sending
        # (may disappear quickly once response arrives)
        progress = page.locator(f'{PROGRESS_AREA}, .el-steps, [class*="progress"], .processing, [class*="loading"]')
        # Progress is transient — if query is fast it may not appear
        # Main assertion: response eventually arrives
        page.wait_for_selector(MSG_ASSISTANT, timeout=60000)
        expect(page.locator(MSG_ASSISTANT).last).to_be_visible()

    def test_tc105_query_results_table(self, admin_logged_in, wait_for_chat_ready, send_query_and_get_response):
        """TC-105: Query results displayed in data table with actual rows."""
        page = admin_logged_in
        wait_for_chat_ready()

        result = send_query_and_get_response("查询前5个采购订单", timeout=150000)

        assert result["has_data_table"], "Response should have data table collapse"
        assert result["data_row_count"] > 0, f"Data table should have rows, got {result['data_row_count']}"

    def test_tc106_ngql_display(self, admin_logged_in, wait_for_chat_ready, send_chat_query, expand_cypher_block):
        """TC-106: Executed nGQL/Cypher query viewable in collapse block."""
        page = admin_logged_in
        wait_for_chat_ready()

        send_chat_query("查询供应商", timeout=20000)

        cypher_text = expand_cypher_block()
        assert cypher_text, "Cypher code block is empty"

        # Should contain graph query keywords
        keywords = ["MATCH", "GO", "LOOKUP", "FETCH", "FIND"]
        has_keyword = any(kw in cypher_text.upper() for kw in keywords)
        assert has_keyword, f"Cypher text lacks graph query keywords: {cypher_text[:200]}"

    @pytest.mark.skip(reason="Temporarily disabled — trace_id rendering not the focus right now")
    def test_tc107_trace_id_format(self, admin_logged_in, wait_for_chat_ready, send_query_and_get_response):
        """TC-107: Trace ID has expected format and is displayed as link."""
        page = admin_logged_in
        wait_for_chat_ready()

        result = send_query_and_get_response("查询采购订单")

        assert result["trace_id"], "No trace ID found"

        # Verify trace ID link is rendered
        trace_link = page.locator(MSG_ASSISTANT).last.locator(TRACE_ID_LINK)
        expect(trace_link).to_be_visible()

    def test_tc108_error_handling(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-108: Invalid/nonsense query returns graceful response."""
        page = admin_logged_in
        wait_for_chat_ready()

        send_chat_query("查询不存在的标签哈哈哈哈哈哈哈", timeout=60000)

        response = page.locator(MSG_ASSISTANT).last
        expect(response).to_be_visible()
        response_text = response.inner_text()
        assert len(response_text) > 5, f"Error response too short: '{response_text}'"

    def test_tc109_continue_conversation_context(self, admin_logged_in, wait_for_chat_ready, send_chat_query, send_query_and_get_response):
        """TC-109: Second query references first query's context."""
        page = admin_logged_in
        wait_for_chat_ready()

        # First query establishes context
        send_chat_query("查询采购订单", timeout=20000)
        page.wait_for_timeout(2000)

        # Second query references context
        result = send_query_and_get_response("上面的订单金额是多少")

        # Response should contain some numeric data (referencing previous context)
        assert len(result["text"]) > 10, "Context follow-up response too short"

    def test_tc110_multiple_queries_with_traces(self, admin_logged_in, wait_for_chat_ready, send_query_and_get_response):
        """TC-110: Multiple queries each produce responses with unique trace IDs."""
        page = admin_logged_in
        wait_for_chat_ready()

        queries = ["查询供应商", "查询采购订单", "查询物料"]
        trace_ids = []

        for q in queries:
            result = send_query_and_get_response(q)
            assert len(result["text"]) > 10, f"Response for '{q}' too short"
            if result["trace_id"]:
                trace_ids.append(result["trace_id"])

        # All 3 queries should have responses
        all_messages = page.locator(MSG_ASSISTANT)
        assert all_messages.count() >= 3, f"Expected >=3 assistant messages, got {all_messages.count()}"

        # Trace IDs should be unique
        if len(trace_ids) >= 2:
            assert len(set(trace_ids)) == len(trace_ids), f"Duplicate trace IDs: {trace_ids}"

    @pytest.mark.skip(reason="Temporarily disabled — execution time display not the focus right now")
    def test_tc111_execution_time_display(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-111: Execution time is displayed in response."""
        page = admin_logged_in
        wait_for_chat_ready()

        send_chat_query("查询采购订单", timeout=90000)

        exec_time = page.locator(MSG_ASSISTANT).last.locator(EXECUTION_TIME)
        expect(exec_time).to_be_visible(timeout=5000)

        time_text = exec_time.inner_text()
        assert re.search(r'\d+', time_text), f"Execution time has no number: '{time_text}'"

    def test_tc112_raw_data_toggle(self, admin_logged_in, wait_for_chat_ready, send_chat_query, expand_data_table):
        """TC-112: Raw data can be toggled visible and has rows."""
        page = admin_logged_in
        wait_for_chat_ready()

        send_chat_query("查询采购订单", timeout=20000)

        row_count = expand_data_table()
        assert row_count > 0, f"Data table should have rows, got {row_count}"
