# eval/reporters/html_reporter.py
"""HTML reporter — rich visual eval results."""
from __future__ import annotations

from pathlib import Path

from eval.stats import EvalResult, EvalSummary


def generate_html_report(
    results: list[EvalResult],
    summary: EvalSummary,
    output_path: Path,
) -> None:
    """Write eval results as a standalone HTML page."""
    rows = []
    for r in results:
        color = "#4caf50" if r.passed else "#f44336"
        rows.append(
            f"<tr><td>{r.case_id}</td><td>{r.category}</td>"
            f"<td>{r.pass_rate:.1%}</td>"
            f"<td style='color:{color};font-weight:bold'>"
            f"{'PASS' if r.passed else 'FAIL'}</td></tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Eval Report</title>
<style>
body {{ font-family: sans-serif; margin: 2rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #f5f5f5; }}
.summary {{ font-size: 1.2rem; margin-bottom: 1rem; }}
</style>
</head>
<body>
<h1>Eval Report</h1>
<div class="summary">
  Total: {summary.total} |
  Passed: {summary.passed} |
  Pass Rate: <strong>{summary.pass_rate:.1%}</strong>
</div>
<h2>By Category</h2>
<table>
<tr><th>Category</th><th>Passed</th><th>Total</th><th>Pass Rate</th></tr>
"""
    for cat, stats in summary.by_category.items():
        html += f"<tr><td>{cat}</td><td>{stats['passed']}</td><td>{stats['count']}</td><td>{stats['pass_rate']:.1%}</td></tr>\n"

    html += f"""</table>
<h2>Case Details</h2>
<table>
<tr><th>Case ID</th><th>Category</th><th>Pass Rate</th><th>Status</th></tr>
{''.join(rows)}
</table>
</body>
</html>"""
    output_path.write_text(html, encoding="utf-8")
