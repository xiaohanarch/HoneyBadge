"""L3 hard enforcement for NebulaGraph queries.

Parses (var:Tag) patterns from MATCH clauses and:
  1. Hard-rejects forbidden process tags
  2. Auto-injects missing org_id filters for org-scoped users
"""
from __future__ import annotations

import re

from honeybadge.permission_service.config import PROCESS_TAGS
from honeybadge.permission_service.models import PermissionContext


class PermissionViolationError(Exception):
    """Raised when a query accesses a forbidden process."""


# Regex to extract (varname:TagName) from MATCH clauses
_TAG_VAR_RE = re.compile(r'\((\w+):(\w+)\)')


def _get_tag_category(tag: str) -> str | None:
    """Return 'PTP', 'OTC', 'MASTER', or None if unknown tag."""
    for category, tags in PROCESS_TAGS.items():
        if tag in tags:
            return category
    return None


def _has_org_filter(ngql: str, var: str) -> bool:
    """Return True if ngql already contains an org_id filter for the given variable."""
    # Matches: var.org_id or var.TagName.org_id in IN/== forms
    in_pattern = re.compile(rf'{re.escape(var)}\.(\w+\.)?org_id\s+IN\b', re.IGNORECASE)
    eq_pattern = re.compile(rf'{re.escape(var)}\.(\w+\.)?org_id\s*==', re.IGNORECASE)
    return bool(in_pattern.search(ngql) or eq_pattern.search(ngql))


def _inject_org_filter(ngql: str, var: str, tag: str, org_ids: list[int]) -> str:
    """Inject org_id filter for `var` into the WHERE clause.

    Uses fully-qualified form var.TagName.org_id as required by NebulaGraph MATCH.
    """
    ids_str = ", ".join(str(i) for i in org_ids)
    condition = f"{var}.{tag}.org_id IN [{ids_str}]"

    # If WHERE already exists, append AND
    where_re = re.compile(r'\bWHERE\b', re.IGNORECASE)
    if where_re.search(ngql):
        # Insert before RETURN/YIELD by finding the first of those keywords
        return_re = re.compile(r'\b(RETURN|YIELD)\b', re.IGNORECASE)
        match = return_re.search(ngql)
        if match:
            insert_pos = match.start()
            return ngql[:insert_pos] + f" AND {condition} " + ngql[insert_pos:]
        return ngql + f" AND {condition}"
    else:
        # Insert WHERE before RETURN/YIELD
        return_re = re.compile(r'\b(RETURN|YIELD)\b', re.IGNORECASE)
        match = return_re.search(ngql)
        if match:
            insert_pos = match.start()
            return ngql[:insert_pos] + f" WHERE {condition} " + ngql[insert_pos:]
        return ngql + f" WHERE {condition}"


class PermissionEnforcer:
    """Hard enforcement gate for NebulaGraph queries.

    Usage:
        enforcer = PermissionEnforcer()
        ngql, warnings = enforcer.enforce(ngql, permission_context)
        # ngql is safe to execute; warnings list any auto-injected filters
    """

    def enforce(
        self, ngql: str, ctx: PermissionContext
    ) -> tuple[str, list[str]]:
        """Enforce permissions on an nGQL statement.

        Returns:
            (modified_ngql, warnings) where modified_ngql has org filters injected.

        Raises:
            PermissionViolationError: if the query accesses a forbidden process tag.
        """
        warnings: list[str] = []
        tag_vars = _TAG_VAR_RE.findall(ngql)  # list of (var, tag) tuples

        # --- 1a. Process tag check via (var:Tag) patterns (hard reject) ---
        for var, tag in tag_vars:
            category = _get_tag_category(tag)
            if category is None or category == "MASTER":
                continue  # unknown or master tags are always allowed
            if category not in ctx.allowed_processes:
                raise PermissionViolationError(
                    f"无权访问 {category} 数据: tag '{tag}' 不在允许的流程范围内"
                )

        # --- 1b. Fallback: scan for forbidden tag names anywhere in nGQL ---
        # Catches LOOKUP ON TagName, FETCH PROP ON TagName, etc.
        forbidden_tags: set[str] = set()
        for cat, tags in PROCESS_TAGS.items():
            if cat != "MASTER" and cat not in ctx.allowed_processes:
                forbidden_tags.update(tags)
        for tag in forbidden_tags:
            if re.search(rf'\b{tag}\b', ngql):
                category = _get_tag_category(tag)
                raise PermissionViolationError(
                    f"无权访问 {category} 数据: tag '{tag}' 不在允许的流程范围内"
                )

        # --- 2. Org filter auto-injection ---
        if ctx.org_ids is None:
            return ngql, warnings  # full org access, no injection needed

        for var, tag in tag_vars:
            category = _get_tag_category(tag)
            if category is None or category == "MASTER":
                continue  # master data: no org filter required
            if not _has_org_filter(ngql, var):
                ngql = _inject_org_filter(ngql, var, tag, ctx.org_ids)
                ids_str = ", ".join(str(i) for i in ctx.org_ids)
                warnings.append(
                    f"[PERMISSION WARNING] 自动注入 org_id 过滤条件: {var}:{tag} "
                    f"WHERE {var}.{tag}.org_id IN [{ids_str}]"
                )

        return ngql, warnings
