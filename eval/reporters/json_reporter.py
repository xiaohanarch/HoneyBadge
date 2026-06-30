# eval/reporters/json_reporter.py
"""JSON reporter — machine-readable eval results."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from eval.stats import EvalResult, EvalSummary


def generate_json_report(
    results: list[EvalResult],
    summary: EvalSummary,
    output_path: Path,
) -> None:
    """Write eval results as JSON."""
    report = {
        "eval_run_id": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": summary.total,
            "passed": summary.passed,
            "pass_rate": round(summary.pass_rate, 4),
            "by_category": {
                cat: {
                    "pass_rate": round(s["pass_rate"], 4),
                    "count": s["count"],
                }
                for cat, s in summary.by_category.items()
            },
        },
        "cases": [
            {
                "case_id": r.case_id,
                "category": r.category,
                "pass_rate": round(r.pass_rate, 4),
                "passed": r.passed,
                "run_scores": r.run_scores,
                "rule_failures": r.rule_failures,
                "judge_reasons": r.judge_reasons,
            }
            for r in results
        ],
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
