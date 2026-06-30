# tests/eval/test_case_loader.py
"""Unit tests for eval.case_loader — YAML case loading + dataclass."""
from __future__ import annotations

from pathlib import Path

from eval.case_loader import load_all_cases, load_case


def _write_case(path: Path, case_id: str, question: str = "test question") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""id: {case_id}
category: ngql_accuracy
subcategory: basic
question: "{question}"
user_context: analyst

ci:
  golden_ngql: |
    MATCH (s:Supplier) RETURN s.Supplier.supplier_name AS name LIMIT 10
  checks:
    - type: syntax_valid
    - type: has_limit

offline:
  judge:
    rubric: "Is the query correct?"
    pass_criteria: 4
    runs: 3
""",
        encoding="utf-8",
    )


def test_load_case_parses_yaml(tmp_path: Path) -> None:
    _write_case(tmp_path / "cases" / "basic-001.yaml", "NGQL-BASIC-001")
    case = load_case(tmp_path / "cases" / "basic-001.yaml")
    assert case.id == "NGQL-BASIC-001"
    assert case.category == "ngql_accuracy"
    assert case.question == "test question"
    assert case.user_context == "analyst"
    assert case.ci is not None
    assert "MATCH" in case.ci.golden_ngql
    assert len(case.ci.checks) == 2
    assert case.ci.checks[0].type == "syntax_valid"
    assert case.offline is not None
    assert case.offline.judge.runs == 3


def test_load_case_without_offline_section(tmp_path: Path) -> None:
    path = tmp_path / "cases" / "ci-only.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """id: ANTIHAL-001
category: antihal_permission
subcategory: write_rejection
question: "delete everything"
user_context: admin

ci:
  golden_ngql: "DELETE VERTEX *"
  checks:
    - type: rejected_by_L1
""",
        encoding="utf-8",
    )
    case = load_case(path)
    assert case.offline is None
    assert case.ci is not None
    assert case.ci.checks[0].type == "rejected_by_L1"


def test_load_case_without_ci_section(tmp_path: Path) -> None:
    path = tmp_path / "cases" / "offline-only.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """id: E2E-001
category: e2e_quality
subcategory: summary
question: "summarize suppliers"
user_context: admin

offline:
  judge:
    rubric: "Is the summary good?"
    pass_criteria: 4
    runs: 3
""",
        encoding="utf-8",
    )
    case = load_case(path)
    assert case.ci is None
    assert case.offline is not None


def test_load_all_cases_recursive(tmp_path: Path) -> None:
    _write_case(tmp_path / "cases" / "ngql" / "a.yaml", "A-001")
    _write_case(tmp_path / "cases" / "ngql" / "b.yaml", "A-002")
    _write_case(tmp_path / "cases" / "antihal" / "c.yaml", "B-001", "reject me")
    cases = load_all_cases(tmp_path / "cases")
    ids = {c.id for c in cases}
    assert ids == {"A-001", "A-002", "B-001"}


def test_load_all_cases_empty_dir(tmp_path: Path) -> None:
    (tmp_path / "cases").mkdir()
    cases = load_all_cases(tmp_path / "cases")
    assert cases == []


def test_check_extra_params_parsed(tmp_path: Path) -> None:
    path = tmp_path / "cases" / "with-params.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """id: PARAM-001
category: ngql_accuracy
subcategory: basic
question: "test"
user_context: analyst

ci:
  golden_ngql: "MATCH (s:Supplier) RETURN s LIMIT 10"
  checks:
    - type: expected_tags
      tags: [Supplier, PurchaseOrder]
    - type: forbidden_ops_absent
      ops: [GO, FETCH]
""",
        encoding="utf-8",
    )
    case = load_case(path)
    check = case.ci.checks[0]
    assert check.type == "expected_tags"
    assert check.params == {"tags": ["Supplier", "PurchaseOrder"]}
    check2 = case.ci.checks[1]
    assert check2.params == {"ops": ["GO", "FETCH"]}
