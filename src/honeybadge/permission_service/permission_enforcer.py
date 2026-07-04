"""L3 hard enforcement for NebulaGraph queries.

Canonical implementation. The MCP server copy at
``mcp-servers/honeybadge-nebula-mcp/permission_enforcer.py`` re-exports
everything from here to avoid drift.

Parses (var:Tag) patterns from MATCH clauses and TagName from LOOKUP ON
clauses, then:
  1. Hard-rejects forbidden process tags
  2. Hard-rejects unsupported operations (GO/FETCH/FIND PATH/GET SUBGRAPH)
     that bypass org_id injection
  3. Auto-names anonymous ``(:Tag)`` nodes so org_id can be injected
  4. Auto-injects missing org_id filters for org-scoped users

Known limitation: regex-based analysis does not fully parse nGQL.  String
literals are stripped before forbidden-ops and tag-name scanning to avoid
false positives, but ``_TAG_VAR_RE`` matching for org_id injection still
operates on the raw query (the structure must be preserved for correct
insertion).  The L1 validator (parser-based) is the primary defence;
this module is the hard-reject safety net.
"""
from __future__ import annotations

import re

from honeybadge.permission_service.config import ORG_SCOPED_MASTER_TAGS, PROCESS_TAGS
from honeybadge.permission_service.models import PermissionContext


class PermissionViolationError(Exception):
    """Raised when a query accesses a forbidden process."""


# Regex to extract (varname:TagName) from MATCH clauses.
# \w* (not \w+) so anonymous nodes (:TagName) are also captured.
_TAG_VAR_RE = re.compile(r'\((\w*):(\w+)\)')

# Regex to extract TagName from LOOKUP ON TagName clauses
_LOOKUP_TAG_RE = re.compile(r'\bLOOKUP\s+ON\s+(\w+)', re.IGNORECASE)

# Regex to detect unsupported nGQL operations that bypass L3 org_id injection.
# GO, FETCH, FIND PATH, GET SUBGRAPH use syntax without (var:Tag) patterns,
# so the enforcer cannot inject org_id filters. The LLM prompt restricts to
# MATCH/LOOKUP; this regex is the hard-reject safety net.
# Covers: GO [n STEPS] FROM, GO UPTO n STEPS FROM, GO n FROM,
#         FETCH [PROP] ON, FIND [SHORTEST|ALL] PATH, GET SUBGRAPH,
#         and DDL/admin commands (ADD/DROP/ALTER/DELETE/UPDATE on schema).
_FORBIDDEN_OPS_RE = re.compile(
    r'\bGO\s+(?:UPTO\s+\d+\s+STEPS\s+|\d+\s*(?:STEPS\s+)?)?FROM\b'
    r'|\bFETCH\s+(?:PROP\s+)?ON\b'
    r'|\bFIND\s+(?:SHORTEST\s+|ALL\s+)?PATH\b'
    r'|\bGET\s+SUBGRAPH\b'
    r'|\b(ADD|DROP|ALTER)\s+(?:HOSTS|USER|SPACE|TAG|EDGE|INDEX|ROLE)\b'
    r'|\bDELETE\s+(?:VERTEX|EDGE|TAG)\b'
    r'|\bUPDATE\s+(?:VERTEX|EDGE)\b'
    r'|\bINSERT\s+(?:VERTEX|EDGE)\b'
    r'|\bCHANGE\s+PASSWORD\b',
    re.IGNORECASE,
)

# Regex to match nGQL string literals (single or double quoted) for stripping.
_STRING_LITERAL_RE = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")


def _strip_string_literals(ngql: str) -> str:
    """Replace string literals with empty strings for safe regex analysis.

    Used before ``_FORBIDDEN_OPS_RE`` and the fallback tag-name scan so that
    data values containing keywords like ``"find path"`` or ``"SalesOrder"``
    do not trigger false-positive rejections.

    NOT used before ``_TAG_VAR_RE`` — the query structure must be preserved
    for org_id injection to insert at the correct position.
    """
    return _STRING_LITERAL_RE.sub("''", ngql)


def _get_tag_category(tag: str) -> str | None:
    """Return 'PTP', 'OTC', 'MASTER', or None if unknown tag."""
    for category, tags in PROCESS_TAGS.items():
        if tag in tags:
            return category
    return None


def _is_org_scoped(tag: str) -> bool:
    """Return True if this tag requires org_id filtering for non-admin users.

    PTP/OTC tags are always org-scoped.  MASTER tags are org-scoped only if
    they appear in ORG_SCOPED_MASTER_TAGS (business entities like Supplier,
    Customer, Item); global reference data (Currency, UOM) returns False.
    """
    category = _get_tag_category(tag)
    if category is None:
        return False
    if category != "MASTER":
        return True  # PTP/OTC tags are always org-scoped
    return tag in ORG_SCOPED_MASTER_TAGS


def _has_top_level_or(text: str) -> bool:
    """Return True if text contains OR at parenthesis depth 0.

    String literals are stripped first to avoid false positives from data
    values containing 'OR'.  Used to determine whether the existing WHERE
    clause needs parentheses wrapping before ``AND org_id`` is appended,
    to prevent AND/OR precedence bugs (AND binds tighter than OR in nGQL).

    Example::

        _has_top_level_or("a == 1 OR b == 2")          → True
        _has_top_level_or("a == 1 AND b == 2")         → False
        _has_top_level_or("(a == 1 OR b == 2) AND c")  → False  (OR is inside parens)
        _has_top_level_or("name == 'OR'")              → False  (OR is in string)
    """
    stripped = _STRING_LITERAL_RE.sub("''", text)
    depth = 0
    for m in re.finditer(r'[()]|\bOR\b', stripped, re.IGNORECASE):
        token = m.group()
        if token == '(':
            depth += 1
        elif token == ')':
            depth -= 1
        elif depth == 0 and token.upper() == 'OR':
            return True
    return False


def _has_org_filter(ngql: str, var: str, search_start: int = 0) -> bool:
    """Return True if ngql already contains an org_id filter for the given variable.

    ``search_start`` scopes the search to after the variable's definition,
    preventing false matches from a different MATCH scope in multi-WITH queries.
    String-literal-aware: ``var.org_id IN`` inside a string value does not count.
    """
    # Matches: var.org_id or var.TagName.org_id in IN/== forms
    in_pattern = re.compile(rf'{re.escape(var)}\.(\w+\.)?org_id\s+IN\b', re.IGNORECASE)
    eq_pattern = re.compile(rf'{re.escape(var)}\.(\w+\.)?org_id\s*==', re.IGNORECASE)
    string_ranges = [
        (m.start(), m.end()) for m in _STRING_LITERAL_RE.finditer(ngql)
    ]

    def _outside_strings(pos: int) -> bool:
        return not any(s <= pos < e for s, e in string_ranges)

    for match in in_pattern.finditer(ngql, search_start):
        if _outside_strings(match.start()):
            return True
    for match in eq_pattern.finditer(ngql, search_start):
        if _outside_strings(match.start()):
            return True
    return False


def _name_anonymous_nodes(ngql: str) -> str:
    """Assign variable names to anonymous ``(:Tag)`` nodes for PTP/OTC tags.

    NebulaGraph MATCH requires a variable name to reference tag properties in
    WHERE clauses.  Anonymous nodes like ``(:PurchaseOrder)`` cannot have
    ``org_id`` injected — they would silently bypass the L3 filter.

    This rewrites ``(:PurchaseOrder)`` to ``(_gen0:PurchaseOrder)`` so the
    enforcer can inject ``_gen0.PurchaseOrder.org_id IN [...]``.

    Only org-scoped tags (PTP/OTC + org-scoped MASTER tags like Supplier) are
    rewritten; global MASTER tags (Currency, UOM) do not need org_id filtering.
    Variable name collisions with existing variables are avoided.
    """
    existing_vars: set[str] = {
        var for var, _ in _TAG_VAR_RE.findall(ngql) if var
    }
    counter = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal counter
        var, tag = match.group(1), match.group(2)
        if var:
            return match.group(0)  # already named
        if not _is_org_scoped(tag):
            return match.group(0)  # global master/unknown: no org_id needed
        while f"_gen{counter}" in existing_vars:
            counter += 1
        new_var = f"_gen{counter}"
        existing_vars.add(new_var)
        counter += 1
        return f"({new_var}:{tag})"

    return _TAG_VAR_RE.sub(_replace, ngql)


def _find_var_scope(ngql: str, var: str, tag: str) -> int:
    """Return the position immediately after the (var:Tag) definition.

    This is used to scope WHERE/boundary keyword searches to the variable's
    own MATCH clause, preventing org_id injection in the wrong scope for
    multi-WITH queries like::

        MATCH (po:PurchaseOrder) WITH po MATCH (i:Invoice) RETURN po, i

    Without scoping, ``i.Invoice.org_id`` would be injected before the first
    ``WITH`` (where ``i`` is not yet defined), causing a NebulaGraph error.
    """
    var_def_re = re.compile(rf'\({re.escape(var)}:{re.escape(tag)}\)')
    match = var_def_re.search(ngql)
    return match.end() if match else 0


def _find_keyword_outside_strings(
    ngql: str, keyword_re: re.Pattern[str], scope_start: int = 0
) -> int | None:
    """Find the first ``keyword_re`` match after ``scope_start`` that is NOT
    inside a string literal.

    nGQL string literals (single or double quoted) can contain keywords like
    ``RETURN``, ``WHERE``, ``WITH``.  A naive ``re.search`` would match inside
    the literal, causing org_id injection to split the string and corrupt the
    query.

    This function finds all string-literal ranges first, then returns the
    first keyword match that falls outside all of them.
    """
    string_ranges = [
        (m.start(), m.end()) for m in _STRING_LITERAL_RE.finditer(ngql)
    ]
    for match in keyword_re.finditer(ngql, scope_start):
        pos = match.start()
        if not any(s <= pos < e for s, e in string_ranges):
            return pos
    return None


def _inject_org_filter(ngql: str, var: str, tag: str, org_ids: list[int]) -> str:
    """Inject org_id filter for `var` into the WHERE clause.

    Uses fully-qualified form var.TagName.org_id as required by NebulaGraph MATCH.
    Searches for the boundary keyword (WITH/RETURN/YIELD) starting from the
    variable's own ``(var:Tag)`` definition, so that multi-WITH queries inject
    in the correct scope.

    String-literal-aware: keywords like ``RETURN`` appearing inside string
    values (e.g. ``status == 'RETURN'``) are not treated as boundary keywords.
    """
    ids_str = ", ".join(str(i) for i in org_ids)
    condition = f"{var}.{tag}.org_id IN [{ids_str}]"

    # Scope the search to after the variable's definition
    scope_start = _find_var_scope(ngql, var, tag)

    boundary_re = re.compile(r'\b(WITH|RETURN|YIELD)\b', re.IGNORECASE)
    where_re = re.compile(r'\bWHERE\b', re.IGNORECASE)

    where_pos = _find_keyword_outside_strings(ngql, where_re, scope_start)
    boundary_pos = _find_keyword_outside_strings(ngql, boundary_re, scope_start)

    if boundary_pos is not None:
        insert_pos = boundary_pos
        if where_pos is not None and where_pos < boundary_pos:
            # WHERE exists in this scope — append AND before boundary.
            # If the existing WHERE has a top-level OR, wrap it in
            # parentheses first to prevent AND/OR precedence bugs:
            #   WHERE a OR b AND org_id  →  WHERE (a OR b) AND org_id
            # Without wrapping, AND binds tighter than OR, so org_id
            # would only filter the 'b' branch, leaking cross-org data.
            existing_where = ngql[where_pos + 5:insert_pos]  # +5 = len("WHERE")
            if _has_top_level_or(existing_where):
                where_end = where_pos + 5
                wrapped = ngql[where_end:insert_pos].strip()
                return (
                    ngql[:where_end]
                    + f" ({wrapped})"
                    + f" AND {condition} "
                    + ngql[insert_pos:]
                )
            return ngql[:insert_pos] + f" AND {condition} " + ngql[insert_pos:]
        else:
            # No WHERE in this scope — insert WHERE before boundary
            return ngql[:insert_pos] + f" WHERE {condition} " + ngql[insert_pos:]
    # Fallback: append at end (only reachable for syntactically incomplete
    # queries that lack WITH/RETURN/YIELD; these should be rejected by L1 first)
    if where_pos is not None:
        existing_where = ngql[where_pos + 5:]
        if _has_top_level_or(existing_where):
            where_end = where_pos + 5
            wrapped = ngql[where_end:].strip()
            return ngql[:where_end] + f" ({wrapped}) AND {condition}"
        return ngql + f" AND {condition}"
    return ngql + f" WHERE {condition}"


def _inject_org_filter_lookup(ngql: str, tag: str, org_ids: list[int]) -> str:
    """Inject org_id filter into a LOOKUP ON Tag query.

    LOOKUP syntax uses TagName.property (no variable prefix), so the
    condition is TagName.org_id IN [...] (not var.TagName.org_id).
    Insertion targets the YIELD keyword (mandatory in LOOKUP).
    String-literal-aware: keywords inside data values are not treated as
    boundary markers.
    """
    ids_str = ", ".join(str(i) for i in org_ids)
    condition = f"{tag}.org_id IN [{ids_str}]"

    where_re = re.compile(r'\bWHERE\b', re.IGNORECASE)
    yield_re = re.compile(r'\bYIELD\b', re.IGNORECASE)
    where_pos = _find_keyword_outside_strings(ngql, where_re)
    yield_pos = _find_keyword_outside_strings(ngql, yield_re)
    insert_pos = yield_pos if yield_pos is not None else len(ngql)

    if where_pos is not None and (yield_pos is None or where_pos < yield_pos):
        # WHERE already exists before YIELD — append AND.
        # Wrap in parentheses if top-level OR present (same precedence fix
        # as _inject_org_filter).
        existing_where = ngql[where_pos + 5:insert_pos]  # +5 = len("WHERE")
        if _has_top_level_or(existing_where):
            where_end = where_pos + 5
            wrapped = ngql[where_end:insert_pos].strip()
            return (
                ngql[:where_end]
                + f" ({wrapped})"
                + f" AND {condition} "
                + ngql[insert_pos:]
            )
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
        # Strip string literals first so data values like 'find path' or
        # 'GO label' don't trigger false-positive rejections.
        sanitized = _strip_string_literals(ngql)
        if _FORBIDDEN_OPS_RE.search(sanitized):
            raise PermissionViolationError(
                "不支持的查询操作: GO/FETCH/FIND PATH/GET SUBGRAPH/DDL "
                "无法注入 org_id 权限过滤，请使用 MATCH 或 LOOKUP 重写查询"
            )

        # --- 0b. Name anonymous PTP/OTC nodes so org_id can be injected ---
        # Must happen before tag_vars extraction so the renamed nodes are picked up.
        ngql = _name_anonymous_nodes(ngql)

        warnings: list[str] = []
        tag_vars = _TAG_VAR_RE.findall(ngql)  # list of (var, tag) tuples from MATCH
        lookup_tags = _LOOKUP_TAG_RE.findall(ngql)  # list of tag names from LOOKUP ON

        # --- 1. Process tag check (hard reject) ---
        # Check tags from both MATCH (var:Tag) and LOOKUP ON Tag patterns
        all_tags = {tag for _, tag in tag_vars} | set(lookup_tags)
        for tag in all_tags:
            category = _get_tag_category(tag)
            if category is None or category == "MASTER":
                continue  # unknown or master tags are always allowed
            if category not in ctx.allowed_processes:
                raise PermissionViolationError(
                    f"无权访问 {category} 数据: tag '{tag}' 不在允许的流程范围内"
                )

        # --- 1b. Fallback: scan for forbidden tag names in sanitized nGQL ---
        # Catches FETCH PROP ON TagName and other patterns the regex above might miss.
        # Uses sanitized (string-literal-stripped) nGQL to avoid false positives
        # from data values that happen to contain tag names.
        forbidden_tags: set[str] = set()
        for cat, tags in PROCESS_TAGS.items():
            if cat != "MASTER" and cat not in ctx.allowed_processes:
                forbidden_tags.update(tags)
        for tag in forbidden_tags:
            if re.search(rf'\b{tag}\b', sanitized):
                raise PermissionViolationError(
                    f"无权访问 {_get_tag_category(tag)} 数据: tag '{tag}' 不在允许的流程范围内"
                )

        # --- 2. Org filter auto-injection ---
        if ctx.org_ids is None:
            return ngql, warnings  # full org access, no injection needed

        # 2a. Inject for MATCH (var:Tag) patterns
        for var, tag in tag_vars:
            if not _is_org_scoped(tag):
                continue  # global master/unknown: no org filter required
            scope_start = _find_var_scope(ngql, var, tag)
            if not _has_org_filter(ngql, var, scope_start):
                ngql = _inject_org_filter(ngql, var, tag, ctx.org_ids)
                ids_str = ", ".join(str(i) for i in ctx.org_ids)
                warnings.append(
                    f"[PERMISSION WARNING] 自动注入 org_id 过滤条件: {var}:{tag} "
                    f"WHERE {var}.{tag}.org_id IN [{ids_str}]"
                )

        # 2b. Inject for LOOKUP ON Tag patterns
        for tag in lookup_tags:
            if not _is_org_scoped(tag):
                continue  # global master/unknown: no org filter required
            if not _has_org_filter(ngql, tag):
                ngql = _inject_org_filter_lookup(ngql, tag, ctx.org_ids)
                ids_str = ", ".join(str(i) for i in ctx.org_ids)
                warnings.append(
                    f"[PERMISSION WARNING] 自动注入 org_id 过滤条件: LOOKUP ON {tag} "
                    f"WHERE {tag}.org_id IN [{ids_str}]"
                )

        return ngql, warnings
