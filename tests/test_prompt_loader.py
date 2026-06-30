"""Unit tests for honeybadge.llm.prompt_loader — file loading + cache behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from honeybadge.llm.prompt_loader import load_prompt, reload

# --------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def _clear_prompt_cache() -> None:
    """Reset the prompt loader cache + resolved dir before and after each test."""
    reload()
    yield
    reload()


# ----------------------------------------------------------------------- tests


def test_load_prompt_finds_cypher_system() -> None:
    """The shipped cypher_system.md loads and contains key nGQL rules."""
    content = load_prompt("cypher_system")
    assert content is not None, "cypher_system.md should exist in prompts/"
    # Key sections from the battle-tested inline prompt
    assert "MATCH" in content
    assert "LOOKUP" in content
    assert "ORDER BY" in content
    # The forbidden query types (L3 permission constraint)
    assert "GO" in content
    # Business concept mapping section
    assert "业务概念" in content
    # The file must NOT contain the dynamic placeholders — those are appended in code
    assert "{schema_info}" not in content
    assert "{ontology_info}" not in content


def test_load_prompt_finds_summarize_system() -> None:
    """The shipped summarize_system.md loads and contains key summarization rules."""
    content = load_prompt("summarize_system")
    assert content is not None, "summarize_system.md should exist in prompts/"
    assert "分析" in content
    assert "不要修改任何数值" in content
    assert "风险等级" in content


def test_load_prompt_returns_none_for_missing_file(tmp_path: Path) -> None:
    """Missing prompt files return None gracefully (no exception)."""
    d = tmp_path / "prompts"
    d.mkdir()
    result = load_prompt("does_not_exist", prompts_dir=d)
    assert result is None


def test_load_prompt_returns_none_for_missing_file_in_empty_dir(tmp_path: Path) -> None:
    """An empty prompts directory yields None for any name."""
    d = tmp_path / "prompts"
    d.mkdir()
    assert load_prompt("cypher_system", prompts_dir=d) is None


def test_load_prompt_reads_file_content(tmp_path: Path) -> None:
    """load_prompt returns the exact file content via explicit prompts_dir."""
    d = tmp_path / "prompts"
    d.mkdir()
    (d / "demo.md").write_text("# Demo Prompt\n\nHello world.", encoding="utf-8")
    result = load_prompt("demo", prompts_dir=d)
    assert result == "# Demo Prompt\n\nHello world."


def test_reload_clears_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """reload() invalidates the module-level cache."""
    d = tmp_path / "prompts"
    d.mkdir()
    (d / "cached.md").write_text("cached content", encoding="utf-8")
    monkeypatch.setenv("HONEYBADGE_PROMPTS_DIR", str(d))

    from honeybadge.llm import prompt_loader

    # Load → populates cache
    result = prompt_loader.load_prompt("cached")
    assert result == "cached content"
    assert "cached" in prompt_loader._prompt_cache

    # reload → clears cache
    prompt_loader.reload()
    assert "cached" not in prompt_loader._prompt_cache
    assert len(prompt_loader._prompt_cache) == 0
    # And resolved dir is reset so env change is re-read
    assert prompt_loader._resolved_dir is None


def test_env_var_resolves_prompts_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """HONEYBADGE_PROMPTS_DIR env var directs file resolution."""
    d = tmp_path / "custom-prompts"
    d.mkdir()
    (d / "via_env.md").write_text("env-loaded", encoding="utf-8")
    monkeypatch.setenv("HONEYBADGE_PROMPTS_DIR", str(d))

    result = load_prompt("via_env")
    assert result == "env-loaded"


def test_real_prompts_directory_loads() -> None:
    """Smoke test against the real shipped prompts/ directory."""
    cypher = load_prompt("cypher_system")
    summarize = load_prompt("summarize_system")
    assert cypher is not None, "shipped prompts/cypher_system.md must load"
    assert summarize is not None, "shipped prompts/summarize_system.md must load"
    # Sanity: cypher prompt is substantial (battle-tested inline content)
    assert len(cypher) > 500
    assert len(summarize) > 200
