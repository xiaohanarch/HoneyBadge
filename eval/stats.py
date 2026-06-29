# eval/stats.py
"""N-run statistics and pass-rate threshold for offline eval."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvalResult:
    """Result of evaluating one case across N runs."""
    case_id: str
    category: str
    pass_rate: float
    passed: bool  # pass_rate >= threshold
    run_scores: list[int] = field(default_factory=list)
    rule_failures: list[str] = field(default_factory=list)
    judge_reasons: list[str] = field(default_factory=list)


@dataclass
class EvalSummary:
    """Aggregated results across all cases."""
    total: int
    passed: int
    pass_rate: float
    by_category: dict[str, dict] = field(default_factory=dict)


def compute_pass_rate(run_results: list[bool]) -> float:
    """Compute the pass rate from a list of per-run pass/fail booleans."""
    if not run_results:
        return 0.0
    return sum(run_results) / len(run_results)


def summarize_results(results: list[EvalResult], threshold: float = 0.8) -> EvalSummary:
    """Aggregate per-case results into a summary by category."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    overall_rate = passed / total if total else 0.0

    by_category: dict[str, dict] = {}
    for r in results:
        cat = r.category
        if cat not in by_category:
            by_category[cat] = {"total": 0, "passed": 0, "pass_rate": 0.0, "count": 0}
        by_category[cat]["total"] += 1
        by_category[cat]["count"] += 1
        if r.passed:
            by_category[cat]["passed"] += 1

    for cat in by_category:
        c = by_category[cat]
        c["pass_rate"] = c["passed"] / c["total"] if c["total"] else 0.0

    return EvalSummary(total=total, passed=passed, pass_rate=overall_rate, by_category=by_category)
