# eval/case_loader.py
"""Load eval cases from YAML files.

Case format defined in docs/superpowers/specs/2026-06-29-eval-suite-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Check:
    """One rule check to run on a golden or generated nGQL query."""
    type: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class CISection:
    """The CI-layer portion of an eval case."""
    golden_ngql: str
    checks: list[Check]


@dataclass
class JudgeSection:
    """The LLM-as-judge configuration for offline eval."""
    rubric: str
    pass_criteria: int  # 1-5 scale, >= pass_criteria is a pass
    runs: int = 3


@dataclass
class PostExecSection:
    """Optional post-execution checks (requires NebulaGraph)."""
    expected_row_count_min: int | None = None
    summary_value_check: bool = False


@dataclass
class OfflineSection:
    """The offline-layer portion of an eval case."""
    judge: JudgeSection
    post_exec: PostExecSection | None = None


@dataclass
class EvalCase:
    """One eval case loaded from YAML."""
    id: str
    category: str  # ngql_accuracy | antihal_permission | e2e_quality
    subcategory: str
    question: str
    user_context: str  # admin|analyst|procurement_lead|subsidiary_lead|auditor
    ci: CISection | None
    offline: OfflineSection | None
    source_path: Path | None = None


def load_case(path: Path) -> EvalCase:
    """Load a single eval case from a YAML file."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    ci = None
    if raw.get("ci"):
        ci = CISection(
            golden_ngql=raw["ci"]["golden_ngql"],
            checks=[
                Check(type=c["type"], params={k: v for k, v in c.items() if k != "type"})
                for c in raw["ci"].get("checks", [])
            ],
        )
    offline = None
    if raw.get("offline"):
        off = raw["offline"]
        judge = JudgeSection(
            rubric=off["judge"]["rubric"],
            pass_criteria=off["judge"]["pass_criteria"],
            runs=off["judge"].get("runs", 3),
        )
        post_exec = None
        if off.get("post_exec"):
            pe = off["post_exec"]
            post_exec = PostExecSection(
                expected_row_count_min=pe.get("expected_row_count_min"),
                summary_value_check=pe.get("summary_value_check", False),
            )
        offline = OfflineSection(judge=judge, post_exec=post_exec)
    return EvalCase(
        id=raw["id"],
        category=raw["category"],
        subcategory=raw.get("subcategory", ""),
        question=raw["question"],
        user_context=raw["user_context"],
        ci=ci,
        offline=offline,
        source_path=path,
    )


def load_all_cases(cases_dir: Path) -> list[EvalCase]:
    """Recursively load all *.yaml cases from a directory."""
    if not cases_dir.exists():
        return []
    cases = []
    for yaml_file in sorted(cases_dir.rglob("*.yaml")):
        cases.append(load_case(yaml_file))
    return cases
