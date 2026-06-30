"""Runtime tests for honeybadge.llm.numeric_fidelity — import smoke + logging guard.

These tests cover the runtime wiring of the L4 numeric fidelity guard:
  * the module imports cleanly under the installed ``honeybadge`` package;
  * ``check_and_log_fidelity`` warns on a tampered summary and never raises;
  * a faithful summary emits no ``numeric_fidelity_mismatch`` warning.

The pure ``validate_numeric_fidelity`` / ``extract_numbers`` logic is already
exercised by ``tests/eval/test_numeric_fidelity.py`` and ``eval/ci/``; this
file focuses on the runtime-only ``check_and_log_fidelity`` helper.
"""
from __future__ import annotations

import logging
from typing import Any

import pytest
import structlog

from honeybadge.llm.numeric_fidelity import (
    NumericFidelityResult,
    check_and_log_fidelity,
    extract_numbers,
    validate_numeric_fidelity,
)


@pytest.fixture(autouse=True)
def _stdlib_structlog():
    """Route structlog through stdlib logging so caplog captures warnings.

    The production code uses ``structlog.get_logger()`` without a global
    ``configure()``, so for tests we explicitly bind the stdlib factory + a
    rendering processor chain. ``cache_logger_on_first_use=False`` ensures the
    module-level lazy proxy re-resolves to this config on each call.
    """
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    yield
    structlog.reset_defaults()


def _mismatches(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if "numeric_fidelity_mismatch" in r.getMessage()]


def _check_errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if "numeric_fidelity_check_error" in r.getMessage()]


# --- smoke ---


def test_public_api_importable() -> None:
    assert callable(extract_numbers)
    assert callable(validate_numeric_fidelity)
    assert callable(check_and_log_fidelity)
    # Default detail is empty — mirrors eval CheckResult shape.
    assert NumericFidelityResult(passed=True).detail == ""


# --- check_and_log_fidelity ---


def test_check_and_log_fidelity_warns_on_mismatch(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    raw_results: list[dict[str, Any]] = [{"amount": "100000"}]
    # Tampered: raw 100000 -> summary says 123000.
    check_and_log_fidelity("金额为 123000 元", raw_results, ["amount"], trace_id="TRC-test-1")
    mismatches = _mismatches(caplog)
    assert mismatches, "expected a numeric_fidelity_mismatch warning"
    # The missing raw number should appear in the rendered detail.
    assert any("100000" in r.getMessage() for r in mismatches)


def test_check_and_log_fidelity_silent_on_match(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    raw_results: list[dict[str, Any]] = [{"amount": "100000"}]
    check_and_log_fidelity("金额为 100000 元", raw_results, ["amount"], trace_id="TRC-test-2")
    assert not _mismatches(caplog)
    assert not _check_errors(caplog)


def test_check_and_log_fidelity_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    # Malformed raw_results (non-iterable) would raise TypeError inside the
    # checker. The log-only guard must swallow it and emit a check_error
    # rather than propagate — never break the production chat path.
    check_and_log_fidelity("summary", 123, ["a"], trace_id="TRC-test-3")  # type: ignore[arg-type]
    assert not _mismatches(caplog)
    assert _check_errors(caplog), "expected a numeric_fidelity_check_error warning"
