"""Numeric fidelity checker for LLM summarization (anti-hallucination L4 validation).

This checker verifies that every numeric value present in the raw query results
appears unchanged in the LLM-generated summary. It is a programmatic enforcement
of the "不要修改任何数值" prompt instruction used by ``summarize_results()`` in
``adapter.py`` (the L4 raw-result-passthrough layer).

Wiring:
    ``summarize_results()`` calls ``check_and_log_fidelity()`` immediately after
    the LLM returns a summary. The guard is **log-only** — on mismatch it emits a
    ``numeric_fidelity_mismatch`` warning (with ``trace_id``) and returns; it
    never raises, so LLM hallucination attempts surface in logs without breaking
    the production chat path. The ``LLMResponse`` is returned unchanged.

Canonical home:
    This module lives in the runtime package so it is importable from both the
    production chat path and the eval suite. The eval layer imports from here;
    the previous ``eval/scorers/numeric_fidelity.py`` copy has been removed.

Limitation:
    Chinese number formats (``10万``, ``1.5亿``) are NOT recognized. Only ASCII
    digits with optional thousands separators and a decimal point are matched.
    A summary that converts ``100000`` to ``10万`` is therefore flagged as a
    missing number (the digit run ``100000`` is absent) — which is the desired
    adversarial signal, but the checker cannot positively confirm that ``10万``
    equals ``100000``.

Known limitation (pre-strip validation):
    ``summarize_results()`` validates ``response.content`` BEFORE the caller
    strips ``<think>...</think>`` tags. A split-brain model (correct numbers in
    ``<think>``, wrong in visible text) could false-PASS. Post-strip validation
    is a documented future refinement.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger()

# Matches comma-grouped numbers (``100,000`` / ``1,234,567.89``) OR plain
# integers/decimals (``42`` / ``123.45`` / ``100000``). The comma-grouped
# alternative requires at least one ``,\d{3}`` group (``+``) so that a plain
# 6-digit integer like ``100000`` is NOT split into ``100`` + ``000`` — it
# falls through to the plain ``\d+`` alternative and matches as one number.
_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


@dataclass
class NumericFidelityResult:
    """Result of a numeric fidelity check.

    Mirrors the ``passed``/``detail`` shape of ``eval.scorers.rule_checks.CheckResult``
    so the eval suite can consume it without adaptation.
    """

    passed: bool
    detail: str = ""


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
) -> NumericFidelityResult:
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
        return NumericFidelityResult(True, "No raw results to verify")

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
        return NumericFidelityResult(True, "No numeric values in raw results")

    summary_numbers = extract_numbers(summary)
    missing = sorted(n for n in raw_numbers if n not in summary_numbers)

    if missing:
        return NumericFidelityResult(
            False,
            f"Numeric values from raw results missing or modified in summary: {missing}",
        )
    return NumericFidelityResult(True, "All raw numeric values present in summary")


def check_and_log_fidelity(
    summary: str,
    raw_results: list[dict[str, Any]],
    columns: list[str],
    trace_id: str | None = None,
) -> None:
    """Post-hoc L4 guard: log a warning if summary numbers diverge from raw.

    Called by ``summarize_results()`` immediately after the LLM returns. This is
    a **log-only** guard — it never raises, so a fidelity mismatch (or an
    unexpected error inside the checker) surfaces in logs without breaking the
    production chat path. The caller returns the ``LLMResponse`` unchanged
    regardless of the outcome.
    """
    try:
        result = validate_numeric_fidelity(summary, raw_results, columns)
    except Exception as exc:
        logger.warning(
            "numeric_fidelity_check_error",
            trace_id=trace_id,
            error=str(exc),
        )
        return
    if not result.passed:
        logger.warning(
            "numeric_fidelity_mismatch",
            trace_id=trace_id,
            detail=result.detail,
        )
