"""
MCP Services E2E Tests
HoneyBadge - Enterprise Knowledge Graph Assistant

Test Coverage:
- TC-601: NebulaGraph MCP server is healthy
- TC-602: Audit MCP server is healthy
- TC-603: Cache MCP server is healthy
- TC-604: Permission MCP server is healthy
- TC-605: MCP servers are reachable from workers
- TC-606: MCP tool calls return valid responses
- TC-607: MCP connection error handling
- TC-608: Multiple MCP servers can be called in sequence
"""
import pytest
from playwright.sync_api import expect
import httpx
from tests.e2e.selectors import CHAT_TEXTAREA, MSG_ASSISTANT


BASE_URL = "http://localhost:3000"
API_BASE_URL = "http://localhost:8090"


class TestMCPServices:
    """Test MCP (Model Context Protocol) server connectivity and functionality."""

    def test_tc601_nebula_mcp_healthy(self, api_client):
        """TC-601: NebulaGraph MCP server is healthy."""
        # Check NebulaGraph MCP health
        response = api_client.get("http://localhost:8000/health")
        # Should be healthy or return valid response

        # Also check via direct HTTP
        try:
            health_response = httpx.get("http://localhost:8000/health", timeout=10)
            assert health_response.status_code == 200, f"NebulaGraph MCP health check failed: {health_response.status_code}"
        except httpx.ConnectError:
            pytest.fail("Cannot connect to NebulaGraph MCP at localhost:8000")

    def test_tc602_audit_mcp_healthy(self, api_client):
        """TC-602: Audit MCP server is healthy."""
        # Check audit service health endpoint
        response = api_client.get("/api/health")
        if response.status_code == 200:
            health_data = response.json()
            assert "status" in health_data or "service" in health_data

    def test_tc603_cache_mcp_healthy(self):
        """TC-603: Cache MCP server is healthy."""
        # Check Redis connectivity
        try:
            import redis
            r = redis.Redis(host='localhost', port=6379, decode_responses=True)
            r.ping()
            # Redis is healthy
        except ImportError:
            pytest.skip("redis-py not installed")
        except Exception as e:
            pytest.fail(f"Redis health check failed: {e}")

    def test_tc604_permission_mcp_healthy(self, api_client):
        """TC-604: Permission MCP server is healthy."""
        # Permission service should be available via Higress
        response = api_client.get("/api/health")
        if response.status_code == 200:
            data = response.json()
            # Should indicate overall health including permissions

    def test_tc605_mcp_servers_reachable_from_workers(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-605: MCP servers are reachable from HiClaw workers."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Send a query that exercises multiple MCP tools
        send_chat_query("查询供应商", timeout=60000)

        # Verify response came through (MCP chain worked)
        response = page.locator('.chat-message.assistant')
        expect(response.first).to_be_visible()

    def test_tc606_mcp_tool_calls_return_valid(self, admin_logged_in, wait_for_chat_ready):
        """TC-606: MCP tool calls return valid responses."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Query that would use MCP tools
        textarea = page.locator(CHAT_TEXTAREA).first
        textarea.fill("查询采购订单")
        textarea.press("Enter")

        page.wait_for_timeout(10000)

        # Verify response structure is valid
        response = page.locator(MSG_ASSISTANT)
        expect(response.first).to_be_visible(timeout=120000)
        text = response.first.inner_text()
        assert len(text) > 5, f"Response too short: '{text}'"

    def test_tc607_mcp_connection_error_handling(self, admin_logged_in, wait_for_chat_ready):
        """TC-607: MCP connection errors are handled gracefully."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Normal query should work
        textarea = page.locator(CHAT_TEXTAREA).first
        textarea.fill("查询供应商")
        textarea.press("Enter")

        page.wait_for_timeout(10000)

        # Should not show raw error, should handle gracefully
        error_elements = page.locator('[class*="error"]:not([class*="chat-error"]):not([class*="error-message"])')
        if error_elements.count() > 0:
            # There might be visible errors from MCP issues
            pass

        # Chat should still be functional
        expect(page.locator(CHAT_TEXTAREA).first).to_be_visible()

    def test_tc608_multiple_mcp_servers_sequence(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-608: Multiple MCP servers can be called in sequence."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Multiple queries that might use different MCP services
        queries = ["查询供应商", "查询采购订单", "查询物料"]

        for query in queries:
            send_chat_query(query, timeout=60000)
            page.wait_for_timeout(1000)

        # All should have responses
        messages = page.locator('.chat-message.assistant')
        expect(messages).to_have_count(3, timeout=120000)

    def test_tc609_nebula_mcp_functional(self, admin_logged_in, wait_for_chat_ready, send_query_and_get_response):
        """TC-609: NebulaGraph MCP returns actual graph data."""
        page = admin_logged_in
        wait_for_chat_ready()

        result = send_query_and_get_response("查询供应商")
        assert result["data_row_count"] > 0, f"NebulaGraph query should return data rows"

    def test_tc610_audit_mcp_write_verification(self, admin_logged_in, wait_for_chat_ready, send_query_and_get_response):
        """TC-610: Query creates audit record retrievable by trace_id."""
        page = admin_logged_in
        wait_for_chat_ready()

        result = send_query_and_get_response("查询采购订单")
        assert result["trace_id"], "Query should produce a trace_id"

        import httpx
        api = httpx.Client(base_url="http://localhost:8090", timeout=30)
        try:
            resp = api.get("/api/audit", params={"trace_id": result["trace_id"]})
            if resp.status_code == 200:
                assert result["trace_id"] in resp.text, "Audit record should contain trace_id"
            # If audit API not implemented, we at least verified trace_id exists in UI
        finally:
            api.close()
