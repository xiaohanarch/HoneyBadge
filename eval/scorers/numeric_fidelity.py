# eval/scorers/numeric_fidelity.py
"""Numeric fidelity checker for LLM summarization (anti-hallucination L4 validation).

This checker verifies that every numeric value present in the raw query results
appears unchanged in the LLM-generated summary. It is a programmatic enforcement
of the "不要修改任何数值" prompt instruction used by ``summarize_results()`` in
``adapter.py`` (the L4 raw-result-passthrough layer).

L4 enforcement gap:
    This checker is NOT yet wired into ``summarize_results()``. The L4 guarantee
    currently relies on prompt instructions alone. Wiring this checker as a
    post-hoc validation in ``summarize_results()`` is a follow-up task — it would
    log a warning (not fail) when numbers do not match, surfacing LLM
    hallucination attempts without breaking production.

Limitation:
    Chinese number formats (``10万``, ``1.5亿``) are NOT recognized. Only ASCII
    digits with optional thousands separators and a decimal point are matched.
    A summary that converts ``100000`` to ``10万`` is therefore flagged as a
    missing number (the digit run ``100000`` is absent) — which is the desired
    adversarial signal, but the checker cannot positively confirm that ``10万``
    equals ``100000``.
"""
from __future__ import annotations

import re
from typing import Any

from eval.scorers.rule_checks import CheckResult

# Matches comma-grouped numbers (``100,000`` / ``1,234,567.89``) OR plain
# integers/decimals (``42`` / ``123.45`` / ``100000``). The comma-grouped
# alternative requires at least one ``,\d{3}`` group (``+``) so that a plain
# 6-digit integer like ``100000`` is NOT split into ``100`` + ``000`` — it
# falls through to the plain ``\d+`` alternative and matches as one number.
_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def _normalize(number: str) -> str:
    """Strip thousands separators so ``100,000`` compares equal to ``100000``."""
    return number.replace(",", "")


def extract_numbers(text: str) -> set[str]:
    """Extract numeric values from text.

    Matches integers, decimals, and numbers with thousands separators.
    Returned values are normalized: thousands separators are stripped
    (``"100,000"`` -> ``"100000"``) so comma-grouped and ungrouped forms
    compare equal.

    Does NOT match Chinese formats (``10万``, ``1.5亿``) — see module docstring.
    """
    return {_normalize(m.group(0)) for m in _NUMBER_RE.finditer(text)}


def validate_numeric_fidelity(
    summary: str,
    raw_results: list[dict[str, Any]],
    columns: list[str],
) -> CheckResult:
    """Check that all numbers in ``raw_results`` appear unchanged in ``summary``.

    Logic:
      1. Extract numbers from the named ``columns`` of every row in
         ``raw_results``.
      2. Extract numbers from ``summary``.
      3. For each raw number, check it appears in the summary (normalized).
      4. If any raw number is missing -> FAIL with detail listing missing numbers.
      5. Extra numbers in summary -> PASS (summary may mention counts/percentages).
      6. Empty ``raw_results`` -> PASS (nothing to verify).
    """
    if not raw_results:
        return CheckResult(True, "No raw results to verify")

    raw_numbers: set[str] = set()
    for row in raw_results:
        for col in columns:
            value = row.get(col)
            if value is None:
                continue
            # Stringify so that both numeric types (123.45) and formatted
            # strings ("100,000") are handled uniformly.
            raw_numbers.update(extract_numbers(str(value)))

    if not raw_numbers:
        return CheckResult(True, "No numeric values in raw results")

    summary_numbers = extract_numbers(summary)
    missing = sorted(n for n in raw_numbers if n not in summary_numbers)

    if missing:
        return CheckResult(
            False,
            f"Numeric values from raw results missing or modified in summary: {missing}",
        )
    return CheckResult(True, "All raw numeric values present in summary")
