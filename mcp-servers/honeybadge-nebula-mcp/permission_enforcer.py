"""L3 hard enforcement for NebulaGraph queries — thin re-export wrapper.

The canonical implementation lives in
``src/honeybadge/permission_service/permission_enforcer.py``.
This wrapper exists so the MCP server can import ``permission_enforcer``
as a top-level module (via ``sys.path`` manipulation in ``server.py``).

Kept as a separate file (rather than a symlink) for Windows/k8s portability.
"""
from __future__ import annotations

import os
import sys

# Allow running standalone (adds src/ to path so the canonical module resolves)
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_src_path = os.path.join(_project_root, "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from honeybadge.permission_service.permission_enforcer import (  # noqa: E402,F401
    PermissionEnforcer,
    PermissionViolationError,
    _FORBIDDEN_OPS_RE,
    _LOOKUP_TAG_RE,
    _TAG_VAR_RE,
    _get_tag_category,
    _has_org_filter,
    _inject_org_filter,
    _inject_org_filter_lookup,
    _name_anonymous_nodes,
)

__all__ = [
    "PermissionEnforcer",
    "PermissionViolationError",
]
