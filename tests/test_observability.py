"""Tests for observability: metric name alignment, tracing, ETL timestamp."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# O1: Alert rule metric names match collectors.py definitions
# ---------------------------------------------------------------------------

_COLLECTORS_PATH = Path(__file__).resolve().parents[1] / "src" / "honeybadge" / "metrics" / "collectors.py"
_RULES_PATH = Path(__file__).resolve().parents[1] / "deploy" / "observability" / "prometheus" / "rules" / "honeybadge.yml"


def _extract_metric_names_from_collectors() -> set[str]:
    """Extract all honeybadge_* metric names defined in collectors.py."""
    content = _COLLECTORS_PATH.read_text(encoding="utf-8")
    # Match string literals like "honeybadge_llm_requests_total"
    return set(re.findall(r'"(honeybadge_\w+)"', content))


def _extract_metric_names_from_rules() -> set[str]:
    """Extract all honeybadge_* metric references from alert rules."""
    content = _RULES_PATH.read_text(encoding="utf-8")
    # Match honeybadge_* identifiers in PromQL expressions
    names = set(re.findall(r'\b(honeybadge_\w+)', content))
    # Strip _bucket/_sum/_count suffixes (histogram aggregation suffixes)
    cleaned = set()
    for n in names:
        for suffix in ("_bucket", "_sum", "_count"):
            if n.endswith(suffix):
                n = n[: -len(suffix)]
                break
        cleaned.add(n)
    return cleaned


class TestAlertRuleMetricAlignment:
    """Every metric referenced in alert rules must exist in collectors.py."""

    def test_all_rule_metrics_exist_in_collectors(self) -> None:
        collector_metrics = _extract_metric_names_from_collectors()
        rule_metrics = _extract_metric_names_from_rules()

        missing = rule_metrics - collector_metrics
        assert not missing, (
            f"Alert rules reference metrics not defined in collectors.py: {missing}. "
            "These alerts will never fire."
        )

    def test_query_duration_metric_correct(self) -> None:
        """The HighLatency alert must use honeybadge_query_duration_seconds, not _e2e_."""
        content = _RULES_PATH.read_text(encoding="utf-8")
        assert "query_e2e_duration_seconds" not in content, (
            "honeybadge_query_e2e_duration_seconds does not exist; use honeybadge_query_duration_seconds"
        )
        assert "honeybadge_query_duration_seconds_bucket" in content

    def test_llm_error_rate_uses_requests_not_tokens(self) -> None:
        """LLM error rate should be errors/requests, not errors/tokens."""
        content = _RULES_PATH.read_text(encoding="utf-8")
        # Find the LLMHighErrorRate expression block
        llm_section = content[content.find("LLMHighErrorRate"):content.find("LLMHighErrorRate") + 500]
        assert "llm_requests_total" in llm_section, "Should use requests as denominator"
        assert "llm_tokens_total" not in llm_section, (
            "tokens_total as denominator is semantically wrong (tokens != requests)"
        )

    def test_workers_metric_no_status_label(self) -> None:
        """honeybadge_hiclaw_workers_active is a separate gauge, not a label."""
        content = _RULES_PATH.read_text(encoding="utf-8")
        assert 'honeybadge_hiclaw_workers{status="active"}' not in content, (
            "Should use honeybadge_hiclaw_workers_active (no label), not {status='active'}"
        )
        assert "honeybadge_hiclaw_workers_active" in content

    def test_nebula_pool_metric_correct(self) -> None:
        """Nebula pool alert should use connection_pool_available, not pool_size{status}."""
        content = _RULES_PATH.read_text(encoding="utf-8")
        assert 'honeybadge_nebula_pool_size{status=' not in content
        assert "honeybadge_nebula_connection_pool_available" in content


# ---------------------------------------------------------------------------
# O5: ETL last_success_timestamp metric exists
# ---------------------------------------------------------------------------

class TestETLTimestampMetric:
    """Verify the ETLStale alert has a backing metric."""

    def test_etl_last_success_timestamp_defined(self) -> None:
        content = _COLLECTORS_PATH.read_text(encoding="utf-8")
        assert "honeybadge_etl_last_success_timestamp" in content, (
            "ETLMetricsCollector must define honeybadge_etl_last_success_timestamp "
            "for the ETLStale alert rule"
        )

    def test_etl_last_success_timestamp_is_gauge(self) -> None:
        content = _COLLECTORS_PATH.read_text(encoding="utf-8")
        # Find the metric definition and check it's a Gauge
        idx = content.find("honeybadge_etl_last_success_timestamp")
        # Look backwards for the type
        definition_block = content[max(0, idx - 200):idx + 100]
        assert "Gauge(" in definition_block, "Should be a Gauge (not Counter)"


# ---------------------------------------------------------------------------
# O4: Tracing module
# ---------------------------------------------------------------------------

class TestTracingModule:
    """Verify OpenTelemetry tracing integration."""

    def test_init_tracing_noop_without_endpoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without OTEL_EXPORTER_OTLP_ENDPOINT, tracing should be no-op."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        from honeybadge.observability.tracing import init_tracing, is_otel_enabled

        init_tracing()
        assert is_otel_enabled() is False

    def test_get_tracer_returns_tracer(self) -> None:
        from honeybadge.observability.tracing import get_tracer

        tracer = get_tracer()
        assert tracer is not None

    def test_tracer_start_span_does_not_raise(self) -> None:
        from honeybadge.observability.tracing import get_tracer

        tracer = get_tracer()
        with tracer.start_as_current_span("test-span") as span:
            assert span is not None


# ---------------------------------------------------------------------------
# O2: Prometheus scrape config includes honeybadge-server
# ---------------------------------------------------------------------------

class TestPrometheusScrapeConfig:
    """Verify Prometheus is configured to scrape all HoneyBadge services."""

    def test_honeybadge_server_in_scrape_configs(self) -> None:
        prom_path = Path(__file__).resolve().parents[1] / "deploy" / "observability" / "prometheus" / "prometheus.yml"
        content = prom_path.read_text(encoding="utf-8")
        assert "honeybadge-server:8090" in content, (
            "Prometheus must scrape honeybadge-server:8090 for /metrics"
        )

    def test_jaeger_container_in_compose(self) -> None:
        compose_path = Path(__file__).resolve().parents[1] / "deploy" / "docker" / "docker-compose.yaml"
        content = compose_path.read_text(encoding="utf-8")
        assert "jaeger:" in content
        assert "16686" in content  # Jaeger UI port
        assert "4317" in content   # OTLP gRPC port
