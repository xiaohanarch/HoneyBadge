"""Tests for audit-log write failure handling in websocket.process_query.

Regression tests for issue #4: the error path silently swallowed audit-log
write failures via ``except Exception: pass``, making audit outages
unobservable and violating the L5 full-chain audit promise.
"""
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_project_root, "src"))

# Mock asyncpg if not available (e.g. Python 3.14 where asyncpg has no wheel).
if "asyncpg" not in sys.modules:
    _asyncpg_mock = types.ModuleType("asyncpg")
    _asyncpg_mock.Pool = MagicMock()  # type: ignore[attr-defined]
    _asyncpg_mock.create_pool = AsyncMock()  # type: ignore[attr-defined]
    sys.modules["asyncpg"] = _asyncpg_mock

from honeybadge.server import websocket  # noqa: E402


@pytest.mark.asyncio
async def test_error_path_audit_write_failure_is_logged_not_swallowed():
    """When pg.write_audit_log raises in the error path, the failure must be
    logged as a warning — not silently swallowed via ``except: pass``.

    Before the fix, an audit-service outage during a failed query produced
    zero observability signal: the audit record was permanently lost with no
    log line. This broke the L5 audit promise and made audit outages invisible.
    """
    # Arrange: force the main query to fail by making schema fetch raise,
    # routing execution into the error-path except block (websocket.py:634).
    pg = AsyncMock()
    pg.get_session_audit_logs = AsyncMock(return_value=[])
    # The error-path attempts to write an error audit entry. Make that write
    # fail too, simulating an audit-service outage (the L5 violation scenario).
    pg.write_audit_log = AsyncMock(side_effect=RuntimeError("audit db down"))

    nebula = AsyncMock()
    llm_adapter = MagicMock()

    with patch.object(
        websocket,
        "get_filtered_schema_str",
        new=AsyncMock(side_effect=RuntimeError("schema fetch failed")),
    ), patch.object(websocket, "logger") as mock_logger:
        result = await websocket.process_query(
            question="any question",
            session_id="sess-test",
            nebula=nebula,
            pg=pg,
            llm_adapter=llm_adapter,
        )

    # The function must still return a graceful error response (no raise).
    assert "error" in result
    assert result["trace_id"]

    # The audit write failure MUST be observable — not silently swallowed.
    warning_calls = mock_logger.warning.call_args_list
    assert warning_calls, "expected at least one warning log on the error path"

    audit_failure_logged = any(
        call.args and "audit" in str(call.args[0]).lower()
        for call in warning_calls
    )
    assert audit_failure_logged, (
        "audit write failure must be logged (not swallowed via except: pass); "
        f"saw warnings: {warning_calls}"
    )

    # The error-path audit write attempt must have happened.
    pg.write_audit_log.assert_awaited()


@pytest.mark.asyncio
async def test_error_path_audit_write_success_does_not_warn():
    """When the error-path audit write succeeds, no audit-failure warning is
    emitted. Only the normal ``ws_query_error`` error-level log fires.

    Guards against over-logging: the fix must not warn when there is no failure.
    """
    pg = AsyncMock()
    pg.get_session_audit_logs = AsyncMock(return_value=[])
    pg.write_audit_log = AsyncMock(return_value=True)

    nebula = AsyncMock()
    llm_adapter = MagicMock()

    with patch.object(
        websocket,
        "get_filtered_schema_str",
        new=AsyncMock(side_effect=RuntimeError("schema fetch failed")),
    ), patch.object(websocket, "logger") as mock_logger:
        result = await websocket.process_query(
            question="any question",
            session_id="sess-test",
            nebula=nebula,
            pg=pg,
            llm_adapter=llm_adapter,
        )

    assert "error" in result
    pg.write_audit_log.assert_awaited()

    # No audit-failure warning should fire when the write succeeded.
    audit_failure_warnings = [
        call for call in mock_logger.warning.call_args_list
        if call.args and "audit" in str(call.args[0]).lower()
    ]
    assert not audit_failure_warnings, (
        "no audit-failure warning expected when write succeeded; "
        f"saw: {audit_failure_warnings}"
    )
