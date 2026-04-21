"""TDD tests for fast-query.sh — Manager direct-MCP skill."""
import pathlib
import subprocess


SCRIPT = "hiclaw/manager/agent/skills/fast-query/fast-query.sh"


def test_script_exists():
    assert pathlib.Path(SCRIPT).exists(), f"{SCRIPT} not found"


def test_bash_syntax_is_valid():
    result = subprocess.run(
        ["bash", "-n", SCRIPT],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Bash syntax error in {SCRIPT}: {result.stderr}"


def test_missing_question_exits_1():
    """When --question is not provided, script exits 1 and prints JSON error."""
    result = subprocess.run(
        ["bash", SCRIPT],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert '"error"' in result.stdout
    assert "--question" in result.stdout or "required" in result.stdout.lower()


def test_question_provided_does_not_exit_1():
    """With --question provided, argument parsing succeeds (exit code != 1).

    In a test environment without mcporter, the script will exit 2 (nGQL generation
    failed) because mcporter is not available. That is expected — the test only
    verifies --question was parsed correctly (not the missing-argument path).
    """
    result = subprocess.run(
        ["bash", SCRIPT, "--question", "查询供应商总数", "--user-id", "admin"],
        capture_output=True,
        text=True,
    )
    # Should NOT exit 1 (missing question) — any other code is fine
    assert result.returncode != 1, (
        f"Script exited 1 (missing question) even though --question was provided. "
        f"stdout: {result.stdout!r}, stderr: {result.stderr!r}"
    )
