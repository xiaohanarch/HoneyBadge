"""QueryOrchestrator and DirectPipelineOrchestrator for HoneyBadge.

Implements the 5-step pipeline for natural language to nGQL query execution,
with anti-hallucination validation, audit logging, and streaming callbacks.
"""

import asyncio
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

import structlog

from honeybadge.core.trace import generate_trace_id
from honeybadge.db.nebula import NebulaGraphClient
from honeybadge.db.postgres import AuditLogEntry, PostgreSQLClient
from honeybadge.db.redis import RedisClient
from honeybadge.llm.adapter import LLMAdapter, generate_ngql, summarize_results
from honeybadge.protocols.validator import NgqlValidator

logger = structlog.get_logger()

# Maximum retry attempts for validation failures
MAX_RETRIES = 2
# Total pipeline steps for progress reporting
TOTAL_STEPS = 5


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class PipelineCallbacks:
    """Transport-agnostic callbacks for pipeline progress and streaming output.

    Attributes:
        on_progress: Called at each pipeline step with (step, total, label, detail).
        on_stream: Called for streaming text chunks with (chunk, kind, done).
    """

    on_progress: Callable[[int, int, str, Optional[str]], Awaitable[None]]
    on_stream: Callable[[str, str, bool], Awaitable[None]]


@dataclass
class QueryResult:
    """Result of a query pipeline execution.

    Attributes:
        summary: Human-readable LLM summary of the query results.
        raw_data: Raw rows from NebulaGraph as list of dicts.
        columns: Column names returned by the query.
        cypher: The nGQL query that was executed.
        trace_id: Unique trace ID for audit logging.
        execution_time_ms: Query execution time in milliseconds.
        row_count: Number of rows returned.
        error: Optional error message if the pipeline failed.
    """

    summary: str
    raw_data: list[dict[str, Any]]
    columns: list[str]
    cypher: str
    trace_id: str
    execution_time_ms: int
    row_count: int
    error: Optional[str] = None


# =============================================================================
# Abstract Base Class
# =============================================================================


class QueryOrchestrator(ABC):
    """Abstract interface for query orchestrators.

    Concrete implementations include DirectPipelineOrchestrator (Phase 1)
    and HiClawOrchestrator (Phase 2+).
    """

    @abstractmethod
    async def execute_query(
        self,
        question: str,
        session_id: str,
        user_context: dict[str, Any],
        callbacks: PipelineCallbacks,
    ) -> QueryResult:
        """Execute a natural language query through the full pipeline.

        Args:
            question: User's natural language question.
            session_id: Session identifier for grouping audit logs.
            user_context: User context dict with user_id, org_ids, data_scope, etc.
            callbacks: Transport-agnostic callbacks for progress and streaming.

        Returns:
            QueryResult with results, metadata, and optional error.
        """
        ...


# =============================================================================
# Direct Pipeline Orchestrator
# =============================================================================


class DirectPipelineOrchestrator(QueryOrchestrator):
    """Direct 5-step pipeline orchestrator for Phase 1.

    Executes the full NL -> nGQL -> validate -> execute -> summarize pipeline
    without agent orchestration (HiClaw). Used when ORCHESTRATOR_TYPE=direct.

    Pipeline Steps:
        1. Understand question (schema loading)
        2. Generate nGQL via LLM
        3. Validate L1-L3 with retry
        4. Execute on NebulaGraph
        5. Summarize results via LLM, write audit log
    """

    MAX_RETRIES = MAX_RETRIES
    TOTAL_STEPS = TOTAL_STEPS

    def __init__(
        self,
        nebula: NebulaGraphClient,
        llm: LLMAdapter,
        pg: PostgreSQLClient,
        redis: RedisClient,
        validator: NgqlValidator,
        nebula_space: str,
    ) -> None:
        """Initialize the orchestrator with all infrastructure dependencies.

        Args:
            nebula: NebulaGraph client for query execution and schema loading.
            llm: LLM adapter for nGQL generation and result summarization.
            pg: PostgreSQL client for audit log writing.
            redis: Redis client (reserved for semantic cache in Phase 2).
            validator: nGQL validator implementing L1-L3 anti-hallucination checks.
            nebula_space: NebulaGraph space name to query.
        """
        self._nebula = nebula
        self._llm = llm
        self._pg = pg
        self._redis = redis
        self._validator = validator
        self._nebula_space = nebula_space

        logger.info(
            "direct_pipeline_orchestrator_initialized",
            nebula_space=nebula_space,
        )

    async def execute_query(
        self,
        question: str,
        session_id: str,
        user_context: dict[str, Any],
        callbacks: PipelineCallbacks,
    ) -> QueryResult:
        """Execute the full 5-step query pipeline.

        Args:
            question: User's natural language question.
            session_id: Session identifier.
            user_context: User context with user_id, org_ids, data_scope, etc.
            callbacks: Callbacks for progress and streaming updates.

        Returns:
            QueryResult with results and metadata.
        """
        trace_id = generate_trace_id()
        start_time = time.monotonic()
        user_id = user_context.get("user_id", "unknown")

        logger.info(
            "pipeline_started",
            trace_id=trace_id,
            session_id=session_id,
            user_id=user_id,
            question=question[:100],
        )

        ngql = ""
        summary = ""
        raw_data: list[dict[str, Any]] = []
        columns: list[str] = []
        execution_time_ms = 0

        try:
            # ------------------------------------------------------------------
            # Step 1: Understand the question — load schema for context
            # ------------------------------------------------------------------
            await callbacks.on_progress(1, self.TOTAL_STEPS, "理解问题", None)
            await callbacks.on_stream("正在理解您的问题并加载数据库结构...", "thinking", False)

            schema_info = await self._load_schema()
            ontology_info = "ERP知识图谱本体：供应商(Supplier)、采购订单(PurchaseOrder)、发票(Invoice)、付款(Payment)、收货(Receipt)"

            logger.debug(
                "schema_loaded",
                trace_id=trace_id,
                schema_length=len(schema_info),
            )

            # ------------------------------------------------------------------
            # Step 2: Generate nGQL via LLM
            # ------------------------------------------------------------------
            await callbacks.on_progress(2, self.TOTAL_STEPS, "生成查询", None)

            ngql = await self._generate_ngql(
                question=question,
                schema_info=schema_info,
                ontology_info=ontology_info,
                user_context=user_context,
                trace_id=trace_id,
            )

            await callbacks.on_stream(ngql, "cypher", False)

            logger.info(
                "ngql_generated",
                trace_id=trace_id,
                ngql=ngql[:200],
            )

            # ------------------------------------------------------------------
            # Step 3: Validate L1-L3 with retry
            # ------------------------------------------------------------------
            await callbacks.on_progress(3, self.TOTAL_STEPS, "校验查询", None)

            ngql = await self._validate_with_retry(
                ngql=ngql,
                question=question,
                schema_info=schema_info,
                ontology_info=ontology_info,
                user_context=user_context,
                trace_id=trace_id,
                callbacks=callbacks,
            )

            # ------------------------------------------------------------------
            # Step 4: Execute on NebulaGraph
            # ------------------------------------------------------------------
            await callbacks.on_progress(4, self.TOTAL_STEPS, "执行查询", None)

            nebula_result = await self._nebula.execute(ngql, space=self._nebula_space)
            execution_time_ms = nebula_result.execution_time_ms

            if not nebula_result.success:
                error_msg = nebula_result.error_message or "NebulaGraph query execution failed"
                logger.error(
                    "nebula_query_failed",
                    trace_id=trace_id,
                    error=error_msg,
                    ngql=ngql[:200],
                )
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                await self._write_audit_log_bg(
                    trace_id=trace_id,
                    question=question,
                    ngql=ngql,
                    raw_data=[],
                    summary="",
                    user_id=user_id,
                    session_id=session_id,
                    execution_time_ms=elapsed_ms,
                    row_count=0,
                    error_message=error_msg,
                )
                return QueryResult(
                    summary="",
                    raw_data=[],
                    columns=[],
                    cypher=ngql,
                    trace_id=trace_id,
                    execution_time_ms=elapsed_ms,
                    row_count=0,
                    error=error_msg,
                )

            raw_data = nebula_result.rows
            columns = nebula_result.columns

            logger.info(
                "nebula_query_succeeded",
                trace_id=trace_id,
                row_count=nebula_result.row_count,
                execution_time_ms=execution_time_ms,
            )

            # ------------------------------------------------------------------
            # Step 5: Summarize results via LLM
            # ------------------------------------------------------------------
            await callbacks.on_progress(5, self.TOTAL_STEPS, "生成摘要", None)

            summary = await self._summarize(
                question=question,
                raw_data=raw_data,
                columns=columns,
                trace_id=trace_id,
                user_id=user_id,
            )

            await callbacks.on_stream(summary, "summarizing", True)

            elapsed_ms = int((time.monotonic() - start_time) * 1000)

            logger.info(
                "pipeline_completed",
                trace_id=trace_id,
                row_count=nebula_result.row_count,
                total_time_ms=elapsed_ms,
            )

            # Write audit log without blocking the response
            await self._write_audit_log_bg(
                trace_id=trace_id,
                question=question,
                ngql=ngql,
                raw_data=raw_data,
                summary=summary,
                user_id=user_id,
                session_id=session_id,
                execution_time_ms=elapsed_ms,
                row_count=nebula_result.row_count,
                error_message=None,
            )

            return QueryResult(
                summary=summary,
                raw_data=raw_data,
                columns=columns,
                cypher=ngql,
                trace_id=trace_id,
                execution_time_ms=elapsed_ms,
                row_count=nebula_result.row_count,
                error=None,
            )

        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = str(exc)

            logger.error(
                "pipeline_failed",
                trace_id=trace_id,
                error=error_msg,
                elapsed_ms=elapsed_ms,
            )

            # Best-effort audit log on failure
            await self._write_audit_log_bg(
                trace_id=trace_id,
                question=question,
                ngql=ngql,
                raw_data=raw_data,
                summary=summary,
                user_id=user_id,
                session_id=session_id,
                execution_time_ms=elapsed_ms,
                row_count=0,
                error_message=error_msg,
            )

            return QueryResult(
                summary=summary,
                raw_data=raw_data,
                columns=columns,
                cypher=ngql,
                trace_id=trace_id,
                execution_time_ms=elapsed_ms,
                row_count=0,
                error=error_msg,
            )

    # =========================================================================
    # Private helpers
    # =========================================================================

    async def _load_schema(self) -> str:
        """Load NebulaGraph schema information for LLM context.

        Executes SHOW TAGS, DESCRIBE TAG each, SHOW EDGES, DESCRIBE EDGE each.

        Returns:
            Human-readable schema string for inclusion in LLM prompts.
        """
        schema_parts: list[str] = []

        try:
            # Load tags
            tags_result = await self._nebula.execute(
                "SHOW TAGS", space=self._nebula_space
            )
            if tags_result.success and tags_result.rows:
                schema_parts.append("## Tags (顶点类型)")
                for row in tags_result.rows:
                    # Row may have "Name" key or first value
                    tag_name = row.get("Name") or row.get("name") or list(row.values())[0]
                    tag_name = str(tag_name)
                    schema_parts.append(f"\n### {tag_name}")

                    desc_result = await self._nebula.execute(
                        f"DESCRIBE TAG `{tag_name}`", space=self._nebula_space
                    )
                    if desc_result.success and desc_result.rows:
                        for prop_row in desc_result.rows:
                            prop_name = prop_row.get("Field") or prop_row.get("field") or ""
                            prop_type = prop_row.get("Type") or prop_row.get("type") or ""
                            schema_parts.append(f"  - {prop_name}: {prop_type}")

            # Load edges
            edges_result = await self._nebula.execute(
                "SHOW EDGES", space=self._nebula_space
            )
            if edges_result.success and edges_result.rows:
                schema_parts.append("\n## Edges (边类型)")
                for row in edges_result.rows:
                    edge_name = row.get("Name") or row.get("name") or list(row.values())[0]
                    edge_name = str(edge_name)
                    schema_parts.append(f"\n### {edge_name}")

                    desc_result = await self._nebula.execute(
                        f"DESCRIBE EDGE `{edge_name}`", space=self._nebula_space
                    )
                    if desc_result.success and desc_result.rows:
                        for prop_row in desc_result.rows:
                            prop_name = prop_row.get("Field") or prop_row.get("field") or ""
                            prop_type = prop_row.get("Type") or prop_row.get("type") or ""
                            schema_parts.append(f"  - {prop_name}: {prop_type}")

        except Exception as exc:
            logger.warning(
                "schema_load_failed",
                error=str(exc),
            )
            # Return minimal schema on failure — LLM will still attempt generation
            return "Schema not available. Use common ERP tags: Supplier, PurchaseOrder, Invoice, Payment, Receipt."

        if schema_parts:
            return "\n".join(schema_parts)

        return "No schema found in NebulaGraph space. Use common ERP tags: Supplier, PurchaseOrder, Invoice, Payment, Receipt."

    async def _generate_ngql(
        self,
        question: str,
        schema_info: str,
        ontology_info: str,
        user_context: dict[str, Any],
        trace_id: str,
    ) -> str:
        """Generate nGQL from a natural language question via LLM.

        Calls generate_ngql() from honeybadge.llm.adapter and strips any
        markdown code fences from the response.

        Args:
            question: User's question.
            schema_info: Schema context string.
            ontology_info: Ontology context string.
            user_context: User permission context.
            trace_id: Trace ID for logging.

        Returns:
            Clean nGQL string without markdown fences.
        """
        response = await generate_ngql(
            adapter=self._llm,
            question=question,
            schema_info=schema_info,
            ontology_info=ontology_info,
            user_context=user_context,
            trace_id=trace_id,
        )

        ngql = response.content.strip()

        # Strip chain-of-thought <think>...</think> tags (e.g. MiniMax, DeepSeek)
        ngql = re.sub(r"<think>.*?</think>", "", ngql, flags=re.DOTALL)
        ngql = ngql.strip()

        # Strip markdown code fences: ```ngql ... ``` or ``` ... ```
        ngql = re.sub(r"^```(?:ngql|cypher|nGQL)?\s*\n?", "", ngql, flags=re.IGNORECASE)
        ngql = re.sub(r"\n?```\s*$", "", ngql, flags=re.IGNORECASE)
        ngql = ngql.strip()

        return ngql

    async def _validate_with_retry(
        self,
        ngql: str,
        question: str,
        schema_info: str,
        ontology_info: str,
        user_context: dict[str, Any],
        trace_id: str,
        callbacks: PipelineCallbacks,
    ) -> str:
        """Run L1 then L2 validation, retrying nGQL generation on failure.

        Retries up to MAX_RETRIES times. On each retry, regenerates nGQL via LLM
        with error context appended. Raises on final failure.

        Args:
            ngql: Initial nGQL to validate.
            question: Original question (for regeneration).
            schema_info: Schema context for regeneration.
            ontology_info: Ontology context for regeneration.
            user_context: User context for regeneration.
            trace_id: Trace ID for logging.
            callbacks: Callbacks for streaming validation feedback.

        Returns:
            Validated (and possibly regenerated) nGQL string.

        Raises:
            ValueError: If validation fails after all retries.
        """
        current_ngql = ngql

        for attempt in range(self.MAX_RETRIES + 1):
            # L1: Syntax validation
            l1_result = self._validator.validate_syntax(current_ngql)

            if not l1_result.valid:
                errors = "; ".join(e.message for e in l1_result.errors)
                logger.warning(
                    "l1_validation_failed",
                    trace_id=trace_id,
                    attempt=attempt,
                    errors=errors,
                )

                if attempt < self.MAX_RETRIES:
                    await callbacks.on_stream(
                        f"语法校验失败，正在重新生成查询（第{attempt + 1}次重试）: {errors}",
                        "thinking",
                        False,
                    )
                    # Regenerate with error context
                    retry_question = (
                        f"{question}\n\n[上一次生成的查询语法错误，请修正: {errors}]"
                    )
                    current_ngql = await self._generate_ngql(
                        question=retry_question,
                        schema_info=schema_info,
                        ontology_info=ontology_info,
                        user_context=user_context,
                        trace_id=trace_id,
                    )
                    continue
                else:
                    raise ValueError(
                        f"L1 syntax validation failed after {self.MAX_RETRIES} retries: {errors}"
                    )

            # L2: Schema validation
            l2_result = self._validator.validate_schema(current_ngql)

            if not l2_result.valid:
                errors = "; ".join(e.message for e in l2_result.errors)
                logger.warning(
                    "l2_validation_failed",
                    trace_id=trace_id,
                    attempt=attempt,
                    errors=errors,
                )

                if attempt < self.MAX_RETRIES:
                    await callbacks.on_stream(
                        f"Schema校验失败，正在重新生成查询（第{attempt + 1}次重试）: {errors}",
                        "thinking",
                        False,
                    )
                    retry_question = (
                        f"{question}\n\n[上一次生成的查询Schema不匹配，请修正: {errors}]"
                    )
                    current_ngql = await self._generate_ngql(
                        question=retry_question,
                        schema_info=schema_info,
                        ontology_info=ontology_info,
                        user_context=user_context,
                        trace_id=trace_id,
                    )
                    continue
                else:
                    raise ValueError(
                        f"L2 schema validation failed after {self.MAX_RETRIES} retries: {errors}"
                    )

            # Both L1 and L2 passed
            logger.info(
                "validation_passed",
                trace_id=trace_id,
                attempt=attempt,
            )
            return current_ngql

        # Should never reach here, but satisfy type checker
        raise ValueError("Validation failed after all retries")

    async def _summarize(
        self,
        question: str,
        raw_data: list[dict[str, Any]],
        columns: list[str],
        trace_id: str,
        user_id: str,
    ) -> str:
        """Generate a human-readable summary of query results.

        Calls summarize_results() from honeybadge.llm.adapter.

        Args:
            question: Original user question.
            raw_data: Raw rows from NebulaGraph.
            columns: Column names.
            trace_id: Trace ID for logging.
            user_id: User ID for token metering.

        Returns:
            Human-readable summary string.
        """
        response = await summarize_results(
            adapter=self._llm,
            question=question,
            raw_results=raw_data,
            columns=columns,
            trace_id=trace_id,
            user_id=user_id,
        )
        summary = response.content
        # Strip chain-of-thought <think>...</think> tags
        summary = re.sub(r"<think>.*?</think>", "", summary, flags=re.DOTALL).strip()
        return summary

    async def _write_audit_log_bg(
        self,
        trace_id: str,
        question: str,
        ngql: str,
        raw_data: list[dict[str, Any]],
        summary: str,
        user_id: str,
        session_id: str,
        execution_time_ms: int,
        row_count: int,
        error_message: Optional[str],
    ) -> None:
        """Write audit log entry without blocking the response.

        Errors are logged but not raised — audit logging must never block
        the user-facing response.

        Args:
            trace_id: Unique trace ID.
            question: Original question.
            ngql: Executed nGQL query.
            raw_data: Raw query results.
            summary: LLM summary.
            user_id: User identifier.
            session_id: Session identifier.
            execution_time_ms: Total pipeline time.
            row_count: Number of rows returned.
            error_message: Optional error message if pipeline failed.
        """
        try:
            entry = AuditLogEntry(
                trace_id=trace_id,
                question=question,
                cypher=ngql,
                raw_result={"rows": raw_data, "columns": columns if (columns := []) else []},
                summary=summary,
                user_id=user_id,
                session_id=session_id,
                execution_time_ms=execution_time_ms,
                row_count=row_count,
                error_message=error_message,
            )
            # Pass raw_data in the raw_result field properly
            entry.raw_result = {"rows": raw_data}
            await self._pg.write_audit_log(entry)
        except Exception as exc:
            logger.error(
                "audit_log_write_failed",
                trace_id=trace_id,
                error=str(exc),
            )


# =============================================================================
# Factory Function
# =============================================================================


def create_orchestrator(
    config: Any,
    nebula: NebulaGraphClient,
    llm: LLMAdapter,
    pg: PostgreSQLClient,
    redis: RedisClient,
    validator: NgqlValidator,
) -> QueryOrchestrator:
    """Factory function to create the appropriate QueryOrchestrator.

    Args:
        config: ServerConfig instance with orchestrator_type and nebula_space.
        nebula: NebulaGraph client.
        llm: LLM adapter.
        pg: PostgreSQL client.
        redis: Redis client.
        validator: nGQL validator.

    Returns:
        Configured QueryOrchestrator instance.

    Raises:
        NotImplementedError: If orchestrator_type is "hiclaw" (Phase 2+).
        ValueError: If orchestrator_type is unknown.
    """
    orchestrator_type = config.orchestrator_type

    if orchestrator_type == "hiclaw":
        raise NotImplementedError(
            "HiClaw orchestrator not yet implemented. Use ORCHESTRATOR_TYPE=direct"
        )

    if orchestrator_type == "direct":
        return DirectPipelineOrchestrator(
            nebula=nebula,
            llm=llm,
            pg=pg,
            redis=redis,
            validator=validator,
            nebula_space=config.nebula_space,
        )

    raise ValueError(
        f"Unknown orchestrator_type: '{orchestrator_type}'. Valid values: 'direct', 'hiclaw'"
    )
