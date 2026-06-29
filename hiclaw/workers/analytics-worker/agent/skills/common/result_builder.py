"""Build result.json from saved MCP responses — replaces SOUL.md heredoc."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class TaskResult:
    """Structured result consumed by forward-to-user.sh (Manager-side)."""
    trace_id: str
    cypher: str
    columns: list
    raw_data: list
    row_count: int
    execution_time_ms: int
    summary: str


def _parse_summary(result_md_path: Path) -> str:
    """Extract the ## Summary section from result.md."""
    md = result_md_path.read_text(encoding="utf-8")
    m = re.search(r"## Summary\n(.*?)(?=\n## |\Z)", md, re.DOTALL)
    return m.group(1).strip() if m else ""


def build(generate_file: Path, execute_file: Path, result_md: Path) -> TaskResult:
    """Build a TaskResult from saved MCP response files and result.md."""
    gen = json.loads(generate_file.read_text(encoding="utf-8"))
    exe = json.loads(execute_file.read_text(encoding="utf-8"))
    rows = exe.get("rows", [])
    return TaskResult(
        trace_id=exe.get("trace_id", ""),
        cypher=exe.get("ngql", gen.get("ngql", "")),
        columns=exe.get("columns", []),
        raw_data=rows,
        row_count=exe.get("row_count", len(rows)),
        execution_time_ms=exe.get("execution_time_ms", 0),
        summary=_parse_summary(result_md),
    )


def main() -> None:
    """CLI entry point: python3 -m common.result_builder --task-id ..."""
    import argparse

    parser = argparse.ArgumentParser(description="Build result.json from MCP responses")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--generate-file", required=True)
    parser.add_argument("--execute-file", required=True)
    parser.add_argument("--result-md", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = build(
        Path(args.generate_file),
        Path(args.execute_file),
        Path(args.result_md),
    )
    Path(args.output).write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"result.json written ({result.row_count} rows, trace={result.trace_id})")


if __name__ == "__main__":
    main()
