# eval/ci/conftest.py
"""Pytest parametrization: load all eval cases from eval/cases/."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from eval.case_loader import load_all_cases

_CASES_DIR = Path(__file__).resolve().parent.parent / "cases"
_SUMMARIZE_DIR = _CASES_DIR / "summarize"


@dataclass
class SummarizeCase:
    """A summarize-fidelity seed case — tests the checker itself, not the LLM.

    Each case carries synthetic raw query results plus two summaries: one that
    preserves every number (must PASS) and one that tampers with them (must FAIL).
    """

    id: str
    raw_results: list[dict[str, Any]]
    columns: list[str]
    expected_summary: str
    tampered_summary: str


def _load_summarize_cases() -> list[SummarizeCase]:
    """Load summarize-fidelity seed cases from eval/cases/summarize/."""
    if not _SUMMARIZE_DIR.exists():
        return []
    cases: list[SummarizeCase] = []
    for yaml_file in sorted(_SUMMARIZE_DIR.glob("*.yaml")):
        raw = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        summ = raw["summarize"]
        cases.append(
            SummarizeCase(
                id=raw["id"],
                raw_results=summ["raw_results"],
                columns=summ["columns"],
                expected_summary=summ["expected_summary"],
                tampered_summary=summ["tampered_summary"],
            )
        )
    return cases


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize eval_case (nGQL cases) and summarize_case (fidelity seeds)."""
    if "eval_case" in metafunc.fixturenames:
        all_cases = load_all_cases(_CASES_DIR)
        # Summarize-fidelity cases have no CI section; exclude them from the
        # nGQL CI fixture so they do not surface as skipped noise there — they
        # run via the dedicated summarize_case fixture below.
        ngql_cases = [c for c in all_cases if c.category != "summarize_fidelity"]
        metafunc.parametrize(
            "eval_case",
            ngql_cases,
            ids=[c.id for c in ngql_cases],
        )
    if "summarize_case" in metafunc.fixturenames:
        cases = _load_summarize_cases()
        metafunc.parametrize(
            "summarize_case",
            cases,
            ids=[c.id for c in cases],
        )
