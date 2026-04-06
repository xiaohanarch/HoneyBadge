"""Analytics Worker implementation for multi-step analysis."""

import time
from typing import Any, Optional

import structlog

from honeybadge.core.trace import generate_trace_id

logger = structlog.get_logger()


class AnalyticsWorkerSkill:
    """
    Analytics Worker Skill for complex multi-step analysis.

    Flow:
    1. Receive complex analysis question
    2. Analyze question type (anomaly_detection / trend / comparison)
    3. Decompose into sub-questions
    4. Execute sequential queries
    5. Collect and integrate intermediate results
    6. Generate analysis conclusion
    7. Return comprehensive report
    """

    def __init__(
        self,
        nebula_server,
        llm_server,
        redis_server,
        graph_worker_skill=None,
    ):
        """
        Initialize Analytics Worker Skill.

        Args:
            nebula_server: NebulaGraph MCP Server instance
            llm_server: LLM MCP Server instance
            redis_server: Redis MCP Server instance
            graph_worker_skill: Optional GraphWorkerSkill for delegated queries
        """
        self.nebula_server = nebula_server
        self.llm_server = llm_server
        self.redis_server = redis_server
        self.graph_worker_skill = graph_worker_skill

    async def multi_step_analysis(
        self,
        user_question: str,
        analysis_type: Optional[str] = None,
        session_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Perform multi-step analysis on a complex question.

        Args:
            user_question: Complex analysis question
            analysis_type: Type of analysis (anomaly_detection, trend, comparison)
            session_context: Optional session context

        Returns:
            Dict with report, steps (list of sub-query results), trace_id
        """
        trace_id = generate_trace_id()
        start_time = time.time()

        logger.info(
            "multi_step_analysis_start",
            trace_id=trace_id,
            question=user_question[:100],
            analysis_type=analysis_type,
        )

        session_context = session_context or {}

        try:
            # Step 1: Determine analysis type if not provided
            if not analysis_type:
                query_type = await self.llm_server.classify_query(user_question)
                if query_type.value == "analytics":
                    # Further classify analytics type
                    analysis_type = self._infer_analysis_type(user_question)
                else:
                    analysis_type = "general"

            # Step 2: Decompose question into sub-queries based on analysis type
            sub_queries = await self._decompose_question(user_question, analysis_type)

            logger.info(
                "question_decomposed",
                trace_id=trace_id,
                sub_query_count=len(sub_queries),
            )

            # Step 3: Execute sub-queries and collect results
            steps = []
            intermediate_results = []

            for i, sub_query in enumerate(sub_queries):
                step_start = time.time()

                logger.info(
                    "executing_sub_query",
                    trace_id=trace_id,
                    step=i + 1,
                    sub_query=sub_query["question"][:100],
                )

                try:
                    # Execute sub-query (delegate to graph worker if available)
                    if self.graph_worker_skill:
                        result = await self.graph_worker_skill.cypher_query(
                            user_question=sub_query["question"],
                            session_context=session_context,
                        )
                    else:
                        # Direct execution
                        result = await self._execute_single_query(sub_query["question"])

                    step_time_ms = int((time.time() - step_start) * 1000)

                    step_result = {
                        "step_number": i + 1,
                        "question": sub_query["question"],
                        "ngql": result.get("cypher", ""),
                        "raw_data": result.get("raw_data", []),
                        "row_count": result.get("row_count", 0),
                        "execution_time_ms": step_time_ms,
                        "success": "error" not in result,
                    }

                    steps.append(step_result)
                    intermediate_results.append(result)

                    # Cache intermediate result
                    if self.redis_server:
                        await self.redis_server.cache_result(
                            key=f"analysis:{trace_id}:step_{i + 1}",
                            value=step_result,
                            ttl=600,  # 10 minutes
                        )

                except Exception as e:
                    logger.error(
                        "sub_query_failed",
                        trace_id=trace_id,
                        step=i + 1,
                        error=str(e),
                    )
                    steps.append({
                        "step_number": i + 1,
                        "question": sub_query["question"],
                        "error": str(e),
                        "success": False,
                    })

            # Step 4: Integrate results and generate final report
            report = await self._generate_report(
                user_question=user_question,
                analysis_type=analysis_type,
                steps=steps,
                intermediate_results=intermediate_results,
            )

            execution_time_ms = int((time.time() - start_time) * 1000)

            logger.info(
                "multi_step_analysis_complete",
                trace_id=trace_id,
                execution_time_ms=execution_time_ms,
                step_count=len(steps),
            )

            return {
                "report": report,
                "steps": steps,
                "trace_id": trace_id,
                "execution_time_ms": execution_time_ms,
            }

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "multi_step_analysis_error",
                trace_id=trace_id,
                error=str(e),
                execution_time_ms=execution_time_ms,
            )

            return {
                "report": f"分析失败: {str(e)}",
                "steps": [],
                "trace_id": trace_id,
                "execution_time_ms": execution_time_ms,
                "error": str(e),
            }

    async def _execute_single_query(self, question: str) -> dict[str, Any]:
        """Execute a single query directly."""
        # Get schema
        schema_info = await self.nebula_server.get_schema()
        schema = self._format_schema(schema_info)

        # Generate nGQL
        llm_response = await self.llm_server.generate_cypher(
            question=question,
            schema=schema,
        )

        if not llm_response.success:
            raise Exception(f"LLM generation failed: {llm_response.error_message}")

        ngql = llm_response.content.strip()

        # Execute
        query_result = await self.nebula_server.execute_ngql(ngql)

        return {
            "summary": "",
            "raw_data": query_result.rows,
            "columns": query_result.columns,
            "cypher": ngql,
            "row_count": query_result.row_count,
        }

    async def _decompose_question(
        self,
        question: str,
        analysis_type: str,
    ) -> list[dict[str, Any]]:
        """
        Decompose a complex question into sub-questions.

        Args:
            question: Complex question
            analysis_type: Type of analysis

        Returns:
            List of sub-query dicts with 'question' and 'purpose'
        """
        # For Phase 1, use simple rule-based decomposition
        # Phase 2+ would use LLM for intelligent decomposition

        if analysis_type == "anomaly_detection":
            # Three-way matching anomaly detection
            return [
                {
                    "question": "找出最近一个月三单匹配状态为 UNMATCHED 或 PARTIAL 的采购订单",
                    "purpose": "找出异常匹配记录",
                },
                {
                    "question": "对于上述订单，找出对应的发票和收货记录",
                    "purpose": "获取完整三单信息",
                },
                {
                    "question": "分析异常金额差异的分布情况",
                    "purpose": "分析异常模式",
                },
            ]

        elif analysis_type == "trend":
            # Trend analysis
            return [
                {
                    "question": "按月统计过去6个月的采购金额趋势",
                    "purpose": "采购趋势",
                },
                {
                    "question": "按月统计过去6个月的发货金额趋势",
                    "purpose": "销售趋势",
                },
                {
                    "question": "对比采购和销售的月度变化",
                    "purpose": "对比分析",
                },
            ]

        elif analysis_type == "comparison":
            # Comparison analysis
            return [
                {
                    "question": "按供应商统计采购金额排名前10的供应商",
                    "purpose": "供应商采购排名",
                },
                {
                    "question": "按物料分类统计采购金额",
                    "purpose": "物料采购分布",
                },
                {
                    "question": "找出采购金额异常高或低的物料",
                    "purpose": "异常物料识别",
                },
            ]

        else:
            # General analysis - single query
            return [
                {
                    "question": question,
                    "purpose": "general",
                },
            ]

    async def _generate_report(
        self,
        user_question: str,
        analysis_type: str,
        steps: list[dict[str, Any]],
        intermediate_results: list[dict[str, Any]],
    ) -> str:
        """Generate final analysis report from steps and results."""
        # Combine all results and generate summary
        total_rows = sum(s.get("row_count", 0) for s in steps if s.get("success"))
        total_time = sum(s.get("execution_time_ms", 0) for s in steps)

        prompt = f"""根据以下多步分析结果，生成一份完整的分析报告。

原始问题：{user_question}
分析类型：{analysis_type}

执行步骤：
"""

        for step in steps:
            if step.get("success"):
                prompt += f"""
步骤 {step['step_number']}: {step['question']}
- 查询结果: {step['row_count']} 条记录
- 执行时间: {step['execution_time_ms']} ms
"""
            else:
                prompt += f"""
步骤 {step['step_number']}: {step['question']}
- 状态: 失败 - {step.get('error', 'Unknown error')}
"""

        prompt += f"""
汇总：
- 总数据量: {total_rows} 条
- 总执行时间: {total_time} ms

请生成一份简洁的分析报告，总结主要发现。
"""

        # Call LLM to generate report
        llm_response = await self.llm_server.summarize_result(
            result={
                "steps": steps,
                "total_rows": total_rows,
            },
            question=user_question,
            cypher=prompt,
        )

        if llm_response.success:
            return llm_response.content

        return f"分析完成，共处理 {total_rows} 条数据，耗时 {total_time} ms"

    def _infer_analysis_type(self, question: str) -> str:
        """Infer analysis type from question keywords."""
        question_lower = question.lower()

        if any(kw in question_lower for kw in ["异常", "虚假", "欺诈", "fraud", "anomaly"]):
            return "anomaly_detection"
        elif any(kw in question_lower for kw in ["趋势", "变化", "对比", "trend", "compare"]):
            return "comparison"
        elif any(kw in question_lower for kw in ["统计", "分析", "分析", "analyze"]):
            return "trend"

        return "general"

    def _format_schema(self, schema_info) -> str:
        """Format schema for prompt."""
        # Similar to graph_worker implementation
        lines = [f"Space: {schema_info.space_name}", "", "Tags:"]

        for tag in schema_info.tags:
            lines.append(f"  - {tag['name']}")
            for prop in tag.get("properties", []):
                lines.append(f"      {prop['name']}: {prop['type']}")

        lines.append("", "Edges:")
        for edge in schema_info.edges:
            lines.append(f"  - {edge['name']}")
            for prop in edge.get("properties", []):
                lines.append(f"      {prop['name']}: {prop['type']}")

        return "\n".join(lines)
