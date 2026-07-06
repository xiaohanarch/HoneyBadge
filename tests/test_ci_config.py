"""Tests for CI/CD pipeline configuration.

Verifies the CI workflow file has the expected jobs and the coverage
configuration is present. These are structural tests that catch drift —
if someone removes a job or drops the coverage gate, this test fails
before the next PR merge.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CI_PATH = _PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
_COVERAGERC_PATH = _PROJECT_ROOT / ".coveragerc"


class TestCIWorkflow:
    """Verify ci.yml has the expected structure."""

    def test_ci_yml_exists(self) -> None:
        assert _CI_PATH.exists(), "ci.yml workflow must exist for CI gate"

    def test_ci_has_four_jobs(self) -> None:
        content = _CI_PATH.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        jobs = data.get("jobs", {})
        expected = {"lint", "type-check", "unit-tests", "eval-ci"}
        actual = set(jobs.keys())
        assert expected.issubset(actual), (
            f"ci.yml missing jobs: {expected - actual}. "
            f"Found: {actual}"
        )

    def test_lint_job_uses_ruff(self) -> None:
        content = _CI_PATH.read_text(encoding="utf-8")
        assert "ruff check" in content, "Lint job must run 'ruff check src tests'"

    def test_type_check_job_uses_mypy(self) -> None:
        content = _CI_PATH.read_text(encoding="utf-8")
        assert "mypy src" in content, "Type check job must run 'mypy src'"

    def test_unit_tests_have_coverage(self) -> None:
        content = _CI_PATH.read_text(encoding="utf-8")
        assert "--cov=src/honeybadge" in content, "Unit tests must collect coverage"
        assert "--cov-fail-under" in content, "Unit tests must enforce coverage threshold"

    def test_eval_ci_job_runs_eval_ci_marker(self) -> None:
        content = _CI_PATH.read_text(encoding="utf-8")
        assert "-m eval_ci" in content, "Eval CI job must run with -m eval_ci marker"

    def test_ci_triggers_on_pr(self) -> None:
        content = _CI_PATH.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        on_config = data.get("on", data.get(True, {}))  # "on" is parsed as True in YAML
        assert "pull_request" in on_config, "CI must trigger on pull requests"
        assert "push" in on_config, "CI must trigger on pushes"


class TestCoverageConfig:
    """Verify .coveragerc is configured."""

    def test_coveragerc_exists(self) -> None:
        assert _COVERAGERC_PATH.exists(), ".coveragerc must exist for coverage config"

    def test_coveragerc_has_source(self) -> None:
        content = _COVERAGERC_PATH.read_text(encoding="utf-8")
        assert "src/honeybadge" in content, "Coverage source must include src/honeybadge"

    def test_coveragerc_omits_tests(self) -> None:
        content = _COVERAGERC_PATH.read_text(encoding="utf-8")
        assert "tests/" in content, "Coverage must omit test files"

    def test_coveragerc_has_exclude_lines(self) -> None:
        content = _COVERAGERC_PATH.read_text(encoding="utf-8")
        assert "exclude_lines" in content, "Coverage must define exclude_lines"
        assert "pragma: no cover" in content

    def test_coveragerc_uses_branch_coverage(self) -> None:
        content = _COVERAGERC_PATH.read_text(encoding="utf-8")
        assert "branch = True" in content, "Coverage must use branch coverage"


class TestPytestMarkers:
    """Verify the eval_ci marker is registered."""

    def test_eval_ci_marker_registered(self) -> None:
        pytest_ini = (_PROJECT_ROOT / "pytest.ini").read_text(encoding="utf-8")
        assert "eval_ci" in pytest_ini, (
            "eval_ci marker must be registered in pytest.ini "
            "for the CI eval gate to work"
        )
