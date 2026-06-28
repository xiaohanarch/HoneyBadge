"""Persist anomaly state across query rounds within a task."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class Anomaly:
    """A single detected anomaly."""
    type: str
    severity: str
    evidence: dict
    round: int


class AnomalyTracker:
    """File-backed anomaly tracker for cross-round deduplication.

    State is persisted to {sessions_dir}/{task_id}/anomalies.json.
    Hermes sessions/ directory provides the storage location.
    """

    def __init__(self, task_id: str, sessions_dir: str = "~/.hermes/sessions"):
        self._task_id = task_id
        self._path = Path(sessions_dir).expanduser() / task_id / "anomalies.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, anomalies: list[Anomaly]) -> None:
        """Save anomalies, deduplicating by (type, severity).

        Existing anomalies with the same (type, severity) are not duplicated.
        New anomalies are appended.
        """
        existing = self.load()
        seen = {(a.type, a.severity) for a in existing}
        for a in anomalies:
            if (a.type, a.severity) not in seen:
                existing.append(a)
                seen.add((a.type, a.severity))
        self._path.write_text(
            json.dumps([asdict(a) for a in existing], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self) -> list[Anomaly]:
        """Load all persisted anomalies for this task."""
        if not self._path.exists():
            return []
        data = json.loads(self._path.read_text(encoding="utf-8"))
        return [Anomaly(**d) for d in data]
