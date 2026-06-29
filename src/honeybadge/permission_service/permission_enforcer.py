"""L3 hard enforcement for NebulaGraph queries.

Canonical implementation. The MCP server copy at
``mcp-servers/honeybadge-nebula-mcp/permission_enforcer.py`` re-exports
everything from here to avoid drift.

Parses (var:Tag) patterns from MATCH clauses and TagName from LOOKUP ON
clauses, then:
  1. Hard-rejects forbidden process tags
  2. Hard-rejects unsupported operations (GO/FETCH/FIND PATH) that bypass
     org_id injection
  3. Auto-names anonymous ``(:Tag)`` nodes so org_id can be injected
  4. Auto-injects missing org_id filters for org-scoped users
"""
from __future__ import annotations

import re

from honeybadge.permission_service.config import PROCESS_TAGS
from honeybadge.permission_service.models import PermissionContext


class PermissionViolationError(Exception):
    """Raised when a query accesses a forbidden process."""


# Regex to extract (varname:TagName) from MATCH clauses.
# \w* (not \w+) so anonymous nodes (:TagName) are also captured.
_TAG_VAR_RE = re.compile(r'\((\w*):(\w+)\)')

# Regex to extract TagName from LOOKUP ON TagName clauses
_LOOKUP_TAG_RE = re.compile(r'\bLOOKUP\s+ON\s+(\w+)', re.IGNORECASE)

# Regex to detect unsupported nGQL operations that bypass L3 org_id injection.
# GO, FETCH, FIND PATH use syntax without (var:Tag) patterns, so the enforcer
# cannot inject org_id filters. The LLM prompt restricts to MATCH/LOOKUP; this
# regex is the hard-reject safety net for when the LLM doesn't comply.
_FORBIDDEN_OPS_RE = re.compile(
    r'\bGO\s+(?:\d+\s+STEPS\s+)?FROM\b'
    r'|\bFETCH\s+PROP\s+ON\b'
    r'|\bFIND\s+(?:SHORTEST\s+|ALL\s+)?PATH\b',
    re.IGNORECASE,
)


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


def _name_anonymous_nodes(ngql: str) -> str:
    """Assign variable names to anonymous ``(:Tag)`` nodes for PTP/OTC tags.

    NebulaGraph MATCH requires a variable name to reference tag properties in
    WHERE clauses.  Anonymous nodes like ``(:PurchaseOrder)`` cannot have
    ``org_id`` injected — they would silently bypass the L3 filter.

    This rewrites ``(:PurchaseOrder)`` to ``(_gen0:PurchaseOrder)`` so the
    enforcer can inject ``_gen0.PurchaseOrder.org_id IN [...]``.

    Only PTP/OTC tags are rewritten (MASTER tags do not need org_id filtering).
    Variable name collisions with existing variables are avoided.
    """
    existing_vars: set[str] = set(
        var for var, _ in _TAG_VAR_RE.findall(ngql) if var
    )
    counter = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal counter
        var, tag = match.group(1), match.group(2)
        if var:
            return match.group(0)  # already named
        category = _get_tag_category(tag)
        if category is None or category == "MASTER":
            return match.group(0)  # master/unknown: no org_id needed
        while f"_gen{counter}" in existing_vars:
            counter += 1
        new_var = f"_gen{counter}"
        existing_vars.add(new_var)
        counter += 1
        return f"({new_var}:{tag})"

    return _TAG_VAR_RE.sub(_replace, ngql)


def _inject_org_filter(ngql: str, var: str, tag: str, org_ids: list[int]) -> str:
    """Inject org_id filter for `var` into the WHERE clause.

    Uses fully-qualified form var.TagName.org_id as required by NebulaGraph MATCH.
    """
    ids_str = ", ".join(str(i) for i in org_ids)
    condition = f"{var}.{tag}.org_id IN [{ids_str}]"

    # If WHERE already exists, append AND
    # Insert before the first clause boundary keyword (WITH/RETURN/YIELD).
    # WITH is critical: it ends the current WHERE scope. If we insert after
    # WITH (e.g. before RETURN), the variable is out of scope and the query
    # silently returns 0 results.
    # Limitation: pipe-chained queries (|) are not supported — insert targets
    # the first boundary keyword, which may be inside a subquery, not at root.
    boundary_re = re.compile(r'\b(WITH|RETURN|YIELD)\b', re.IGNORECASE)
    where_re = re.compile(r'\bWHERE\b', re.IGNORECASE)
    if where_re.search(ngql):
        match = boundary_re.search(ngql)
        if match:
            insert_pos = match.start()
            return ngql[:insert_pos] + f" AND {condition} " + ngql[insert_pos:]
        # Fallback: append at end (only reachable for syntactically incomplete
        # queries that lack WITH/RETURN/YIELD; these should be rejected by L1 first)
        return ngql + f" AND {condition}"
    else:
        match = boundary_re.search(ngql)
        if match:
            insert_pos = match.start()
            return ngql[:insert_pos] + f" WHERE {condition} " + ngql[insert_pos:]
        # Fallback: append at end (same caveat as above)
        return ngql + f" WHERE {condition}"


def _inject_org_filter_lookup(ngql: str, tag: str, org_ids: list[int]) -> str:
    """Inject org_id filter into a LOOKUP ON Tag query.

    LOOKUP syntax uses TagName.property (no variable prefix), so the
    condition is TagName.org_id IN [...] (not var.TagName.org_id).
    Insertion targets the YIELD keyword (mandatory in LOOKUP).
    """
    ids_str = ", ".join(str(i) for i in org_ids)
    condition = f"{tag}.org_id IN [{ids_str}]"

    where_re = re.compile(r'\bWHERE\b', re.IGNORECASE)
    yield_re = re.compile(r'\bYIELD\b', re.IGNORECASE)
    match = yield_re.search(ngql)
    insert_pos = match.start() if match else len(ngql)

    if where_re.search(ngql):
        # WHERE already exists before YIELD — append AND
        return ngql[:insert_pos] + f" AND {condition} " + ngql[insert_pos:]
    else:
        # No WHERE — insert WHERE before YIELD
        return ngql[:insert_pos] + f" WHERE {condition} " + ngql[insert_pos:]


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
            PermissionViolationError: if the query accesses a forbidden process
            tag or uses an unsupported nGQL operation.
        """
        # --- 0. Reject unsupported operations (defense in depth) ---
        # GO, FETCH, FIND PATH bypass L3 org_id injection because their syntax
        # doesn't use (var:Tag) patterns. The LLM prompt restricts to MATCH/LOOKUP;
        # this hard-rejects any query that slips through.
        if _FORBIDDEN_OPS_RE.search(ngql):
            raise PermissionViolationError(
                "不支持的查询操作: GO/FETCH/FIND PATH 无法注入 org_id 权限过滤，"
                "请使用 MATCH 或 LOOKUP 重写查询"
            )

        # --- 0b. Name anonymous PTP/OTC nodes so org_id can be injected ---
        # Must happen before tag_vars extraction so the renamed nodes are picked up.
        ngql = _name_anonymous_nodes(ngql)

        warnings: list[str] = []
        tag_vars = _TAG_VAR_RE.findall(ngql)  # list of (var, tag) tuples from MATCH
        lookup_tags = _LOOKUP_TAG_RE.findall(ngql)  # list of tag names from LOOKUP ON

        # --- 1. Process tag check (hard reject) ---
        # Check tags from both MATCH (var:Tag) and LOOKUP ON Tag patterns
        all_tags = set(tag for _, tag in tag_vars) | set(lookup_tags)
        for tag in all_tags:
            category = _get_tag_category(tag)
            if category is None or category == "MASTER":
                continue  # unknown or master tags are always allowed
            if category not in ctx.allowed_processes:
                raise PermissionViolationError(
                    f"无权访问 {category} 数据: tag '{tag}' 不在允许的流程范围内"
                )

        # --- 1b. Fallback: scan for forbidden tag names anywhere in nGQL ---
        # Catches FETCH PROP ON TagName and other patterns the regex above might miss.
        forbidden_tags: set[str] = set()
        for cat, tags in PROCESS_TAGS.items():
            if cat != "MASTER" and cat not in ctx.allowed_processes:
                forbidden_tags.update(tags)
        for tag in forbidden_tags:
            if re.search(rf'\b{tag}\b', ngql):
                raise PermissionViolationError(
                    f"无权访问 {_get_tag_category(tag)} 数据: tag '{tag}' 不在允许的流程范围内"
                )

        # --- 2. Org filter auto-injection ---
        if ctx.org_ids is None:
            return ngql, warnings  # full org access, no injection needed

        # 2a. Inject for MATCH (var:Tag) patterns
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

        # 2b. Inject for LOOKUP ON Tag patterns
        for tag in lookup_tags:
            category = _get_tag_category(tag)
            if category is None or category == "MASTER":
                continue  # master data: no org filter required
            if not _has_org_filter(ngql, tag):
                ngql = _inject_org_filter_lookup(ngql, tag, ctx.org_ids)
                ids_str = ", ".join(str(i) for i in ctx.org_ids)
                warnings.append(
                    f"[PERMISSION WARNING] 自动注入 org_id 过滤条件: LOOKUP ON {tag} "
                    f"WHERE {tag}.org_id IN [{ids_str}]"
                )

        return ngql, warnings
