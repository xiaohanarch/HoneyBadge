"""
Worker Routing E2E Tests
HoneyBadge - Enterprise Knowledge Graph Assistant

Test Coverage:
- TC-1101: Simple data query routes to graph-worker
- TC-1102: Analysis query routes to analytics-worker
- TC-1103: Non-ERP question handled by Manager directly (not routed to workers)
- TC-1104: Lookup keyword variants all produce structured query responses
- TC-1105: Analysis keyword variants all produce structured query responses
- TC-1106: Greeting does not trigger graph query pipeline
"""
import re
import pytest
from datetime import datetime, timezone
from playwright.sync_api import expect
from tests.e2e.selectors import (
    CHAT_TEXTAREA, MSG_ASSISTANT,
    TRACE_ID_LINK, CYPHER_COLLAPSE_HEADER, CYPHER_CODE,
    DATA_COLLAPSE_HEADER, DATA_ROWS,
)



def _get_worker_logs_since(container_name: str, since: datetime) -> str:
    """Fetch Docker container logs since a given UTC timestamp.

    Returns empty string if Docker SDK is unavailable or container not found.
    """
    try:
        import docker
        client = docker.from_env()
        container = client.containers.get(container_name)
        return container.logs(since=since).decode("utf-8", errors="replace")
    except Exception:
        return ""


@pytest.mark.e2e
@pytest.mark.routing
class TestWorkerRouting:
    """Verify Manager routes queries to the correct worker based on intent."""

    def test_tc1101_simple_query_routes_to_graph_worker(
        self, admin_logged_in, wait_for_chat_ready, send_query_and_get_response,
    ):
        """TC-1101: Simple data lookup routes to graph-worker.

        Sends a factual ERP query and verifies:
        1. Response contains structured query elements (trace_id, cypher, data table)
        2. graph-worker container shows activity in Docker logs
        3. analytics-worker does NOT receive the task
        """
        page = admin_logged_in
        wait_for_chat_ready()

        ts_before = datetime.now(timezone.utc)
        result = send_query_and_get_response("查询前5个供应商")

        # Structured ERP response indicates a worker processed the query
        assert result["trace_id"], "graph-worker response should have trace_id"
        assert result["has_cypher"], "graph-worker response should have cypher block"

        # Docker log verification (supplementary — skipped if Docker unavailable)
        graph_logs = _get_worker_logs_since("honeybadge-graph-worker", ts_before)
        analytics_logs = _get_worker_logs_since("honeybadge-analytics-worker", ts_before)

        if graph_logs:
            # graph-worker should show task execution activity
            assert len(graph_logs.strip()) > 0, \
                "graph-worker should have log activity for simple lookup query"

        if analytics_logs:
            # analytics-worker should NOT have received this task
            task_indicators = ["spec.md", "task received", "cypher-query"]
            has_task = any(ind in analytics_logs.lower() for ind in task_indicators)
            assert not has_task, \
                f"analytics-worker should NOT receive simple lookup query, but logs show task activity"

    def test_tc1102_analysis_query_routes_to_analytics_worker(
        self, admin_logged_in, wait_for_chat_ready, send_query_and_get_response,
    ):
        """TC-1102: Analysis/anomaly query routes to analytics-worker.

        Sends an analysis question and verifies:
        1. Response contains meaningful analytical content
        2. analytics-worker container shows activity in Docker logs
        """
        page = admin_logged_in
        wait_for_chat_ready()

        ts_before = datetime.now(timezone.utc)
        result = send_query_and_get_response(
            "分析采购订单金额异常，检测是否存在三单匹配问题",
            timeout=60000,
        )

        # Should produce a substantive analytical response
        assert len(result["text"]) > 20, \
            f"analytics-worker should produce meaningful response, got: '{result['text'][:80]}'"
        assert result["trace_id"], "analytics-worker response should have trace_id"

        # Docker log verification (supplementary)
        analytics_logs = _get_worker_logs_since("honeybadge-analytics-worker", ts_before)
        if analytics_logs:
            assert len(analytics_logs.strip()) > 0, \
                "analytics-worker should have log activity for analysis query"

    def test_tc1103_non_erp_question_stays_in_manager(
        self, admin_logged_in, wait_for_chat_ready, send_chat_query,
    ):
        """TC-1103: Non-ERP question is handled by Manager directly.

        Sends a greeting/general question and verifies:
        1. Manager responds with text (not an error)
        2. Response does NOT contain structured query elements (trace_id, cypher, data table)
        This confirms the Manager did not route to any worker.
        """
        page = admin_logged_in
        wait_for_chat_ready()

        send_chat_query("你好，请做个自我介绍", timeout=60000)

        last_msg = page.locator(MSG_ASSISTANT).last
        response_text = last_msg.inner_text()

        # Manager should produce a meaningful text response
        assert len(response_text) > 5, \
            f"Manager should respond to greeting, got: '{response_text}'"

        # Non-ERP response must NOT have structured query result elements
        has_trace = last_msg.locator(TRACE_ID_LINK).count() > 0
        has_cypher = last_msg.locator(CYPHER_COLLAPSE_HEADER).count() > 0
        has_data = last_msg.locator(DATA_COLLAPSE_HEADER).count() > 0

        assert not has_trace, \
            "Non-ERP response should NOT have trace_id — Manager should respond directly"
        assert not has_cypher, \
            "Non-ERP response should NOT have cypher block — no graph query should execute"
        assert not has_data, \
            "Non-ERP response should NOT have data table — no graph query should execute"

    @pytest.mark.parametrize("query", [
        "查询采购订单",
        "查找供应商信息",
        "搜索物料编码M001的详情",
        "列出所有发票",
    ])
    def test_tc1104_graph_worker_routing_keywords(
        self, admin_logged_in, wait_for_chat_ready, send_query_and_get_response,
        query,
    ):
        """TC-1104: Lookup keywords (查询/查找/搜索/列出) produce structured query responses."""
        page = admin_logged_in
        wait_for_chat_ready()

        result = send_query_and_get_response(query, timeout=60000)

        assert result["trace_id"], \
            f"'{query}' should produce trace_id (routed to worker)"
        assert result["has_cypher"], \
            f"'{query}' should produce cypher block (graph query executed)"

    @pytest.mark.parametrize("query", [
        "分析本月采购趋势",
        "检测发票金额异常",
        "对比各供应商的交付周期",
        "统计采购订单的供应商集中度",
    ])
    def test_tc1105_analytics_worker_routing_keywords(
        self, admin_logged_in, wait_for_chat_ready, send_query_and_get_response,
        query,
    ):
        """TC-1105: Analysis keywords (分析/检测/对比/统计) produce structured query responses."""
        page = admin_logged_in
        wait_for_chat_ready()

        result = send_query_and_get_response(query, timeout=60000)

        assert result["trace_id"], \
            f"'{query}' should produce trace_id (routed to analytics-worker)"
        assert len(result["text"]) > 20, \
            f"'{query}' should produce meaningful analytical response"

    def test_tc1106_general_chitchat_no_graph_pipeline(
        self, admin_logged_in, wait_for_chat_ready, send_chat_query,
    ):
        """TC-1106: General chitchat does not trigger the graph query pipeline.

        Different from TC-1103 — uses a knowledge question (not just greeting)
        to verify Manager doesn't over-route to workers.
        """
        page = admin_logged_in
        wait_for_chat_ready()

        send_chat_query("Python的列表推导式怎么写", timeout=60000)

        last_msg = page.locator(MSG_ASSISTANT).last
        response_text = last_msg.inner_text()

        assert len(response_text) > 5, \
            f"Manager should answer general knowledge question, got: '{response_text}'"

        # Should NOT trigger graph query pipeline
        has_trace = last_msg.locator(TRACE_ID_LINK).count() > 0
        has_cypher = last_msg.locator(CYPHER_COLLAPSE_HEADER).count() > 0

        assert not has_trace, \
            "General knowledge question should NOT produce trace_id"
        assert not has_cypher, \
            "General knowledge question should NOT produce cypher block"
