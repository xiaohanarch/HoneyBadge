# eval/ci/test_ci_rules.py
"""CI-layer tests: each eval case's golden_ngql must pass all CI checks."""
from __future__ import annotations

from dataclasses import asdict

import pytest

from eval.case_loader import EvalCase
from eval.scorers.rule_checks import run_check
from honeybadge.permission_service.config import PERMISSION_CONFIG


def _build_user_context(user_context: str) -> dict[str, object] | None:
    """Map the demo user name to a permission context dict.

    Uses the canonical PERMISSION_CONFIG so CI matches production behaviour
    (e.g. procurement_lead/auditor have org_ids=None for full access).
    """
    ctx = PERMISSION_CONFIG.get(user_context)
    return asdict(ctx) if ctx else None


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
