"""Graph Worker implementation for nGQL query generation and execution."""

import time
from typing import Any, Optional

import structlog

from honeybadge.core.trace import generate_trace_id

logger = structlog.get_logger()


class GraphWorkerSkill:
    """
    Graph Worker Skill for processing natural language queries.

    Flow:
    1. Receive user question
    2. Load schema prompt template
    3. Call LLM to generate nGQL
    4. L1: Syntax validation
    5. L2: Schema compliance validation
    6. L3: Permission validation (reserved)
    7. Execute nGQL on NebulaGraph
    8. Generate natural language summary
    9. Write audit log
    10. Return result
    """

    def __init__(
        self,
        nebula_server,
        llm_server,
        redis_server,
        schema: Optional[str] = None,
    ):
        """
        Initialize Graph Worker Skill.

        Args:
            nebula_server: NebulaGraph MCP Server instance
            llm_server: LLM MCP Server instance
            redis_server: Redis MCP Server instance
            schema: Optional schema string for prompt generation
        """
        self.nebula_server = nebula_server
        self.llm_server = llm_server
        self.redis_server = redis_server
        self.schema = schema or ""

    async def cypher_query(
        self,
        user_question: str,
        session_context: Optional[dict[str, Any]] = None,
        user_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Process a natural language query and return results.

        Args:
            user_question: User's natural language question
            session_context: Optional session context
            user_context: Optional user context for L3 permission validation

        Returns:
            Dict with summary, raw_data, cypher, trace_id, execution_time_ms, row_count
        """
        trace_id = generate_trace_id()
        start_time = time.time()

        logger.info(
            "cypher_query_start",
            trace_id=trace_id,
            question=user_question[:100],
        )

        session_context = session_context or {}
        user_context = user_context or {}

        try:
            # Step 1: Get schema for prompt
            if not self.schema:
                schema_info = await self.nebula_server.get_schema()
                self.schema = self._format_schema_for_prompt(schema_info)

            # Step 2: Generate nGQL using LLM
            llm_response = await self.llm_server.generate_cypher(
                question=user_question,
                schema=self.schema,
                context=session_context,
            )

            if not llm_response.success:
                raise Exception(f"LLM generation failed: {llm_response.error_message}")

            ngql = llm_response.content.strip()
            logger.info("ngql_generated", trace_id=trace_id, ngql=ngql)

            # Step 3: L1 - Syntax validation
            syntax_result = await self.nebula_server.validate_ngql(ngql)
            if not syntax_result.valid:
                error_msg = f"Syntax validation failed: {', '.join(syntax_result.errors)}"
                logger.warning("l1_validation_failed", trace_id=trace_id, errors=syntax_result.errors)
                # Retry with error feedback (max 3 retries handled by caller)
                raise Exception(error_msg)

            # Step 4: L2 - Schema validation (would use validator here)
            # Step 5: L3 - Permission validation (reserved for Phase 1)

            # Step 6: Execute query
            query_result = await self.nebula_server.execute_ngql(ngql)

            if not query_result.success:
                raise Exception(f"Query execution failed: {query_result.error_message}")

            execution_time_ms = int((time.time() - start_time) * 1000)

            # Step 7: Generate summary
            summary_response = await self.llm_server.summarize_result(
                result={
                    "columns": query_result.columns,
                    "rows": query_result.rows,
                    "row_count": query_result.row_count,
                },
                question=user_question,
                cypher=ngql,
            )

            summary = summary_response.content if summary_response.success else "摘要生成失败"

            # Step 8: Cache result (optional)
            if self.redis_server:
                cache_key = f"query:{trace_id}"
                await self.redis_server.cache_result(
                    key=cache_key,
                    value={
                        "ngql": ngql,
                        "result": query_result.rows,
                        "summary": summary,
                    },
                    ttl=300,  # 5 minutes
                )

            logger.info(
                "cypher_query_complete",
                trace_id=trace_id,
                execution_time_ms=execution_time_ms,
                row_count=query_result.row_count,
            )

            return {
                "summary": summary,
                "raw_data": query_result.rows,
                "columns": query_result.columns,
                "cypher": ngql,
                "trace_id": trace_id,
                "execution_time_ms": execution_time_ms,
                "row_count": query_result.row_count,
            }

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "cypher_query_error",
                trace_id=trace_id,
                error=str(e),
                execution_time_ms=execution_time_ms,
            )

            return {
                "summary": f"查询处理失败: {str(e)}",
                "raw_data": [],
                "columns": [],
                "cypher": "",
                "trace_id": trace_id,
                "execution_time_ms": execution_time_ms,
                "row_count": 0,
                "error": str(e),
            }

    def _format_schema_for_prompt(self, schema_info) -> str:
        """
        Format schema information for prompt injection.

        Args:
            schema_info: SchemaInfo from nebula_server.get_schema()

        Returns:
            Formatted schema string
        """
        lines = [f"Space: {schema_info.space_name}", "", "Tags:"]

        for tag in schema_info.tags:
            lines.append(f"  - {tag['name']} (")
            for prop in tag.get("properties", []):
                lines.append(f"      {prop['name']}: {prop['type']}")
            lines.append("  )")

        lines.append("", "Edges:")
        for edge in schema_info.edges:
            lines.append(f"  - {edge['name']} (")
            for prop in edge.get("properties", []):
                lines.append(f"      {prop['name']}: {prop['type']}")
            lines.append("  )")

        return "\n".join(lines)
