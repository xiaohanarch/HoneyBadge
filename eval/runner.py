# eval/runner.py
"""Offline eval runner — calls real LLM, scores with rules + LLM-as-judge.

This is the core of the offline eval layer (Task 9). It:
  1. Loads eval cases (via case_loader, called from main()).
  2. Generates nGQL using the real LLM adapter (generate_ngql).
  3. Scores with rule checks (rule_checks.run_check).
  4. If rules pass, scores with LLM-as-judge (LLMJudge.evaluate).
  5. Computes pass rates across N runs (stats.compute_pass_rate).
  6. Exposes a CLI entry point (main()) for standalone execution.

API note: LLMProviderManager requires a config dict and does not expose
get_primary_config/get_judge_config. We build OpenAICompatibleAdapter
directly from environment variables, mirroring the pattern used in
mcp-servers/honeybadge-nebula-mcp/server.py. This keeps the runner
genuinely usable at runtime while remaining mockable in tests.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import structlog

from eval.case_loader import EvalCase
from eval.scorers.llm_judge import LLMJudge
from eval.scorers.rule_checks import run_check
from eval.stats import EvalResult, compute_pass_rate

logger = structlog.get_logger()


def build_llm_adapter() -> Any:
    """Build the LLM adapter for nGQL generation.

    Reads LLM_ENDPOINT / LLM_API_KEY / LLM_MODEL from the environment,
    falling back to the Higress gateway default used by workers.
    Returns an object with an async chat() method (LLMAdapter).
    """
    from honeybadge.llm.adapter import OpenAICompatibleAdapter

    config = {
        "endpoint": os.environ.get("LLM_ENDPOINT", "http://localhost:8080"),
        "api_key": os.environ.get("LLM_API_KEY", ""),
        "model": os.environ.get("LLM_MODEL", "glm-4-flash"),
        "timeout": _parse_timeout("LLM_TIMEOUT"),
    }
    return OpenAICompatibleAdapter(config, None)


def build_judge_adapter() -> Any:
    """Build a stronger LLM adapter for judging.

    Reads JUDGE_LLM_* env vars, falling back to the primary LLM_* vars
    so a single-model setup works without extra configuration.
    """
    from honeybadge.llm.adapter import OpenAICompatibleAdapter

    config = {
        "endpoint": os.environ.get("JUDGE_LLM_ENDPOINT", os.environ.get("LLM_ENDPOINT", "http://localhost:8080")),
        "api_key": os.environ.get("JUDGE_LLM_API_KEY", os.environ.get("LLM_API_KEY", "")),
        "model": os.environ.get("JUDGE_LLM_MODEL", os.environ.get("LLM_MODEL", "glm-4-flash")),
        "timeout": _parse_timeout("JUDGE_LLM_TIMEOUT"),
    }
    return OpenAICompatibleAdapter(config, None)


def get_schema_info() -> str:
    """Get NebulaGraph schema info (tags + edges) from the deploy directory."""
    repo_root = Path(__file__).resolve().parents[2]
    schema_path = repo_root / "deploy" / "docker" / "nebula-schema.ngql"
    edges_path = repo_root / "deploy" / "docker" / "nebula-edges.ngql"
    parts: list[str] = []
    if schema_path.exists():
        parts.append(schema_path.read_text(encoding="utf-8"))
    if edges_path.exists():
        parts.append(edges_path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def render_ontology(question: str) -> str:
    """Render ontology context for the question.

    Returns empty string if the ontology directory cannot be located
    (e.g. in CI without prompts/ontology mounted).
    """
    from honeybadge.ontology import get_loader

    try:
        loader = get_loader()
        text, _ = loader.render_for_question(question)
        return str(text)
    except FileNotFoundError:
        return ""


def _build_user_context(user_context: str) -> dict[str, Any] | None:
    """Map a case's user_context label to a permission context dict.

    org_ids=None means admin (no org filter). procurement_lead and auditor
    are both in org 1000 (corrected from Task 4's bug fix).
    """
    profiles: dict[str, dict[str, Any]] = {
        "admin": {"user_id": "admin", "org_ids": None},
        "analyst": {"user_id": "analyst", "org_ids": [1000]},
        "procurement_lead": {"user_id": "procurement_lead", "org_ids": [1000]},
        "subsidiary_lead": {"user_id": "subsidiary_lead", "org_ids": [1021]},
        "auditor": {"user_id": "auditor", "org_ids": [1000]},
    }
    return profiles.get(user_context)


def _parse_timeout(env_var: str, default: int = 300) -> int:
    """Parse a timeout value from an environment variable.

    Returns the default if the env var is unset or non-numeric,
    logging a warning in the latter case so misconfiguration is visible.
    """
    raw = os.environ.get(env_var, str(default))
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "invalid_timeout_env",
            env_var=env_var,
            raw_value=raw,
            default=default,
        )
        return default


def _strip_fences(text: str) -> str:
    """Strip markdown code fences and <think> blocks from LLM output."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"^```\w*\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


async def run_offline_eval(
    cases: list[EvalCase],
    runs: int = 3,
    threshold: float = 0.8,
) -> list[EvalResult]:
    """Run offline eval: generate nGQL with real LLM, score with rules + judge.

    Args:
        cases: List of EvalCase objects (cases with offline=None are skipped).
        runs: Default number of runs per case (overridden by case.offline.judge.runs).
        threshold: Pass-rate threshold for marking a case as passed.

    Returns:
        List of EvalResult, one per case that has an offline section.
    """
    adapter = build_llm_adapter()
    judge = LLMJudge(build_judge_adapter())
    schema_info = get_schema_info()

    # Lazy import to avoid circular deps at module load time.
    from honeybadge.llm.adapter import generate_ngql

    results: list[EvalResult] = []
    for case in cases:
        if case.offline is None:
            continue

        ctx = _build_user_context(case.user_context)
        run_passes: list[bool] = []
        run_scores: list[int] = []
        rule_failures: list[str] = []
        judge_reasons: list[str] = []

        case_runs = case.offline.judge.runs if case.offline.judge.runs is not None else runs
        for run_idx in range(case_runs):
            try:
                # 1. Generate nGQL with real LLM
                llm_resp = await generate_ngql(
                    adapter,
                    case.question,
                    schema_info=schema_info,
                    ontology_info=render_ontology(case.question),
                    user_context=ctx,
                )
                generated_ngql = _strip_fences(llm_resp.content)

                # 2. Rule scoring (skip if no ci section)
                all_rules_pass = True
                if case.ci:
                    for check in case.ci.checks:
                        check_dict = {"type": check.type, **check.params}
                        result = run_check(check_dict, generated_ngql, ctx)
                        if not result.passed:
                            all_rules_pass = False
                            rule_failures.append(f"{check.type}: {result.detail}")

                # 3. LLM-as-judge (only if rules pass — save API cost)
                if all_rules_pass:
                    score, reason = await judge.evaluate(
                        question=case.question,
                        generated_ngql=generated_ngql,
                        rubric=case.offline.judge.rubric,
                    )
                    run_scores.append(score)
                    judge_reasons.append(reason)
                    passed = score >= case.offline.judge.pass_criteria
                else:
                    run_scores.append(0)
                    judge_reasons.append("Skipped — rule check failed")
                    passed = False

                run_passes.append(passed)
                logger.debug(
                    "eval_run_complete",
                    case_id=case.id,
                    run=run_idx + 1,
                    passed=passed,
                    rules_pass=all_rules_pass,
                )
            except Exception as e:
                # Broad catch: any LLM failure (network, timeout, 500, rate
                # limit) should not abort the entire suite. generate_ngql
                # wraps errors as LLMGenerationError; judge.evaluate may raise
                # LLMError/LLMTimeoutError/RateLimitExceeded. We record the
                # failure and continue to the next run.
                logger.warning(
                    "eval_run_failed",
                    case_id=case.id,
                    run=run_idx + 1,
                    error=str(e),
                )
                run_passes.append(False)
                run_scores.append(0)
                judge_reasons.append(str(e))
                rule_failures.append(f"run_error: {type(e).__name__}: {e}")
                continue

        pass_rate = compute_pass_rate(run_passes)
        results.append(EvalResult(
            case_id=case.id,
            category=case.category,
            pass_rate=pass_rate,
            passed=pass_rate >= threshold,
            run_scores=run_scores,
            rule_failures=rule_failures,
            judge_reasons=judge_reasons,
        ))

    return results


def main() -> None:
    """CLI entry point: honeybadge-eval --offline --runs 3 --report html.

    Reporters (json/html/markdown) are imported lazily inside main() so
    that running tests does not require the reporter modules (Task 10).
    """
    import argparse
    import asyncio

    from eval.case_loader import load_all_cases
    from eval.stats import summarize_results

    parser = argparse.ArgumentParser(description="HoneyBadge LLM eval suite")
    parser.add_argument("--offline", action="store_true", help="Run offline eval with real LLM")
    parser.add_argument("--runs", type=int, default=3, help="N runs per case")
    parser.add_argument("--threshold", type=float, default=0.8, help="Pass-rate threshold")
    parser.add_argument("--report", choices=["json", "html", "markdown"], default="json")
    parser.add_argument("--cases-dir", default="eval/cases", help="Cases directory")
    args = parser.parse_args()

    if not args.offline:
        parser.error("Use --offline to run offline eval. CI layer: pytest eval/ci/ -m eval_ci")

    cases = load_all_cases(Path(args.cases_dir))
    print(f"Loaded {len(cases)} cases from {args.cases_dir}")

    results = asyncio.run(run_offline_eval(cases, runs=args.runs, threshold=args.threshold))
    summary = summarize_results(results, threshold=args.threshold)

    print(f"\nEval complete: {summary.passed}/{summary.total} passed ({summary.pass_rate:.1%})")
    for cat, stats in summary.by_category.items():
        print(f"  {cat}: {stats['passed']}/{stats['count']} ({stats['pass_rate']:.1%})")

    # Lazy imports — reporters are created in Task 10.
    if args.report == "json":
        from eval.reporters.json_reporter import generate_json_report
        generate_json_report(results, summary, Path("eval-report.json"))
    elif args.report == "html":
        from eval.reporters.html_reporter import generate_html_report
        generate_html_report(results, summary, Path("eval-report.html"))
    elif args.report == "markdown":
        from eval.reporters.markdown_reporter import generate_markdown_report
        generate_markdown_report(results, summary, Path("eval-report.md"))


if __name__ == "__main__":
    main()
