"""Ontology loader and keyword-based domain router.

Loading strategy:
  - All `*.md` in the resolved ontology directory are loaded once (first use).
  - Each file's Keywords header (```> **Keywords**: a, b, c```) yields the
    routing vocabulary for that domain.

Routing strategy for `select_domains(question)`:
  1. Always include `overview.md` (global schema/nGQL guide).
  2. Rank all other domains by keyword-match count against the lowercased
    question. Take the top `max_domains` (default 3).
  3. If the question contains any risk/fraud signal keyword, also include
    `constraints.md`.
  4. If no domain keyword matched, fall back to `constraints.md` +
    `master-data.md` as a safe default.

Directory resolution order:
  1. Explicit constructor argument
  2. HONEYBADGE_ONTOLOGY_DIR environment variable
  3. Repo-relative `<package_root>/../prompts/ontology`
  4. `/opt/honeybadge/prompts/ontology`
  5. `/app/prompts/ontology`
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

_ALWAYS_INCLUDE = {"overview"}
_CONSTRAINTS_KEY = "constraints"
_FALLBACK_KEYS = ("constraints", "master-data")

_RISK_SIGNAL_KEYWORDS = (
    "fraud",
    "欺诈",
    "风险",
    "risk",
    "audit",
    "审计",
    "anomaly",
    "异常",
    "violation",
    "违规",
    "suspicious",
    "可疑",
    "compliance",
    "合规",
    "duplicate",
    "重复",
    "three-way",
    "三单",
    "matching",
    "匹配",
    "hold",
    "冻结",
    "reconciliation",
    "对账",
    "circular",
    "循环",
    "split",
    "拆分",
)

_KEYWORDS_RE = re.compile(r"^\s*>\s*\*\*Keywords\*\*\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE)


@dataclass
class OntologyDomain:
    """One ontology file with its parsed routing keywords."""

    key: str
    path: Path
    content: str
    keywords: list[str] = field(default_factory=list)


def _default_search_paths() -> list[Path]:
    env = os.environ.get("HONEYBADGE_ONTOLOGY_DIR")
    paths: list[Path] = []
    if env:
        paths.append(Path(env))
    # Repo layout: src/honeybadge/ontology/loader.py → parents[3] = repo root
    pkg_root = Path(__file__).resolve().parents[3]
    paths.append(pkg_root / "prompts" / "ontology")
    paths.append(Path("/opt/honeybadge/prompts/ontology"))
    paths.append(Path("/app/prompts/ontology"))
    return paths


class OntologyLoader:
    """Loads per-domain ontology markdown files and routes questions to domains."""

    def __init__(self, ontology_dir: Path | None = None) -> None:
        self.ontology_dir: Path = self._resolve_dir(ontology_dir)
        self._domains: dict[str, OntologyDomain] = {}
        self._loaded: bool = False

    @staticmethod
    def _resolve_dir(explicit: Path | None) -> Path:
        candidates: list[Path] = []
        if explicit is not None:
            candidates.append(Path(explicit))
        candidates.extend(_default_search_paths())
        for p in candidates:
            if p and p.exists() and p.is_dir():
                return p
        raise FileNotFoundError(
            "Could not locate an ontology directory. Checked: "
            + ", ".join(str(p) for p in candidates)
            + ". Set HONEYBADGE_ONTOLOGY_DIR or mount prompts/ontology/."
        )

    # ------------------------------------------------------------------ load

    def load(self) -> None:
        """Scan the ontology directory and parse each .md file."""
        self._domains.clear()
        for md_file in sorted(self.ontology_dir.glob("*.md")):
            content = md_file.read_text(encoding="utf-8")
            keywords = self._extract_keywords(content)
            self._domains[md_file.stem] = OntologyDomain(
                key=md_file.stem,
                path=md_file,
                content=content,
                keywords=keywords,
            )
        self._loaded = True

    def reload(self) -> None:
        """Force a re-scan of the ontology directory."""
        self.load()

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    @staticmethod
    def _extract_keywords(content: str) -> list[str]:
        m = _KEYWORDS_RE.search(content)
        if not m:
            return []
        raw = m.group(1)
        # Split on commas OR Chinese commas
        parts = re.split(r"[,，]", raw)
        return [p.strip().lower() for p in parts if p.strip()]

    # ------------------------------------------------------------------ inspect

    def list_domains(self) -> list[str]:
        self._ensure_loaded()
        return sorted(self._domains.keys())

    def get_domain(self, key: str) -> OntologyDomain | None:
        self._ensure_loaded()
        return self._domains.get(key)

    # ------------------------------------------------------------------ route

    def select_domains(self, question: str, max_domains: int = 3) -> list[str]:
        """Pick the relevant domain keys for a question.

        Always includes ``overview``. Adds ``constraints`` if the question has
        risk/fraud signals. Other domains chosen by keyword-match count.
        """
        self._ensure_loaded()
        q = (question or "").lower()

        selected: list[str] = []

        # 1. Always include overview (if present)
        for key in _ALWAYS_INCLUDE:
            if key in self._domains and key not in selected:
                selected.append(key)

        # 2. Rank other domains by keyword match count
        scores: dict[str, int] = {}
        for key, dom in self._domains.items():
            if key in _ALWAYS_INCLUDE or key == _CONSTRAINTS_KEY:
                continue
            score = 0
            for kw in dom.keywords:
                if kw and kw in q:
                    score += 1
            if score > 0:
                scores[key] = score

        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        for key, _score in ranked[:max_domains]:
            if key not in selected:
                selected.append(key)

        # 3. Risk signal → include constraints
        if _CONSTRAINTS_KEY in self._domains and any(sig in q for sig in _RISK_SIGNAL_KEYWORDS):
            if _CONSTRAINTS_KEY not in selected:
                selected.append(_CONSTRAINTS_KEY)

        # 4. Safe fallback — if nothing matched beyond overview, include
        #    constraints + master-data so the LLM at least has master data and rules.
        if len(selected) <= 1:
            for fb in _FALLBACK_KEYS:
                if fb in self._domains and fb not in selected:
                    selected.append(fb)

        return selected

    # ------------------------------------------------------------------ render

    def render(self, domain_keys: list[str]) -> str:
        """Concatenate the content of the given domains with clear delimiters."""
        self._ensure_loaded()
        blocks: list[str] = []
        for key in domain_keys:
            dom = self._domains.get(key)
            if dom is None:
                continue
            blocks.append(f"<!-- BEGIN ontology/{key}.md -->")
            blocks.append(dom.content.rstrip())
            blocks.append(f"<!-- END ontology/{key}.md -->\n")
        return "\n".join(blocks)

    def render_for_question(
        self, question: str, max_domains: int = 3
    ) -> tuple[str, list[str]]:
        """One-shot: select + render. Returns (text, selected_keys)."""
        selected = self.select_domains(question, max_domains=max_domains)
        return self.render(selected), selected


# ---------------------------------------------------------------------- singleton

_default_loader: OntologyLoader | None = None


def get_loader() -> OntologyLoader:
    """Return a process-global OntologyLoader instance (lazy-initialized)."""
    global _default_loader
    if _default_loader is None:
        _default_loader = OntologyLoader()
    return _default_loader
