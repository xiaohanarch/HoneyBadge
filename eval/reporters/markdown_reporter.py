# eval/reporters/markdown_reporter.py
"""Markdown reporter — human-readable eval results for PR comments."""
from __future__ import annotations

from pathlib import Path

from eval.stats import EvalResult, EvalSummary


def generate_markdown_report(
    results: list[EvalResult],
    summary: EvalSummary,
    output_path: Path,
) -> None:
    """Write eval results as Markdown."""
    lines = [
        "# Eval Report",
        "",
        f"**Total:** {summary.total} | **Passed:** {summary.passed} | **Pass Rate:** {summary.pass_rate:.1%}",
        "",
        "## By Category",
        "",
        "| Category | Passed | Total | Pass Rate |",
        "|----------|--------|-------|-----------|",
    ]
    for cat, stats in summary.by_category.items():
        lines.append(f"| {cat} | {stats['passed']} | {stats['count']} | {stats['pass_rate']:.1%} |")

    lines.extend(["", "## Case Details", "", "| Case ID | Category | Pass Rate | Passed |", "|---------|----------|------------|--------|"])
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"| {r.case_id} | {r.category} | {r.pass_rate:.1%} | {status} |")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
