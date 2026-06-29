# eval/ci/test_ci_rules.py
"""CI-layer tests: each eval case's golden_ngql must pass all CI checks."""
from __future__ import annotations

import pytest

from eval.case_loader import EvalCase
from eval.scorers.rule_checks import run_check


def _build_user_context(user_context: str) -> dict | None:
    """Map the demo user name to a permission context dict."""
    profiles = {
        "admin": {"user_id": "admin", "org_ids": None},
        "analyst": {"user_id": "analyst", "org_ids": [1000]},
        "procurement_lead": {"user_id": "procurement_lead", "org_ids": [1000]},
        "subsidiary_lead": {"user_id": "subsidiary_lead", "org_ids": [1021]},
        "auditor": {"user_id": "auditor", "org_ids": [1000]},
    }
    return profiles.get(user_context)


@pytest.mark.eval_ci
def test_golden_ngql_passes_all_ci_checks(eval_case: EvalCase) -> None:
    """Every case with a ci section must pass all its checks."""
    if eval_case.ci is None:
        pytest.skip(f"{eval_case.id}: no CI section")

    ngql = eval_case.ci.golden_ngql
    ctx = _build_user_context(eval_case.user_context)

    failures = []
    for check in eval_case.ci.checks:
        check_dict = {"type": check.type, **check.params}
        result = run_check(check_dict, ngql, ctx)
        if not result.passed:
            failures.append(f"{check.type}: {result.detail}")

    assert not failures, f"{eval_case.id}: CI check failures:\n  " + "\n  ".join(failures)
