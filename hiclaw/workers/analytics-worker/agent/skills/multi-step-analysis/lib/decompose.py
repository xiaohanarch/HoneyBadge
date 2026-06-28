"""Question decomposition and cross-reference for multi-step analysis."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from common.mcp_client import MCPClient, QueryResult


@dataclass(frozen=True)
class SubQuery:
    """A single sub-query in a decomposition."""
    description: str
    question: str
    round: int


def decompose(question: str, client: MCPClient) -> list[SubQuery]:
    """Decompose a complex question into 2-5 sub-queries.

    Uses the LLM (via generate_query) to break the question into parts,
    then assigns round numbers for sequential execution.
    """
    response = client.generate_query(question)
    sub_questions: list[str] = response.get("sub_questions", [])
    if not sub_questions:
        # Fallback: single sub-query
        sub_questions = [question]

    # Clamp to maximum 5 sub-queries
    if len(sub_questions) > 5:
        sub_questions = sub_questions[:5]

    return [
        SubQuery(
            description=sq,
            question=sq,
            round=i + 1,
        )
        for i, sq in enumerate(sub_questions)
    ]


def cross_reference(results: list[QueryResult]) -> dict[str, Any]:
    """Find patterns across sub-query results.

    Identifies trends, deltas, and anomalies across multiple query results.
    """
    patterns: dict[str, Any] = {"trends": [], "deltas": []}

    if len(results) < 2:
        return patterns

    # Compare consecutive results for trend patterns
    for i in range(len(results) - 1):
        current = results[i].rows
        next_result = results[i + 1].rows
        if current and next_result:
            comparison = compare_trends(current, next_result)
            if comparison["direction"] != "stable":
                patterns["trends"].append({
                    "from_round": i + 1,
                    "to_round": i + 2,
                    **comparison,
                })

    return patterns


def compare_trends(
    baseline: list[dict], comparison: list[dict]
) -> dict[str, Any]:
    """Compare two result sets and return trend direction.

    Looks for numeric 'amount' fields and compares sums.
    """
    if not baseline or not comparison:
        return {"direction": "unknown", "change_percent": 0.0}

    baseline_sum = sum(float(r.get("amount", 0)) for r in baseline)
    comparison_sum = sum(float(r.get("amount", 0)) for r in comparison)

    if baseline_sum == 0:
        return {"direction": "unknown", "change_percent": 0.0}

    change_percent = ((comparison_sum - baseline_sum) / baseline_sum) * 100

    if abs(change_percent) < 1.0:
        direction = "stable"
    elif change_percent > 0:
        direction = "increase"
    else:
        direction = "decrease"

    return {
        "direction": direction,
        "change_percent": round(change_percent, 2),
        "baseline_sum": baseline_sum,
        "comparison_sum": comparison_sum,
    }
