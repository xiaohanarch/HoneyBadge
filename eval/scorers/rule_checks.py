# eval/scorers/rule_checks.py
"""Rule-based nGQL checks — shared between CI and offline layers.

Each check takes a raw nGQL string and a user context dict, returns a
CheckResult indicating pass/fail with a detail message.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Type aliases for check parameters and user context
CheckParams = dict[str, Any]
UserContext = dict[str, Any]
CheckHandler = Callable[[str, UserContext, CheckParams], "CheckResult"]


@dataclass
class CheckResult:
    """Result of a single rule check."""
    passed: bool
    detail: str = ""


def run_check(check: CheckParams, ngql: str, user_context: UserContext | None) -> CheckResult:
    """Dispatch to the appropriate check function by type."""
    check_type = check["type"]
    params: CheckParams = {k: v for k, v in check.items() if k != "type"}
    ctx: UserContext = user_context or {}
    handler = _CHECKS.get(check_type)
    if handler is None:
        return CheckResult(False, f"Unknown check type: {check_type}")
    return handler(ngql, ctx, params)


# --- Individual checks ---

def _check_syntax_valid(ngql: str, ctx: UserContext, params: CheckParams) -> CheckResult:
    stripped = ngql.strip()
    if not stripped:
        return CheckResult(False, "Empty query")
    parens = 0
    for ch in stripped:
        if ch == "(":
            parens += 1
        elif ch == ")":
            parens -= 1
        if parens < 0:
            return CheckResult(False, "Unbalanced parentheses")
    if parens != 0:
        return CheckResult(False, f"Unbalanced parentheses: {parens} unclosed")
    known_keywords = ("MATCH", "LOOKUP", "GO", "FETCH", "FIND", "SHOW", "YIELD", "RETURN", "GET")
    first_word = stripped.split()[0].upper() if stripped.split() else ""
    if first_word not in known_keywords:
        return CheckResult(False, f"Unknown starting keyword: {first_word}")
    return CheckResult(True)


def _check_has_limit(ngql: str, ctx: UserContext, params: CheckParams) -> CheckResult:
    if re.search(r"\bLIMIT\s+\d+", ngql, re.IGNORECASE):
        return CheckResult(True)
    return CheckResult(False, "No LIMIT clause found")


def _check_forbidden_ops_absent(ngql: str, ctx: UserContext, params: CheckParams) -> CheckResult:
    ops: list[str] = params.get("ops", [])
    found: list[str] = []
    for op in ops:
        # Word-boundary match; spaces in op match \s+
        pattern = r"\b" + r"\s+".join(re.escape(w) for w in op.split()) + r"\b"
        if re.search(pattern, ngql, re.IGNORECASE):
            found.append(op)
    if found:
        return CheckResult(False, f"Forbidden operations found: {found}")
    return CheckResult(True)


def _check_expected_tags(ngql: str, ctx: UserContext, params: CheckParams) -> CheckResult:
    expected: list[str] = params.get("tags", [])
    found_tags = set(re.findall(r"\((\w+):(\w+)\)", ngql))  # (var:Tag)
    found_tag_names: set[str] = {t for _, t in found_tags}
    # Also catch LOOKUP ON Tag
    found_tag_names.update(re.findall(r"LOOKUP\s+ON\s+(\w+)", ngql, re.IGNORECASE))
    missing = [t for t in expected if t not in found_tag_names]
    if missing:
        return CheckResult(False, f"Missing expected tags: {missing}")
    return CheckResult(True)


def _check_expected_edges(ngql: str, ctx: UserContext, params: CheckParams) -> CheckResult:
    expected: list[str] = params.get("edges", [])
    found_edges: set[str] = set()
    # Forward: -[:Edge]-> or -[Edge]->
    found_edges.update(re.findall(r"-\[:?(\w+)\]->", ngql))
    # Reverse: <-[:Edge]- or <-[Edge]-
    found_edges.update(re.findall(r"<-\[:?(\w+)\]-", ngql))
    # LOOKUP/GO OVER Edge
    found_edges.update(re.findall(r"OVER\s+(\w+)", ngql, re.IGNORECASE))
    missing = [e for e in expected if e not in found_edges]
    if missing:
        return CheckResult(False, f"Missing expected edges: {missing}")
    return CheckResult(True)


def _check_order_by_uses_alias(ngql: str, ctx: UserContext, params: CheckParams) -> CheckResult:
    m = re.search(r"ORDER\s+BY\s+(.+?)(?:LIMIT|$)", ngql, re.IGNORECASE)
    if not m:
        return CheckResult(True)  # No ORDER BY — nothing to check
    sort_items = m.group(1)
    # If any sort item contains a dot (property path), it's wrong
    if "." in sort_items:
        return CheckResult(
            False,
            f"ORDER BY uses property path instead of alias: {sort_items.strip()}",
        )
    return CheckResult(True)


def _check_no_optional_match_where(ngql: str, ctx: UserContext, params: CheckParams) -> CheckResult:
    # Detect OPTIONAL MATCH ... WHERE (NebulaGraph doesn't support this)
    pattern = r"OPTIONAL\s+MATCH.*?WHERE"
    if re.search(pattern, ngql, re.IGNORECASE | re.DOTALL):
        return CheckResult(False, "OPTIONAL MATCH followed by WHERE — not supported in NebulaGraph")
    return CheckResult(True)


def _check_has_org_id(ngql: str, ctx: UserContext, params: CheckParams) -> CheckResult:
    # Admin users don't need org_id filter
    org_ids = ctx.get("org_ids")
    if org_ids is None:
        return CheckResult(True)  # admin or no org restriction
    if re.search(r"org_id\s+IN\s*\[", ngql, re.IGNORECASE):
        return CheckResult(True)
    if re.search(r"org_id\s*==", ngql, re.IGNORECASE):
        return CheckResult(True)
    return CheckResult(False, "Non-admin user query missing org_id filter")


_WRITE_OPS_RE = re.compile(
    r"\b(INSERT|UPDATE|UPSERT|DELETE|DROP|CREATE|ALTER)\b", re.IGNORECASE
)
_FORBIDDEN_QUERY_OPS_RE = re.compile(
    r"\b(GO|FETCH|FIND\s+PATH|GET\s+SUBGRAPH)\b", re.IGNORECASE
)


def _check_rejected_by_L1(ngql: str, ctx: UserContext, params: CheckParams) -> CheckResult:
    """Expect the query to be rejected by L1 (syntax/validate_syntax)."""
    stripped = ngql.strip()
    if not stripped:
        return CheckResult(True, "Rejected: empty query")
    if _WRITE_OPS_RE.search(stripped):
        return CheckResult(True, "Rejected: write operation")
    # If it's a valid read query, L1 would NOT reject it
    syntax = _check_syntax_valid(stripped, ctx, params)
    if not syntax.passed:
        return CheckResult(True, f"Rejected: {syntax.detail}")
    return CheckResult(False, "Query was NOT rejected by L1 (valid syntax, no write op)")


def _check_rejected_by_L3(ngql: str, ctx: UserContext, params: CheckParams) -> CheckResult:
    """Expect the query to be rejected by L3 (forbidden ops / permission)."""
    stripped = ngql.strip()
    if _FORBIDDEN_QUERY_OPS_RE.search(stripped):
        return CheckResult(True, "Rejected: forbidden query operation (GO/FETCH/FIND PATH)")
    if _WRITE_OPS_RE.search(stripped):
        return CheckResult(True, "Rejected: write operation")
    return CheckResult(False, "Query was NOT rejected by L3 (no forbidden ops detected)")


_CHECKS: dict[str, CheckHandler] = {
    "syntax_valid": _check_syntax_valid,
    "has_limit": _check_has_limit,
    "forbidden_ops_absent": _check_forbidden_ops_absent,
    "expected_tags": _check_expected_tags,
    "expected_edges": _check_expected_edges,
    "order_by_uses_alias": _check_order_by_uses_alias,
    "no_optional_match_where": _check_no_optional_match_where,
    "has_org_id": _check_has_org_id,
    "rejected_by_L1": _check_rejected_by_L1,
    "rejected_by_L3": _check_rejected_by_L3,
}
