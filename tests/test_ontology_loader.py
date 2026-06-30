"""Unit tests for honeybadge.ontology.loader — routing + render behavior."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from honeybadge.ontology import OntologyLoader, get_loader

# --------------------------------------------------------------------- fixtures


def _write(p: Path, body: str) -> None:
    p.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")


@pytest.fixture
def tmp_ontology(tmp_path: Path) -> Path:
    """Minimal ontology directory covering every routing path."""
    d = tmp_path / "ontology"
    d.mkdir()

    _write(
        d / "overview.md",
        """
        # Overview
        > **Purpose**: global index
        > **Keywords**: schema, 总览
        """,
    )
    _write(
        d / "supplier.md",
        """
        # Supplier
        > **Purpose**: supplier master
        > **Keywords**: supplier, 供应商, vendor, 供方, bank
        """,
    )
    _write(
        d / "procurement.md",
        """
        # Procurement
        > **Purpose**: PTP
        > **Keywords**: po, 采购订单, purchase order, receipt, 收货
        """,
    )
    _write(
        d / "payable.md",
        """
        # Payable
        > **Purpose**: AP
        > **Keywords**: invoice, 发票, payment, 付款
        """,
    )
    _write(
        d / "constraints.md",
        """
        # Constraints
        > **Purpose**: risk rules
        > **Keywords**: constraint, rule, 规则
        """,
    )
    _write(
        d / "master-data.md",
        """
        # Master Data
        > **Purpose**: master
        > **Keywords**: item, 物料
        """,
    )
    # No-keyword file — must not be selected by keyword ranking
    _write(
        d / "empty.md",
        """
        # Empty
        > No keywords header here.
        """,
    )
    return d


# ----------------------------------------------------------------------- tests


def test_loader_discovers_all_md(tmp_ontology: Path) -> None:
    loader = OntologyLoader(ontology_dir=tmp_ontology)
    assert set(loader.list_domains()) == {
        "overview",
        "supplier",
        "procurement",
        "payable",
        "constraints",
        "master-data",
        "empty",
    }


def test_extract_keywords_splits_ascii_and_chinese_commas(tmp_ontology: Path) -> None:
    loader = OntologyLoader(ontology_dir=tmp_ontology)
    loader.load()
    kw = loader.get_domain("supplier").keywords
    assert "supplier" in kw
    assert "供应商" in kw
    assert "vendor" in kw
    # Lowercased
    assert all(k == k.lower() for k in kw)


def test_empty_file_has_no_keywords(tmp_ontology: Path) -> None:
    loader = OntologyLoader(ontology_dir=tmp_ontology)
    loader.load()
    assert loader.get_domain("empty").keywords == []


def test_select_always_includes_overview(tmp_ontology: Path) -> None:
    loader = OntologyLoader(ontology_dir=tmp_ontology)
    # Trivial question — no domain keywords match
    selected = loader.select_domains("今天天气不错")
    assert "overview" in selected


def test_select_ranks_by_keyword_match(tmp_ontology: Path) -> None:
    loader = OntologyLoader(ontology_dir=tmp_ontology)
    selected = loader.select_domains("列出该供应商的所有采购订单 supplier po")
    # Expect: overview always, supplier + procurement ranked high
    assert "overview" in selected
    assert "supplier" in selected
    assert "procurement" in selected


def test_select_risk_signal_adds_constraints(tmp_ontology: Path) -> None:
    loader = OntologyLoader(ontology_dir=tmp_ontology)
    selected = loader.select_domains("check for fraud in invoice payments")
    assert "constraints" in selected
    # Constraints must not block regular matches
    assert "payable" in selected


def test_select_fallback_when_nothing_matches(tmp_ontology: Path) -> None:
    loader = OntologyLoader(ontology_dir=tmp_ontology)
    selected = loader.select_domains("xyzzy nothing matches")
    # overview + fallback (constraints + master-data)
    assert "overview" in selected
    assert "constraints" in selected
    assert "master-data" in selected


def test_select_max_domains_respected(tmp_ontology: Path) -> None:
    loader = OntologyLoader(ontology_dir=tmp_ontology)
    # Question that matches many domains — must cap non-overview/non-constraints picks
    q = "supplier 供应商 po 采购订单 invoice 发票 item 物料"
    selected = loader.select_domains(q, max_domains=2)
    # overview + 2 ranked (supplier and procurement or payable) — no more than overview+max_domains ranked picks.
    # May still include constraints via risk signal (none here), so expect exactly overview + 2 = 3.
    assert selected[0] == "overview"
    assert len(selected) == 1 + 2


def test_render_wraps_with_delimiters(tmp_ontology: Path) -> None:
    loader = OntologyLoader(ontology_dir=tmp_ontology)
    text = loader.render(["overview", "supplier"])
    assert "<!-- BEGIN ontology/overview.md -->" in text
    assert "<!-- END ontology/overview.md -->" in text
    assert "<!-- BEGIN ontology/supplier.md -->" in text
    assert "# Supplier" in text


def test_render_for_question_is_select_plus_render(tmp_ontology: Path) -> None:
    loader = OntologyLoader(ontology_dir=tmp_ontology)
    text, keys = loader.render_for_question("supplier 供应商 bank account fraud")
    assert "overview" in keys
    assert "supplier" in keys
    assert "constraints" in keys  # risk signal "fraud"
    for k in keys:
        assert f"<!-- BEGIN ontology/{k}.md -->" in text


def test_real_prompts_directory_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke test against the real shipped prompts/ontology/*.md."""
    loader = OntologyLoader()  # uses default search paths
    domains = loader.list_domains()
    # Must include at least the 12-file split we ship
    expected = {
        "overview",
        "supplier",
        "procurement",
        "payable",
        "receivable",
        "customer",
        "xla",
        "gl",
        "inventory",
        "cash-mgmt",
        "master-data",
        "constraints",
    }
    missing = expected - set(domains)
    assert not missing, f"Missing shipped ontology files: {missing}"


def test_get_loader_singleton() -> None:
    a = get_loader()
    b = get_loader()
    assert a is b
