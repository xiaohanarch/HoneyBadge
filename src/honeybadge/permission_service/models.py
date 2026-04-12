"""Permission service data models."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal


@dataclass
class PermissionContext:
    """Represents the permission context for a user.

    Attributes:
        user_id: The user identifier
        allowed_processes: List of allowed processes (e.g., ["PTP"], ["OTC"], ["PTP", "OTC"])
        org_ids: Allowed organization IDs (None = all orgs; [2] = org_id=2 only)
        dept_ids: Allowed department IDs (reserved for future dept-level control)
        data_scope: Data scope level ("ALL" / "ORG" / "DEPT")
    """
    user_id: str
    allowed_processes: list[Literal["PTP", "OTC", "MASTER"]]
    org_ids: list[int] | None
    dept_ids: list[int] | None
    data_scope: Literal["ALL", "ORG", "DEPT"]
