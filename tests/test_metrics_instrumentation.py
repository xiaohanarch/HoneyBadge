"""Tests for Prometheus metrics instrumentation.

Verifies that the metrics defined in collectors.py are actually emitted
by the instrumented code paths:
  - /metrics endpoint exposes honeybadge_* metrics
  - LLM metrics recorded on adapter.chat()
  - Validation metrics (L1/L2) recorded on validator calls
  - Query metrics recorded in process_query
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prometheus_client import REGISTRY, generate_latest
from prometheus_client.parser import text_string_to_metric_families

from honeybadge.protocols.validator import NgqlValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _metric_value(metric_name: str, label_filter: dict | None = None) -> float:
    """Extract a metric value from the global Prometheus registry.

    Matches against *sample* names (not family names) because
    text_string_to_metric_families strips the ``_total`` suffix from
    Counter family names while sample names retain it.

    Returns the sum of all samples matching *metric_name* and (optionally)
    the given label filter. Returns 0.0 if the metric is not found.
    """
    text = generate_latest(REGISTRY).decode("utf-8")
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.name == metric_name:
                if label_filter is None or all(
                    sample.labels.get(k) == v for k, v in label_filter.items()
                ):
                    return sample.value
    return 0.0


# ---------------------------------------------------------------------------
# /metrics endpoint
# ---------------------------------------------------------------------------
class TestMetricsEndpoint:
    def test_metrics_endpoint_exposes_honeybadge_metrics(self):
        """GET /metrics returns text containing honeybadge_ metric names."""
        from fastapi.testclient import TestClient

        from honeybadge.server.app import create_app
        from honeybadge.server.config import ServerConfig

        # Use dummy config — lifespan services will fail but /metrics
        # doesn't depend on them (it's mounted before lifespan init).
        config = ServerConfig(
            host="127.0.0.1", port=8090,
            jwt_secret="test-secret",
        )
        app = create_app(config)
        with TestClient(app) as client:
            resp = client.get("/metrics")
        assert resp.status_code == 200
        body = resp.text
        # The collectors define these metrics — they must appear in /metrics.
        assert "honeybadge_llm_requests_total" in body
        assert "honeybadge_query_total" in body
        assert "honeybadge_validation_total" in body
        assert "honeybadge_nebula_query_total" in body


# ---------------------------------------------------------------------------
# Validation metrics (L1/L2)
# ---------------------------------------------------------------------------
class TestValidationMetrics:
    def test_l1_metrics_recorded_on_valid_syntax(self):
        """validate_syntax on a valid MATCH records L1 pass."""
        before = _metric_value(
            "honeybadge_validation_total", {"level": "L1", "result": "pass"}
        )
        validator = NgqlValidator()
        result = validator.validate_syntax("MATCH (n) RETURN n LIMIT 10")
        assert result.valid
        after = _metric_value(
            "honeybadge_validation_total", {"level": "L1", "result": "pass"}
        )
        assert after > before

    def test_l1_metrics_recorded_on_invalid_syntax(self):
        """validate_syntax on invalid nGQL records L1 fail."""
        before = _metric_value(
            "honeybadge_validation_total", {"level": "L1", "result": "fail"}
        )
        validator = NgqlValidator()
        validator.validate_syntax("")  # empty → E001
        after = _metric_value(
            "honeybadge_validation_total", {"level": "L1", "result": "fail"}
        )
        assert after > before

    def test_l2_metrics_recorded_on_schema_check(self):
        """validate_schema records L2 pass when no schema is loaded."""
        before = _metric_value(
            "honeybadge_validation_total", {"level": "L2", "result": "pass"}
        )
        validator = NgqlValidator()
        # No schema loaded → early return with W003 warning, still "valid"
        result = validator.validate_schema("MATCH (n) RETURN n")
        assert result.valid
        after = _metric_value(
            "honeybadge_validation_total", {"level": "L2", "result": "pass"}
        )
        assert after > before

    def test_validation_duration_histogram_emitted(self):
        """validation_duration_seconds histogram has L1 observations."""
        validator = NgqlValidator()
        validator.validate_syntax("MATCH (n) RETURN n LIMIT 5")
        text = generate_latest(REGISTRY).decode("utf-8")
        assert "honeybadge_validation_duration_seconds" in text


# ---------------------------------------------------------------------------
# LLM metrics (adapter)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
class TestLLMMetrics:
    async def test_llm_request_metrics_recorded_on_success(self):
        """A successful _chat_once emits llm_requests_total + tokens."""
        from honeybadge.llm.adapter import LLMRequest, OpenAICompatibleAdapter

        before_req = _metric_value("honeybadge_llm_requests_total")
        before_tokens = _metric_value("honeybadge_llm_tokens_total")

        adapter = OpenAICompatibleAdapter(
            {"endpoint": "http://localhost:9999/v1", "api_key": "k", "model": "test-model"},
            None,
        )

        # Mock the httpx client to return a successful chat completion.
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "model": "test-model",
            "choices": [{"message": {"content": "MATCH (n) RETURN n"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            resp = await adapter._chat_once(LLMRequest(messages=[{"role": "user", "content": "hi"}]))

        assert resp.content == "MATCH (n) RETURN n"

        after_req = _metric_value("honeybadge_llm_requests_total")
        after_tokens = _metric_value("honeybadge_llm_tokens_total")
        assert after_req > before_req, "llm_requests_total did not increase"
        assert after_tokens > before_tokens, "llm_tokens_total did not increase"

    async def test_llm_error_metric_recorded_on_server_error(self):
        """A 500 response emits llm_errors_total."""
        from honeybadge.llm.adapter import LLMError, LLMRequest, OpenAICompatibleAdapter

        before = _metric_value("honeybadge_llm_errors_total")

        adapter = OpenAICompatibleAdapter(
            {"endpoint": "http://localhost:9999/v1", "api_key": "k", "model": "test-model"},
            None,
        )

        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            with pytest.raises(LLMError):
                await adapter._chat_once(
                    LLMRequest(messages=[{"role": "user", "content": "hi"}])
                )

        after = _metric_value("honeybadge_llm_errors_total")
        assert after > before, "llm_errors_total did not increase"


# ---------------------------------------------------------------------------
# Query metrics (websocket process_query)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
class TestQueryMetrics:
    async def test_query_metrics_recorded_on_success(self):
        """process_query emits query_total (success) + phase durations."""
        from honeybadge.db.nebula import NebulaQueryResult
        from honeybadge.llm.adapter import LLMResponse
        from honeybadge.server.websocket import process_query

        before_success = _metric_value(
            "honeybadge_query_total", {"query_type": "ws", "status": "success"}
        )

        # Mocks
        mock_nebula = AsyncMock()
        mock_nebula.execute = AsyncMock(
            return_value=NebulaQueryResult(
                columns=["n"], rows=[{"n": 1}], execution_time_ms=5, success=True,
            )
        )
        mock_pg = AsyncMock()
        mock_pg.get_session_audit_logs = AsyncMock(return_value=[])
        mock_pg.write_audit_log = AsyncMock()

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(
            return_value=LLMResponse(
                content="MATCH (n) RETURN n LIMIT 10",
                model="test", prompt_tokens=5, completion_tokens=5,
                total_tokens=10, finish_reason="stop", latency_ms=10,
            )
        )

        await process_query(
            question="查询供应商",
            session_id="test-session",
            nebula=mock_nebula,
            pg=mock_pg,
            llm_adapter=mock_llm,
            user_id="admin",
            org_id=None,
            roles=["admin"],
        )

        after_success = _metric_value(
            "honeybadge_query_total", {"query_type": "ws", "status": "success"}
        )
        assert after_success > before_success, "query_total (success) did not increase"

    async def test_query_metrics_recorded_on_error(self):
        """process_query emits query_total (error) when an exception occurs."""
        from honeybadge.llm.adapter import LLMResponse
        from honeybadge.server.websocket import process_query

        before_error = _metric_value(
            "honeybadge_query_total", {"query_type": "ws", "status": "error"}
        )

        # Mock nebula to raise → process_query catches → error path
        mock_nebula = AsyncMock()
        mock_nebula.execute = AsyncMock(side_effect=RuntimeError("connection lost"))

        mock_pg = AsyncMock()
        mock_pg.get_session_audit_logs = AsyncMock(return_value=[])
        mock_pg.write_audit_log = AsyncMock()

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(
            return_value=LLMResponse(
                content="MATCH (n) RETURN n",
                model="test", prompt_tokens=5, completion_tokens=5,
                total_tokens=10, finish_reason="stop", latency_ms=10,
            )
        )

        result = await process_query(
            question="查询供应商",
            session_id="test-session",
            nebula=mock_nebula,
            pg=mock_pg,
            llm_adapter=mock_llm,
            user_id="admin",
        )
        assert "error" in result

        after_error = _metric_value(
            "honeybadge_query_total", {"query_type": "ws", "status": "error"}
        )
        assert after_error > before_error, "query_total (error) did not increase"
