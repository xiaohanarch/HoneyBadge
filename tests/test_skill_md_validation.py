"""Structured validation for project SKILL.md files.

Ensures the HiClaw agent skill definitions — the core reusable template
artifact — follow the required structure so they remain machine-parseable
and semantically complete:

  * Frontmatter with name + description
  * name matches the enclosing directory (routing depends on this)
  * At least one hard-constraint keyword (CRITICAL / MUST / NEVER / DO NOT)
  * MCP tool references use valid server.tool patterns
  * Skills that call validate_and_execute propagate user identity (L3)
  * No hardcoded credentials
  * Non-empty body with a title heading

These are CI-checkable structural guarantees. The semantic quality of the
instructions is still human-reviewed, but drift in structure is caught here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# The 5 project-specific SKILL.md files (excluding vendored plugins).
_SKILL_DIRS = [
    _PROJECT_ROOT / "hiclaw" / "manager" / "agent" / "skills",
    _PROJECT_ROOT / "hiclaw" / "workers" / "graph-worker" / "agent" / "skills",
    _PROJECT_ROOT / "hiclaw" / "workers" / "analytics-worker" / "agent" / "skills",
]

# Valid MCP server.tool patterns referenced by mcporter call ...
_VALID_MCP_TOOL_RE = re.compile(
    r"honeybadge-(?:nebula|audit|cache)\.[a-z_]+"
)

# mcporter call <tool> extraction
_MCPORTER_CALL_RE = re.compile(r"mcporter\s+call\s+(honeybadge-[\w.]+)")

# Hard-constraint keywords that turn a soft instruction into a flagged directive.
_HARD_CONSTRAINT_KEYWORDS = ("CRITICAL", "MUST", "NEVER", "DO NOT", "绝对")


def _discover_skill_files() -> list[Path]:
    """Find all project SKILL.md files under hiclaw/."""
    files: list[Path] = []
    for base in _SKILL_DIRS:
        if not base.exists():
            continue
        files.extend(base.rglob("SKILL.md"))
    return sorted(files)


def _parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Split SKILL.md into (frontmatter_dict, body).

    Returns ({}, content) if no frontmatter block is present.
    """
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    fm_text = parts[1].strip()
    body = parts[2]
    fm: dict[str, str] = {}
    for line in fm_text.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
    return fm, body


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def skill_files() -> list[Path]:
    return _discover_skill_files()


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

class TestSkillMdStructure:
    """Every project SKILL.md must follow the required structure."""

    def test_skill_files_exist(self, skill_files: list[Path]) -> None:
        """At least 5 project skills should exist (manager + workers)."""
        assert len(skill_files) >= 5, (
            f"Expected >= 5 project SKILL.md files, found {len(skill_files)}: "
            f"{[str(p.relative_to(_PROJECT_ROOT)) for p in skill_files]}"
        )

    def test_frontmatter_has_required_fields(self, skill_files: list[Path]) -> None:
        """Every SKILL.md must have frontmatter with name + description."""
        missing: list[str] = []
        for path in skill_files:
            content = path.read_text(encoding="utf-8")
            fm, _ = _parse_frontmatter(content)
            for field in ("name", "description"):
                if not fm.get(field):
                    missing.append(f"{path.relative_to(_PROJECT_ROOT)}: missing '{field}'")
        assert not missing, "SKILL.md frontmatter incomplete:\n" + "\n".join(missing)

    def test_name_matches_directory(self, skill_files: list[Path]) -> None:
        """The frontmatter 'name' must match the parent directory name.

        HiClaw routing and SOUL.md references depend on this correspondence.
        """
        mismatches: list[str] = []
        for path in skill_files:
            content = path.read_text(encoding="utf-8")
            fm, _ = _parse_frontmatter(content)
            expected = path.parent.name
            actual = fm.get("name", "")
            if actual != expected:
                mismatches.append(
                    f"{path.relative_to(_PROJECT_ROOT)}: name='{actual}' but dir='{expected}'"
                )
        assert not mismatches, "SKILL.md name/dir mismatch:\n" + "\n".join(mismatches)

    def test_body_has_title_heading(self, skill_files: list[Path]) -> None:
        """The markdown body must start with a level-1 heading."""
        missing: list[str] = []
        for path in skill_files:
            content = path.read_text(encoding="utf-8")
            _, body = _parse_frontmatter(content)
            stripped = body.lstrip()
            if not stripped.startswith("# "):
                missing.append(str(path.relative_to(_PROJECT_ROOT)))
        assert not missing, "SKILL.md missing # title heading:\n" + "\n".join(missing)

    def test_body_is_nonempty(self, skill_files: list[Path]) -> None:
        """Body must have substantial content (>= 5 non-blank lines)."""
        thin: list[str] = []
        for path in skill_files:
            content = path.read_text(encoding="utf-8")
            _, body = _parse_frontmatter(content)
            non_blank = [ln for ln in body.splitlines() if ln.strip()]
            if len(non_blank) < 5:
                thin.append(f"{path.relative_to(_PROJECT_ROOT)} ({len(non_blank)} lines)")
        assert not thin, "SKILL.md too thin:\n" + "\n".join(thin)


# ---------------------------------------------------------------------------
# Semantic tests — hard constraints
# ---------------------------------------------------------------------------

class TestSkillMdHardConstraints:
    """SKILL.md files must contain hard-constraint keywords.

    SKILL.md is the primary agent instruction layer. Without at least one
    CRITICAL/MUST/NEVER directive, the skill degrades to soft guidance that
    the LLM can ignore. The template standard requires at least one
    hard-constraint keyword per skill.
    """

    def test_each_skill_has_hard_constraint_keyword(
        self, skill_files: list[Path]
    ) -> None:
        missing: list[str] = []
        for path in skill_files:
            content = path.read_text(encoding="utf-8")
            # Case-insensitive: "Do NOT", "must", "Never" all count.
            lowered = content.lower()
            if not any(kw.lower() in lowered for kw in _HARD_CONSTRAINT_KEYWORDS):
                missing.append(str(path.relative_to(_PROJECT_ROOT)))
        assert not missing, (
            "SKILL.md without any hard-constraint keyword "
            "(CRITICAL/MUST/NEVER/DO NOT):\n" + "\n".join(missing)
        )


# ---------------------------------------------------------------------------
# MCP tool reference tests
# ---------------------------------------------------------------------------

class TestSkillMdMcpToolRefs:
    """MCP tool references in SKILL.md must use valid server.tool patterns."""

    def test_mcporter_calls_reference_valid_tools(
        self, skill_files: list[Path]
    ) -> None:
        """Every `mcporter call <tool>` must reference a known MCP server."""
        invalid: list[str] = []
        for path in skill_files:
            content = path.read_text(encoding="utf-8")
            for match in _MCPORTER_CALL_RE.finditer(content):
                tool = match.group(1)
                if not _VALID_MCP_TOOL_RE.fullmatch(tool):
                    invalid.append(
                        f"{path.relative_to(_PROJECT_ROOT)}: invalid tool '{tool}'"
                    )
        assert not invalid, "Invalid MCP tool references:\n" + "\n".join(invalid)


# ---------------------------------------------------------------------------
# L3 user identity propagation
# ---------------------------------------------------------------------------

class TestSkillMdUserIdentityPropagation:
    """Skills that invoke validate_and_execute must propagate user identity.

    This is the SKILL.md-side complement to the L3 fail-closed guard in
    validate_and_execute_impl: the skill instructions must tell the LLM to
    extract user_id and pass it as user_context. Without this, the L3 guard
    would reject every query in fail-closed mode.
    """

    # Direct invocation: `mcporter call honeybadge-nebula.validate_and_execute`
    _DIRECT_VAE_RE = re.compile(
        r"mcporter\s+call\s+honeybadge-nebula\.validate_and_execute"
    )

    def test_validate_and_execute_skills_mention_user_identity(
        self, skill_files: list[Path]
    ) -> None:
        """Skills that DIRECTLY call validate_and_execute via mcporter must
        instruct the LLM to pass user identity.

        Skills that delegate to shell scripts or Python modules (which handle
        user_context internally) are not flagged — only direct mcporter calls
        are checked, because those are the ones where the LLM constructs the
        --args JSON and could omit user_context.
        """
        violators: list[str] = []
        for path in skill_files:
            content = path.read_text(encoding="utf-8")
            if not self._DIRECT_VAE_RE.search(content):
                continue
            # Must mention user_id or user_context near the invocation.
            if "user_id" not in content and "user_context" not in content:
                violators.append(str(path.relative_to(_PROJECT_ROOT)))
        assert not violators, (
            "SKILL.md directly calls validate_and_execute via mcporter but does "
            "not mention user_id/user_context (L3 will reject):\n"
            + "\n".join(violators)
        )


# ---------------------------------------------------------------------------
# Security: no hardcoded credentials
# ---------------------------------------------------------------------------

class TestSkillMdNoCredentials:
    """SKILL.md must not contain hardcoded credentials."""

    _SECRET_PATTERNS = [
        (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "API key pattern (sk-...)"),
        (re.compile(r"(?i)password\s*[:=]\s*['\"][^'\"]{4,}['\"]"), "password assignment"),
        (re.compile(r"(?i)token\s*[:=]\s*['\"][^'\"]{20,}['\"]"), "token assignment"),
        (re.compile(r"(?i)secret\s*[:=]\s*['\"][^'\"]{8,}['\"]"), "secret assignment"),
    ]

    def test_no_hardcoded_secrets(self, skill_files: list[Path]) -> None:
        offenders: list[str] = []
        for path in skill_files:
            content = path.read_text(encoding="utf-8")
            for pattern, label in self._SECRET_PATTERNS:
                if pattern.search(content):
                    offenders.append(
                        f"{path.relative_to(_PROJECT_ROOT)}: {label}"
                    )
        assert not offenders, "Hardcoded credentials in SKILL.md:\n" + "\n".join(offenders)
