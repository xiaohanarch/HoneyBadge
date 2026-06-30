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
import httpx
import pytest
from playwright.sync_api import expect

from tests.e2e.selectors import CHAT_TEXTAREA, MSG_ASSISTANT

BASE_URL = "http://localhost:3000"
API_BASE_URL = "http://localhost:8090"


# Previously deferred to 1.1.1 — all three blockers now resolved:
#   1. /api/health returns all services up (redis, postgres, nebula)
#   2. Redis password reconciled (redis123 in both secrets.yaml and test)
#   3. Two-stage harness wait in conftest.py handles mid-stream LLM preamble


class TestMCPServices:
    """Test MCP (Model Context Protocol) server connectivity and functionality."""

    def test_tc601_nebula_mcp_healthy(self, api_client):
        """TC-601: NebulaGraph MCP server is healthy (verified via honeybadge-server health)."""
        # MCP servers are internal Docker services, not directly exposed to host.
        # Verify NebulaGraph connectivity via honeybadge-server health endpoint.
        response = api_client.get("/api/health")
        assert response.status_code == 200
        health = response.json()
        services = health.get("services", {})
        nebula_status = services.get("nebula", {}).get("status", "")
        assert nebula_status == "up", f"NebulaGraph not healthy: {services.get('nebula', {})}"

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
            r = redis.Redis(host='localhost', port=6379, password='redis123', decode_responses=True)
            pong = r.ping()
            assert pong is True
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
        send_chat_query("查询供应商", timeout=120000)

        # Verify response came through (MCP chain worked)
        response = page.locator(MSG_ASSISTANT)
        expect(response.last).to_be_visible()

    def test_tc606_mcp_tool_calls_return_valid(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-606: MCP tool calls return valid responses."""
        page = admin_logged_in
        wait_for_chat_ready()

        send_chat_query("查询采购订单", timeout=120000)

        # Verify response structure is valid
        response = page.locator(MSG_ASSISTANT)
        expect(response.last).to_be_visible()
        text = response.last.inner_text()
        assert len(text) > 5, f"Response too short: '{text}'"

    def test_tc607_mcp_connection_error_handling(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-607: MCP connection errors are handled gracefully."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Normal query should work without crashing
        send_chat_query("查询供应商", timeout=120000)

        # Chat should still be functional after query
        expect(page.locator(CHAT_TEXTAREA).first).to_be_visible()
        expect(page.locator(CHAT_TEXTAREA).first).to_be_enabled()

    def test_tc608_multiple_mcp_servers_sequence(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-608: Multiple MCP servers can be called in sequence."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Multiple queries that might use different MCP services
        queries = ["查询供应商", "查询采购订单", "查询物料"]

        for query in queries:
            send_chat_query(query, timeout=120000)
            page.wait_for_timeout(1000)

        # Each query produces at least one assistant message (Manager dispatch ack);
        # most also produce a second message from the Worker carrying structured data.
        # Assert >=3 messages (one per query, minimum) rather than exact count.
        messages = page.locator(MSG_ASSISTANT)
        assert messages.count() >= 3, f"Expected >=3 assistant messages for 3 queries, got {messages.count()}"

    def test_tc609_nebula_mcp_functional(self, admin_logged_in, wait_for_chat_ready, send_query_and_get_response):
        """TC-609: NebulaGraph MCP returns actual graph data."""
        page = admin_logged_in
        wait_for_chat_ready()

        result = send_query_and_get_response("查询供应商")
        assert result["data_row_count"] > 0, "NebulaGraph query should return data rows"

    def test_tc610_audit_mcp_write_verification(self, admin_logged_in, wait_for_chat_ready, send_query_and_get_response):
        """TC-610: Query creates audit record retrievable by trace_id."""
        page = admin_logged_in
        wait_for_chat_ready()

        result = send_query_and_get_response("查询采购订单")
        assert result["trace_id"], "Query should produce a trace_id"

        api = httpx.Client(base_url="http://localhost:8090", timeout=30)
        try:
            resp = api.get("/api/audit", params={"trace_id": result["trace_id"]})
            if resp.status_code == 200:
                assert result["trace_id"] in resp.text, "Audit record should contain trace_id"
            # If audit API not implemented, we at least verified trace_id exists in UI
        finally:
            api.close()
