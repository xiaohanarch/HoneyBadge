# tests/eval/test_reporters.py
"""Unit tests for eval reporters — JSON/HTML/Markdown output."""
from __future__ import annotations

import json
from pathlib import Path

from eval.reporters.html_reporter import generate_html_report
from eval.reporters.json_reporter import generate_json_report
from eval.reporters.markdown_reporter import generate_markdown_report
from eval.stats import EvalResult, EvalSummary


def _make_results() -> tuple[list[EvalResult], EvalSummary]:
    results = [
        EvalResult(case_id="A-001", category="ngql_accuracy", pass_rate=1.0, passed=True, run_scores=[5, 5, 5]),
        EvalResult(case_id="A-002", category="ngql_accuracy", pass_rate=0.0, passed=False, run_scores=[2, 1, 2]),
    ]
    summary = EvalSummary(
        total=2, passed=1, pass_rate=0.5,
        by_category={"ngql_accuracy": {"total": 2, "passed": 1, "pass_rate": 0.5, "count": 2}},
    )
    return results, summary


def test_json_reporter_writes_valid_json(tmp_path: Path) -> None:
    results, summary = _make_results()
    out = tmp_path / "report.json"
    generate_json_report(results, summary, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summary"]["total"] == 2
    assert data["summary"]["passed"] == 1
    assert len(data["cases"]) == 2
    assert data["cases"][0]["case_id"] == "A-001"


def test_markdown_reporter_writes_readable_md(tmp_path: Path) -> None:
    results, summary = _make_results()
    out = tmp_path / "report.md"
    generate_markdown_report(results, summary, out)
    content = out.read_text(encoding="utf-8")
    assert "# Eval Report" in content
    assert "A-001" in content
    assert "ngql_accuracy" in content


def test_html_reporter_writes_html(tmp_path: Path) -> None:
    results, summary = _make_results()
    out = tmp_path / "report.html"
    generate_html_report(results, summary, out)
    content = out.read_text(encoding="utf-8")
    assert "<html" in content.lower()
    assert "A-001" in content
    assert "ngql_accuracy" in content
