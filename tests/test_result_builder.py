"""Unit tests for result_builder — replaces SOUL.md heredoc."""
import json

from common.result_builder import TaskResult, _parse_summary, build


class TestParseSummary:
    def test_extracts_summary_section(self, tmp_path):
        md = tmp_path / "result.md"
        md.write_text(
            "# Task Result\n\n## Query\nGO FROM 1\n\n"
            "## Summary\n这是中文摘要\n\n## Row Count\n5\n",
            encoding="utf-8",
        )
        summary = _parse_summary(md)
        assert "中文摘要" in summary

    def test_returns_empty_when_no_summary_section(self, tmp_path):
        md = tmp_path / "result.md"
        md.write_text("# Task Result\n\n## Query\nGO FROM 1\n", encoding="utf-8")
        summary = _parse_summary(md)
        assert summary == ""

    def test_handles_summary_at_end_of_file(self, tmp_path):
        md = tmp_path / "result.md"
        md.write_text("## Summary\nFinal summary text", encoding="utf-8")
        summary = _parse_summary(md)
        assert "Final summary text" in summary


class TestBuild:
    def _write_fixtures(self, tmp_path):
        gen = tmp_path / "mcp_generate.json"
        gen.write_text(json.dumps({
            "ngql": "GO FROM 1 OVER edge",
            "trace_id": "gen-trace",
        }), encoding="utf-8")
        exe = tmp_path / "mcp_execute.json"
        exe.write_text(json.dumps({
            "trace_id": "exe-trace",
            "columns": ["name", "amount"],
            "rows": [{"name": "ACME", "amount": 100}],
            "row_count": 1,
            "execution_time_ms": 42,
            "success": True,
        }), encoding="utf-8")
        md = tmp_path / "result.md"
        md.write_text(
            "## Summary\nTest summary\n", encoding="utf-8"
        )
        return gen, exe, md

    def test_returns_task_result_with_correct_fields(self, tmp_path):
        gen, exe, md = self._write_fixtures(tmp_path)
        result = build(gen, exe, md)
        assert isinstance(result, TaskResult)
        assert result.trace_id == "exe-trace"
        assert result.cypher == "GO FROM 1 OVER edge"
        assert result.columns == ["name", "amount"]
        assert result.row_count == 1
        assert result.execution_time_ms == 42
        assert "Test summary" in result.summary

    def test_row_count_defaults_to_len_rows(self, tmp_path):
        gen, exe, md = self._write_fixtures(tmp_path)
        # Overwrite execute without row_count
        exe.write_text(json.dumps({
            "rows": [{"a": 1}, {"a": 2}, {"a": 3}],
            "success": True,
        }), encoding="utf-8")
        result = build(gen, exe, md)
        assert result.row_count == 3

    def test_raw_data_matches_rows(self, tmp_path):
        gen, exe, md = self._write_fixtures(tmp_path)
        result = build(gen, exe, md)
        assert result.raw_data == [{"name": "ACME", "amount": 100}]

    def test_empty_rows_handled(self, tmp_path):
        gen = tmp_path / "gen.json"
        gen.write_text(json.dumps({"ngql": "GO FROM 1"}), encoding="utf-8")
        exe = tmp_path / "exe.json"
        exe.write_text(json.dumps({"rows": [], "success": True}), encoding="utf-8")
        md = tmp_path / "result.md"
        md.write_text("## Summary\nNo results\n", encoding="utf-8")
        result = build(gen, exe, md)
        assert result.row_count == 0
        assert result.raw_data == []
