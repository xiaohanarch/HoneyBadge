"""Unit tests for MCPClient — mocked subprocess over mcporter."""
import json
from unittest.mock import MagicMock, patch

import pytest
from common.mcp_client import MCPClient, QueryResult


class TestQueryResult:
    def test_is_frozen_dataclass(self):
        qr = QueryResult(
            trace_id="t1", ngql="GO FROM 1", columns=["a"],
            rows=[{"a": 1}], row_count=1, execution_time_ms=10, success=True
        )
        assert qr.trace_id == "t1"
        with pytest.raises(AttributeError):
            qr.trace_id = "modified"  # frozen


class TestMCPClientCall:
    @patch("common.mcp_client.subprocess.run")
    def test_call_parses_stdout_as_json(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"trace_id": "abc", "rows": [{"x": 1}]}),
            stderr=""
        )
        client = MCPClient("honeybadge-nebula")
        result = client.call("generate_query", {"question": "test"})
        assert result["trace_id"] == "abc"

    @patch("common.mcp_client.subprocess.run")
    def test_call_raises_on_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="connection refused"
        )
        client = MCPClient("honeybadge-nebula")
        with pytest.raises(RuntimeError, match="connection refused"):
            client.call("generate_query", {"question": "test"})

    @patch("common.mcp_client.subprocess.run")
    def test_call_passes_correct_command(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="{}", stderr=""
        )
        client = MCPClient("honeybadge-nebula")
        client.call("generate_query", {"question": "hello"})
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "mcporter"
        assert cmd[1] == "call"
        assert cmd[2] == "honeybadge-nebula.generate_query"
        assert json.loads(cmd[4]) == {"question": "hello"}


class TestValidateAndExecute:
    @patch("common.mcp_client.subprocess.run")
    def test_returns_typed_query_result(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "trace_id": "trace-123",
                "ngql": "GO FROM 1",
                "columns": ["name", "amount"],
                "rows": [{"name": "ACME", "amount": 100}],
                "row_count": 1,
                "execution_time_ms": 42,
                "success": True,
            }),
            stderr=""
        )
        client = MCPClient("honeybadge-nebula")
        result = client.validate_and_execute("GO FROM 1", user_id="alice")
        assert isinstance(result, QueryResult)
        assert result.trace_id == "trace-123"
        assert result.row_count == 1
        assert result.rows[0]["name"] == "ACME"
        assert result.success is True

    @patch("common.mcp_client.subprocess.run")
    def test_user_context_included_when_user_id_provided(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps({"success": True}), stderr=""
        )
        client = MCPClient("honeybadge-nebula")
        client.validate_and_execute("GO FROM 1", user_id="bob")
        cmd = mock_run.call_args[0][0]
        args = json.loads(cmd[4])
        assert args["user_context"] == {"user_id": "bob"}

    @patch("common.mcp_client.subprocess.run")
    def test_user_context_omitted_when_no_user_id(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps({"success": True}), stderr=""
        )
        client = MCPClient("honeybadge-nebula")
        client.validate_and_execute("GO FROM 1")
        cmd = mock_run.call_args[0][0]
        args = json.loads(cmd[4])
        assert "user_context" not in args

    @patch("common.mcp_client.subprocess.run")
    def test_row_count_defaults_to_len_rows(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "rows": [{"a": 1}, {"a": 2}],
                "success": True,
            }),
            stderr=""
        )
        client = MCPClient("honeybadge-nebula")
        result = client.validate_and_execute("GO FROM 1")
        assert result.row_count == 2
