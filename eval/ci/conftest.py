# eval/ci/conftest.py
"""Pytest parametrization: load all eval cases from eval/cases/."""
from __future__ import annotations

from pathlib import Path

import pytest

from eval.case_loader import load_all_cases

_CASES_DIR = Path(__file__).resolve().parent.parent / "cases"


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize eval_case fixture with all YAML cases."""
    if "eval_case" in metafunc.fixturenames:
        cases = load_all_cases(_CASES_DIR)
        metafunc.parametrize(
            "eval_case",
            cases,
            ids=[c.id for c in cases],
        )
