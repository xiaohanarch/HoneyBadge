"""Unit tests for AnomalyTracker — cross-round anomaly persistence."""
import pytest
from common.session_state import Anomaly, AnomalyTracker


class TestAnomalyDataclass:
    def test_is_frozen(self):
        a = Anomaly(type="duplicate_invoice", severity="WARNING", evidence={"id": 1}, round=1)
        assert a.type == "duplicate_invoice"
        with pytest.raises(Exception):
            a.type = "modified"


class TestAnomalyTrackerLoad:
    def test_load_returns_empty_for_new_task(self, tmp_path):
        tracker = AnomalyTracker("task-001", sessions_dir=str(tmp_path))
        assert tracker.load() == []

    def test_load_returns_saved_anomalies(self, tmp_path):
        tracker = AnomalyTracker("task-001", sessions_dir=str(tmp_path))
        anomalies = [
            Anomaly(type="duplicate_invoice", severity="WARNING", evidence={"id": 1}, round=1),
        ]
        tracker.save(anomalies)
        loaded = tracker.load()
        assert len(loaded) == 1
        assert loaded[0].type == "duplicate_invoice"


class TestAnomalyTrackerDedup:
    def test_dedup_by_type_and_severity(self, tmp_path):
        tracker = AnomalyTracker("task-001", sessions_dir=str(tmp_path))
        # Round 1: flag a WARNING
        tracker.save([
            Anomaly(type="duplicate_invoice", severity="WARNING", evidence={"id": 1}, round=1),
        ])
        # Round 2: same anomaly flagged again
        tracker.save([
            Anomaly(type="duplicate_invoice", severity="WARNING", evidence={"id": 1}, round=2),
        ])
        loaded = tracker.load()
        assert len(loaded) == 1  # deduplicated

    def test_different_severity_not_deduped(self, tmp_path):
        tracker = AnomalyTracker("task-001", sessions_dir=str(tmp_path))
        tracker.save([
            Anomaly(type="duplicate_invoice", severity="WARNING", evidence={"id": 1}, round=1),
        ])
        tracker.save([
            Anomaly(type="duplicate_invoice", severity="ALERT", evidence={"id": 1}, round=2),
        ])
        loaded = tracker.load()
        assert len(loaded) == 2  # WARNING and ALERT are different

    def test_different_type_not_deduped(self, tmp_path):
        tracker = AnomalyTracker("task-001", sessions_dir=str(tmp_path))
        tracker.save([
            Anomaly(type="duplicate_invoice", severity="WARNING", evidence={"id": 1}, round=1),
            Anomaly(type="three_way_mismatch", severity="WARNING", evidence={"id": 2}, round=1),
        ])
        loaded = tracker.load()
        assert len(loaded) == 2


class TestAnomalyTrackerPersistence:
    def test_persists_across_instances(self, tmp_path):
        tracker1 = AnomalyTracker("task-001", sessions_dir=str(tmp_path))
        tracker1.save([
            Anomaly(type="unusual_payment", severity="ALERT", evidence={}, round=3),
        ])
        # New instance, same task_id
        tracker2 = AnomalyTracker("task-001", sessions_dir=str(tmp_path))
        loaded = tracker2.load()
        assert len(loaded) == 1
        assert loaded[0].type == "unusual_payment"

    def test_different_tasks_isolated(self, tmp_path):
        tracker1 = AnomalyTracker("task-001", sessions_dir=str(tmp_path))
        tracker1.save([
            Anomaly(type="a", severity="INFO", evidence={}, round=1),
        ])
        tracker2 = AnomalyTracker("task-002", sessions_dir=str(tmp_path))
        assert tracker2.load() == []
