"""Prometheus metrics collectors for HoneyBadge.

Defines all Prometheus metrics used in the HoneyBadge system organized by component.
All metrics follow the pattern: honeybadge_{component}_{name}
"""


from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge, Histogram

# =============================================================================
# LLM Metrics
# =============================================================================

class LLMMetricsCollector:
    """
    LLM-related Prometheus metrics.

    Metrics:
    - llm_requests_total: Total number of LLM requests (counter)
    - llm_tokens_total: Total tokens consumed (counter, labels: model, type)
    - llm_request_duration_seconds: Request latency histogram
    - llm_errors_total: Total LLM errors (counter, labels: error_type)
    - llm_provider_health: Provider health status (gauge, labels: provider)
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        """Initialize LLM metrics collectors."""
        self._registry = registry or REGISTRY

        # Total LLM requests
        self.requests_total = Counter(
            "honeybadge_llm_requests_total",
            "Total number of LLM requests",
            ["provider", "model", "operation"],
            registry=self._registry,
        )

        # Token consumption
        self.tokens_total = Counter(
            "honeybadge_llm_tokens_total",
            "Total tokens consumed",
            ["model", "token_type"],  # token_type: prompt | completion | total
            registry=self._registry,
        )

        # Request duration
        self.request_duration_seconds = Histogram(
            "honeybadge_llm_request_duration_seconds",
            "LLM request duration in seconds",
            ["provider", "model", "operation"],
            buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
            registry=self._registry,
        )

        # Error counter
        self.errors_total = Counter(
            "honeybadge_llm_errors_total",
            "Total LLM errors",
            ["provider", "error_type"],
            registry=self._registry,
        )

        # Provider health status (1 = healthy, 0 = unhealthy)
        self.provider_health = Gauge(
            "honeybadge_llm_provider_health",
            "LLM provider health status (1=healthy, 0=unhealthy)",
            ["provider"],
            registry=self._registry,
        )

        # Rate limit hits
        self.rate_limit_hits_total = Counter(
            "honeybadge_llm_rate_limit_hits_total",
            "Total rate limit exceeded events",
            ["provider"],
            registry=self._registry,
        )

    def record_request(
        self,
        provider: str,
        model: str,
        operation: str,
        duration_seconds: float,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """Record a completed LLM request."""
        self.requests_total.labels(
            provider=provider,
            model=model,
            operation=operation,
        ).inc()

        self.request_duration_seconds.labels(
            provider=provider,
            model=model,
            operation=operation,
        ).observe(duration_seconds)

        self.tokens_total.labels(model=model, token_type="prompt").inc(prompt_tokens)
        self.tokens_total.labels(model=model, token_type="completion").inc(completion_tokens)
        self.tokens_total.labels(model=model, token_type="total").inc(
            prompt_tokens + completion_tokens
        )

    def record_error(
        self,
        provider: str,
        error_type: str,
    ) -> None:
        """Record an LLM error."""
        self.errors_total.labels(
            provider=provider,
            error_type=error_type,
        ).inc()

    def record_rate_limit(self, provider: str) -> None:
        """Record a rate limit exceeded event."""
        self.rate_limit_hits_total.labels(provider=provider).inc()

    def set_provider_health(
        self,
        provider: str,
        healthy: bool,
    ) -> None:
        """Set provider health status."""
        self.provider_health.labels(provider=provider).set(1 if healthy else 0)


# =============================================================================
# NebulaGraph Metrics
# =============================================================================

class NebulaMetricsCollector:
    """
    NebulaGraph database Prometheus metrics.

    Metrics:
    - nebula_query_duration_seconds: Query execution time histogram
    - nebula_query_total: Total number of queries (counter)
    - nebula_connection_pool_size: Current connection pool size (gauge)
    - nebula_connection_pool_available: Available connections (gauge)
    - nebula_query_errors_total: Query errors (counter)
    - nebula_session_duration_seconds: Session lifetime histogram
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        """Initialize NebulaGraph metrics collectors."""
        self._registry = registry or REGISTRY

        # Query duration
        self.query_duration_seconds = Histogram(
            "honeybadge_nebula_query_duration_seconds",
            "NebulaGraph query duration in seconds",
            ["space", "operation"],
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            registry=self._registry,
        )

        # Query counter
        self.query_total = Counter(
            "honeybadge_nebula_query_total",
            "Total NebulaGraph queries",
            ["space", "operation", "status"],
            registry=self._registry,
        )

        # Connection pool
        self.connection_pool_size = Gauge(
            "honeybadge_nebula_connection_pool_size",
            "NebulaGraph connection pool size",
            ["host", "port"],
            registry=self._registry,
        )

        self.connection_pool_available = Gauge(
            "honeybadge_nebula_connection_pool_available",
            "Available NebulaGraph connections",
            ["host", "port"],
            registry=self._registry,
        )

        # Query errors
        self.query_errors_total = Counter(
            "honeybadge_nebula_query_errors_total",
            "Total NebulaGraph query errors",
            ["space", "error_type"],
            registry=self._registry,
        )

        # Session metrics
        self.session_duration_seconds = Histogram(
            "honeybadge_nebula_session_duration_seconds",
            "NebulaGraph session lifetime in seconds",
            ["space"],
            buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0, 1800.0),
            registry=self._registry,
        )

        # Active sessions
        self.active_sessions = Gauge(
            "honeybadge_nebula_active_sessions",
            "Number of active NebulaGraph sessions",
            ["space"],
            registry=self._registry,
        )

    def record_query(
        self,
        space: str,
        operation: str,
        duration_seconds: float,
        success: bool,
    ) -> None:
        """Record a NebulaGraph query."""
        self.query_duration_seconds.labels(
            space=space,
            operation=operation,
        ).observe(duration_seconds)

        self.query_total.labels(
            space=space,
            operation=operation,
            status="success" if success else "failure",
        ).inc()

    def record_error(
        self,
        space: str,
        error_type: str,
    ) -> None:
        """Record a NebulaGraph query error."""
        self.query_errors_total.labels(
            space=space,
            error_type=error_type,
        ).inc()

    def set_connection_pool_status(
        self,
        host: str,
        port: int,
        size: int,
        available: int,
    ) -> None:
        """Set connection pool status."""
        self.connection_pool_size.labels(host=host, port=str(port)).set(size)
        self.connection_pool_available.labels(host=host, port=str(port)).set(available)


# =============================================================================
# HiClaw Metrics
# =============================================================================

class HiClawMetricsCollector:
    """
    HiClaw agent orchestration Prometheus metrics.

    Metrics:
    - hiclaw_workers_total: Total workers (gauge, labels: group)
    - hiclaw_workers_active: Active workers (gauge, labels: group)
    - hiclaw_task_queue_size: Task queue depth (gauge, labels: group)
    - hiclaw_task_duration_seconds: Task execution time histogram
    - hiclaw_task_total: Total tasks processed (counter)
    - hiclaw_task_errors_total: Task errors (counter)
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        """Initialize HiClaw metrics collectors."""
        self._registry = registry or REGISTRY

        # Worker counts
        self.workers_total = Gauge(
            "honeybadge_hiclaw_workers_total",
            "Total number of HiClaw workers",
            ["group"],
            registry=self._registry,
        )

        self.workers_active = Gauge(
            "honeybadge_hiclaw_workers_active",
            "Number of active HiClaw workers",
            ["group"],
            registry=self._registry,
        )

        # Task queue
        self.task_queue_size = Gauge(
            "honeybadge_hiclaw_task_queue_size",
            "HiClaw task queue depth",
            ["group", "priority"],
            registry=self._registry,
        )

        # Task duration
        self.task_duration_seconds = Histogram(
            "honeybadge_hiclaw_task_duration_seconds",
            "HiClaw task duration in seconds",
            ["group", "task_type"],
            buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
            registry=self._registry,
        )

        # Task counter
        self.task_total = Counter(
            "honeybadge_hiclaw_task_total",
            "Total HiClaw tasks processed",
            ["group", "task_type", "status"],
            registry=self._registry,
        )

        # Task errors
        self.task_errors_total = Counter(
            "honeybadge_hiclaw_task_errors_total",
            "Total HiClaw task errors",
            ["group", "task_type", "error_type"],
            registry=self._registry,
        )

        # Message throughput
        self.message_throughput = Counter(
            "honeybadge_hiclaw_messages_total",
            "Total HiClaw messages processed",
            ["group", "message_type"],
            registry=self._registry,
        )

    def record_task(
        self,
        group: str,
        task_type: str,
        duration_seconds: float,
        status: str,
    ) -> None:
        """Record a completed HiClaw task."""
        self.task_duration_seconds.labels(
            group=group,
            task_type=task_type,
        ).observe(duration_seconds)

        self.task_total.labels(
            group=group,
            task_type=task_type,
            status=status,
        ).inc()

    def record_error(
        self,
        group: str,
        task_type: str,
        error_type: str,
    ) -> None:
        """Record a HiClaw task error."""
        self.task_errors_total.labels(
            group=group,
            task_type=task_type,
            error_type=error_type,
        ).inc()

    def set_worker_status(
        self,
        group: str,
        total: int,
        active: int,
    ) -> None:
        """Set worker status."""
        self.workers_total.labels(group=group).set(total)
        self.workers_active.labels(group=group).set(active)

    def set_queue_size(
        self,
        group: str,
        priority: str,
        size: int,
    ) -> None:
        """Set task queue size."""
        self.task_queue_size.labels(group=group, priority=priority).set(size)


# =============================================================================
# Validation Metrics
# =============================================================================

class ValidationMetricsCollector:
    """
    Anti-Hallucination Framework validation Prometheus metrics.

    Metrics:
    - validation_total: Total validations (counter, labels: level, result)
    - validation_errors_total: Validation errors (counter, labels: level, error_code)
    - validation_duration_seconds: Validation time histogram
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        """Initialize validation metrics collectors."""
        self._registry = registry or REGISTRY

        # Validation counter
        self.validation_total = Counter(
            "honeybadge_validation_total",
            "Total validation checks",
            ["level", "result"],  # level: L1|L2|L3, result: pass|fail
            registry=self._registry,
        )

        # Validation errors
        self.validation_errors_total = Counter(
            "honeybadge_validation_errors_total",
            "Total validation errors",
            ["level", "error_code"],
            registry=self._registry,
        )

        # Validation duration
        self.validation_duration_seconds = Histogram(
            "honeybadge_validation_duration_seconds",
            "Validation duration in seconds",
            ["level"],
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5),
            registry=self._registry,
        )

        # Regeneration counter (when LLM retry happens)
        self.regeneration_total = Counter(
            "honeybadge_validation_regeneration_total",
            "Total nGQL regenerations due to validation failure",
            ["level"],
            registry=self._registry,
        )

    def record_validation(
        self,
        level: str,
        passed: bool,
        duration_seconds: float,
    ) -> None:
        """Record a validation check."""
        result = "pass" if passed else "fail"
        self.validation_total.labels(level=level, result=result).inc()
        self.validation_duration_seconds.labels(level=level).observe(duration_seconds)

    def record_error(
        self,
        level: str,
        error_code: str,
    ) -> None:
        """Record a validation error."""
        self.validation_errors_total.labels(level=level, error_code=error_code).inc()

    def record_regeneration(self, level: str) -> None:
        """Record a regeneration due to validation failure."""
        self.regeneration_total.labels(level=level).inc()


# =============================================================================
# Query Metrics
# =============================================================================

class QueryMetricsCollector:
    """
    End-to-end query Prometheus metrics.

    Metrics:
    - query_total: Total queries (counter, labels: query_type, status)
    - query_duration_seconds: End-to-end query duration histogram
    - query_e2e_duration_seconds: Full chain duration including LLM+validation+execution
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        """Initialize query metrics collectors."""
        self._registry = registry or REGISTRY

        # Query counter
        self.query_total = Counter(
            "honeybadge_query_total",
            "Total queries processed",
            ["query_type", "status"],
            registry=self._registry,
        )

        # End-to-end duration
        self.query_duration_seconds = Histogram(
            "honeybadge_query_duration_seconds",
            "End-to-end query duration in seconds",
            ["query_type"],
            buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
            registry=self._registry,
        )

        # Phase durations
        self.phase_duration_seconds = Histogram(
            "honeybadge_query_phase_duration_seconds",
            "Query phase duration in seconds",
            ["phase"],  # phases: llm_generation, validation, execution, summarization
            buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
            registry=self._registry,
        )

        # Result row count
        self.query_row_count = Histogram(
            "honeybadge_query_row_count",
            "Number of rows returned per query",
            ["query_type"],
            buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000),
            registry=self._registry,
        )

        # Concurrent queries
        self.concurrent_queries = Gauge(
            "honeybadge_concurrent_queries",
            "Number of currently processing queries",
            registry=self._registry,
        )

    def record_query(
        self,
        query_type: str,
        status: str,
        duration_seconds: float,
        row_count: int = 0,
    ) -> None:
        """Record a completed query."""
        self.query_total.labels(query_type=query_type, status=status).inc()
        self.query_duration_seconds.labels(query_type=query_type).observe(duration_seconds)
        if row_count > 0:
            self.query_row_count.labels(query_type=query_type).observe(row_count)

    def record_phase(
        self,
        phase: str,
        duration_seconds: float,
    ) -> None:
        """Record a query phase duration."""
        self.phase_duration_seconds.labels(phase=phase).observe(duration_seconds)

    def increment_concurrent(self) -> None:
        """Increment concurrent query count."""
        self.concurrent_queries.inc()

    def decrement_concurrent(self) -> None:
        """Decrement concurrent query count."""
        self.concurrent_queries.dec()


# =============================================================================
# ETL Metrics
# =============================================================================

class ETLMetricsCollector:
    """
    ETL pipeline Prometheus metrics.

    Metrics:
    - etl_runs_total: Total pipeline runs (counter, labels: status, load_mode)
    - etl_records_extracted_total: Rows extracted from source (counter, labels: table, source_system)
    - etl_pipeline_duration_seconds: End-to-end pipeline duration histogram
    - etl_watermark_lag_seconds: Data freshness lag (gauge, labels: table)
    - etl_extraction_errors_total: Extraction failures (counter, labels: table, error_type)
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        """Initialize ETL metrics collectors."""
        self._registry = registry or REGISTRY

        # Pipeline run counter
        self.runs_total = Counter(
            "honeybadge_etl_runs_total",
            "Total ETL pipeline runs",
            ["status", "load_mode"],
            registry=self._registry,
        )

        # Records extracted from source
        self.records_extracted_total = Counter(
            "honeybadge_etl_records_extracted_total",
            "Total records extracted from source system",
            ["table", "source_system"],
            registry=self._registry,
        )

        # Pipeline duration
        self.pipeline_duration_seconds = Histogram(
            "honeybadge_etl_pipeline_duration_seconds",
            "ETL pipeline end-to-end duration in seconds",
            ["load_mode"],
            buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0, 1800.0, 3600.0),
            registry=self._registry,
        )

        # Watermark lag (now - MAX(source_update_time)) — data freshness
        self.watermark_lag_seconds = Gauge(
            "honeybadge_etl_watermark_lag_seconds",
            "ETL data freshness lag (now - latest source_update_time) in seconds",
            ["table"],
            registry=self._registry,
        )

        # Extraction errors
        self.extraction_errors_total = Counter(
            "honeybadge_etl_extraction_errors_total",
            "Total ETL extraction errors",
            ["table", "error_type"],
            registry=self._registry,
        )

        # Last successful run timestamp (Unix epoch seconds)
        # Used by the ETLStale alert rule. Updated only on successful runs.
        self.last_success_timestamp = Gauge(
            "honeybadge_etl_last_success_timestamp",
            "Unix timestamp of the last successful ETL pipeline run",
            registry=self._registry,
        )

    def record_run(self, status: str, load_mode: str, duration_seconds: float) -> None:
        """Record a completed pipeline run."""
        self.runs_total.labels(status=status, load_mode=load_mode).inc()
        self.pipeline_duration_seconds.labels(load_mode=load_mode).observe(duration_seconds)
        if status == "success":
            import time

            self.last_success_timestamp.set(time.time())

    def record_extraction(self, table: str, source_system: str, rows: int) -> None:
        """Record rows extracted from the source system."""
        if rows > 0:
            self.records_extracted_total.labels(
                table=table, source_system=source_system
            ).inc(rows)

    def record_extraction_error(self, table: str, error_type: str) -> None:
        """Record an extraction failure."""
        self.extraction_errors_total.labels(table=table, error_type=error_type).inc()

    def set_watermark_lag(self, table: str, lag_seconds: float) -> None:
        """Set the freshness lag for a table."""
        self.watermark_lag_seconds.labels(table=table).set(lag_seconds)


# =============================================================================
# Resilience Metrics
# =============================================================================

class ResilienceMetricsCollector:
    """Circuit breaker and resilience metrics.

    Metrics:
    - circuit_breaker_state: Breaker state as numeric gauge (labels: name)
      0=CLOSED, 1=OPEN, 2=HALF_OPEN
    - circuit_breaker_failures_total: Consecutive failure count (labels: name)
    - circuit_breaker_rejected_total: Calls rejected because breaker was OPEN (labels: name)
    """

    _STATE_VALUES = {"closed": 0, "open": 1, "half_open": 2}

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self._registry = registry or REGISTRY

        self.breaker_state = Gauge(
            "honeybadge_circuit_breaker_state",
            "Circuit breaker state (0=closed, 1=open, 2=half_open)",
            ["name"],
            registry=self._registry,
        )

        self.breaker_failures = Gauge(
            "honeybadge_circuit_breaker_failures",
            "Current consecutive failure count for circuit breakers",
            ["name"],
            registry=self._registry,
        )

        self.breaker_rejected_total = Counter(
            "honeybadge_circuit_breaker_rejected_total",
            "Total calls rejected because the circuit breaker was open",
            ["name"],
            registry=self._registry,
        )

    def update_breaker(self, name: str, state: str, failure_count: int) -> None:
        """Update metrics for a single circuit breaker.

        Args:
            name: Breaker name (e.g. "nebula", "llm", "redis").
            state: One of "closed", "open", "half_open".
            failure_count: Current consecutive failure count.
        """
        self.breaker_state.labels(name=name).set(self._STATE_VALUES.get(state, 0))
        self.breaker_failures.labels(name=name).set(failure_count)

    def record_rejected(self, name: str) -> None:
        """Record a call rejected by an open circuit breaker."""
        self.breaker_rejected_total.labels(name=name).inc()


# =============================================================================
# Global Metrics Instances
# =============================================================================

LLM_METRICS = LLMMetricsCollector()
NEBULA_METRICS = NebulaMetricsCollector()
HICLAW_METRICS = HiClawMetricsCollector()
VALIDATION_METRICS = ValidationMetricsCollector()
QUERY_METRICS = QueryMetricsCollector()
ETL_METRICS = ETLMetricsCollector()
RESILIENCE_METRICS = ResilienceMetricsCollector()
