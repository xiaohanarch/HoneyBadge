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


if __name__ == "__main__":
    import argparse
    import json
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(
        prog="decompose",
        description="Multi-step analysis: decompose questions or cross-reference results",
    )
    sub = parser.add_subparsers(dest="command", required=False)

    # Default (no subcommand): decompose mode
    parser.add_argument(
        "--question",
        help="Complex question to decompose into sub-queries",
    )

    # cross-reference subcommand
    xref = sub.add_parser("cross-reference", help="Cross-reference results from multiple rounds")
    xref.add_argument(
        "--results-dir",
        default="/tmp/",
        help="Directory containing mcp_execute.json result files",
    )

    args = parser.parse_args()

    if args.command == "cross-reference":
        results_dir = Path(args.results_dir)
        results: list[QueryResult] = []
        for json_file in sorted(results_dir.glob("mcp_execute*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                results.append(QueryResult(
                    trace_id=data.get("trace_id", ""),
                    ngql=data.get("ngql", ""),
                    columns=data.get("columns", []),
                    rows=data.get("rows", []),
                    row_count=data.get("row_count", 0),
                    execution_time_ms=data.get("execution_time_ms", 0),
                    success=data.get("success", True),
                ))
            except (json.JSONDecodeError, KeyError) as exc:
                print(f"Skip {json_file.name}: {exc}", file=sys.stderr)
        patterns = cross_reference(results)
        print(json.dumps(patterns, ensure_ascii=False, indent=2))
    elif args.question:
        client = MCPClient()
        sub_queries = decompose(args.question, client)
        print(json.dumps(
            [{"description": sq.description, "question": sq.question, "round": sq.round} for sq in sub_queries],
            ensure_ascii=False, indent=2,
        ))
    else:
        parser.print_help(sys.stderr)
        sys.exit(2)
