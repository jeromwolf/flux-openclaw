"""Tests for retention.py -- RetentionPolicy, RetentionManager."""
import sqlite3
from datetime import datetime, timedelta

from openclaw.retention import RetentionPolicy, RetentionManager, DEFAULT_POLICIES


# ---------------------------------------------------------------------------
# RetentionPolicy dataclass
# ---------------------------------------------------------------------------

class TestRetentionPolicy:

    def test_default_conversations_policy(self):
        p = DEFAULT_POLICIES[0]
        assert p.category == "conversations"
        assert p.max_age_days == 90
        assert p.max_count == 0

    def test_default_audit_logs_policy(self):
        p = DEFAULT_POLICIES[1]
        assert p.category == "audit_logs"
        assert p.max_age_days == 365
        assert p.max_count == 0

    def test_default_webhook_deliveries_policy(self):
        p = DEFAULT_POLICIES[2]
        assert p.category == "webhook_deliveries"
        assert p.max_age_days == 30
        assert p.max_count == 10000

    def test_constructor_stores_fields(self):
        p = RetentionPolicy(category="custom", max_age_days=7, max_count=500)
        assert p.category == "custom"
        assert p.max_age_days == 7
        assert p.max_count == 500


# ---------------------------------------------------------------------------
# Helpers to build temp databases
# ---------------------------------------------------------------------------

def _create_conversations_db(path, rows):
    """Create conversations.db with given rows: list of (id, updated_at_iso)."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE conversations (id TEXT PRIMARY KEY, updated_at TEXT)"
    )
    conn.executemany(
        "INSERT INTO conversations (id, updated_at) VALUES (?, ?)", rows
    )
    conn.commit()
    conn.close()


def _create_audit_db(path, rows):
    """Create audit.db with given rows: list of (id, timestamp_iso)."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE audit_events (id INTEGER PRIMARY KEY, timestamp TEXT)"
    )
    conn.executemany(
        "INSERT INTO audit_events (id, timestamp) VALUES (?, ?)", rows
    )
    conn.commit()
    conn.close()


def _create_webhooks_db(path, rows):
    """Create webhooks.db with given rows: list of (id, delivered_at_iso)."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE webhook_deliveries (id INTEGER PRIMARY KEY, delivered_at TEXT)"
    )
    conn.executemany(
        "INSERT INTO webhook_deliveries (id, delivered_at) VALUES (?, ?)", rows
    )
    conn.commit()
    conn.close()


def _count_rows(db_path, table):
    conn = sqlite3.connect(str(db_path))
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return n


def _iso(days_ago=0):
    """Return ISO timestamp for `days_ago` days in the past."""
    return (datetime.utcnow() - timedelta(days=days_ago)).isoformat()


# ---------------------------------------------------------------------------
# RetentionManager.__init__
# ---------------------------------------------------------------------------

class TestRetentionManagerInit:

    def test_uses_default_policies_when_none(self):
        rm = RetentionManager()
        for dp in DEFAULT_POLICIES:
            assert rm.get_policy(dp.category) is not None

    def test_accepts_custom_policies(self):
        custom = [RetentionPolicy("x", 1, 2)]
        rm = RetentionManager(policies=custom)
        assert rm.get_policy("x") is not None
        assert rm.get_policy("conversations") is None


# ---------------------------------------------------------------------------
# get_policy
# ---------------------------------------------------------------------------

class TestGetPolicy:

    def test_returns_matching_policy(self):
        rm = RetentionManager()
        p = rm.get_policy("conversations")
        assert p is not None
        assert p.category == "conversations"

    def test_returns_none_for_unknown(self):
        rm = RetentionManager()
        assert rm.get_policy("unknown_category") is None


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

class TestGetStats:

    def test_returns_stats_for_each_category(self, tmp_path):
        conv_db = tmp_path / "conv.db"
        _create_conversations_db(conv_db, [("1", _iso(0)), ("2", _iso(1))])

        policies = [RetentionPolicy("conversations", 90, 0)]
        db_paths = {"conversations": str(conv_db)}
        rm = RetentionManager(policies=policies, db_paths=db_paths)

        stats = rm.get_stats()
        assert "conversations" in stats
        assert stats["conversations"]["total"] == 2
        assert stats["conversations"]["policy"]["max_age_days"] == 90

    def test_returns_zero_total_when_db_missing(self, tmp_path):
        policies = [RetentionPolicy("conversations", 90, 0)]
        db_paths = {"conversations": str(tmp_path / "nonexistent.db")}
        rm = RetentionManager(policies=policies, db_paths=db_paths)

        stats = rm.get_stats()
        assert stats["conversations"]["total"] == 0


# ---------------------------------------------------------------------------
# _delete_older_than
# ---------------------------------------------------------------------------

class TestDeleteOlderThan:

    def test_deletes_old_records(self, tmp_path):
        db = tmp_path / "conv.db"
        _create_conversations_db(db, [
            ("old1", _iso(100)),
            ("old2", _iso(95)),
            ("recent", _iso(5)),
        ])

        policies = [RetentionPolicy("conversations", max_age_days=90, max_count=0)]
        db_paths = {"conversations": str(db)}
        rm = RetentionManager(policies=policies, db_paths=db_paths)

        deleted = rm._delete_older_than("conversations", 90)
        assert deleted == 2
        assert _count_rows(db, "conversations") == 1

    def test_preserves_recent_records(self, tmp_path):
        db = tmp_path / "conv.db"
        _create_conversations_db(db, [
            ("r1", _iso(1)),
            ("r2", _iso(10)),
            ("r3", _iso(30)),
        ])

        policies = [RetentionPolicy("conversations", max_age_days=90, max_count=0)]
        db_paths = {"conversations": str(db)}
        rm = RetentionManager(policies=policies, db_paths=db_paths)

        deleted = rm._delete_older_than("conversations", 90)
        assert deleted == 0
        assert _count_rows(db, "conversations") == 3

    def test_audit_logs_table(self, tmp_path):
        db = tmp_path / "audit.db"
        _create_audit_db(db, [
            (1, _iso(400)),
            (2, _iso(10)),
        ])

        policies = [RetentionPolicy("audit_logs", max_age_days=365, max_count=0)]
        db_paths = {"audit_logs": str(db)}
        rm = RetentionManager(policies=policies, db_paths=db_paths)

        deleted = rm._delete_older_than("audit_logs", 365)
        assert deleted == 1
        assert _count_rows(db, "audit_events") == 1

    def test_missing_db_returns_zero(self, tmp_path):
        policies = [RetentionPolicy("conversations", 90, 0)]
        db_paths = {"conversations": str(tmp_path / "nope.db")}
        rm = RetentionManager(policies=policies, db_paths=db_paths)

        assert rm._delete_older_than("conversations", 90) == 0


# ---------------------------------------------------------------------------
# _delete_excess
# ---------------------------------------------------------------------------

class TestDeleteExcess:

    def test_deletes_oldest_exceeding_max(self, tmp_path):
        db = tmp_path / "wh.db"
        _create_webhooks_db(db, [
            (1, _iso(5)),   # oldest -- should be deleted
            (2, _iso(3)),   # second oldest -- should be deleted
            (3, _iso(1)),   # keep
        ])

        policies = [RetentionPolicy("webhook_deliveries", max_age_days=0, max_count=1)]
        db_paths = {"webhook_deliveries": str(db)}
        rm = RetentionManager(policies=policies, db_paths=db_paths)

        deleted = rm._delete_excess("webhook_deliveries", 1)
        assert deleted == 2
        assert _count_rows(db, "webhook_deliveries") == 1

    def test_preserves_all_when_under_max(self, tmp_path):
        db = tmp_path / "wh.db"
        _create_webhooks_db(db, [
            (1, _iso(1)),
            (2, _iso(0)),
        ])

        policies = [RetentionPolicy("webhook_deliveries", 0, 10)]
        db_paths = {"webhook_deliveries": str(db)}
        rm = RetentionManager(policies=policies, db_paths=db_paths)

        deleted = rm._delete_excess("webhook_deliveries", 10)
        assert deleted == 0
        assert _count_rows(db, "webhook_deliveries") == 2

    def test_missing_db_returns_zero(self, tmp_path):
        policies = [RetentionPolicy("webhook_deliveries", 0, 5)]
        db_paths = {"webhook_deliveries": str(tmp_path / "nope.db")}
        rm = RetentionManager(policies=policies, db_paths=db_paths)

        assert rm._delete_excess("webhook_deliveries", 5) == 0


# ---------------------------------------------------------------------------
# run_cleanup
# ---------------------------------------------------------------------------

class TestRunCleanup:

    def test_applies_all_policies(self, tmp_path):
        conv_db = tmp_path / "conv.db"
        audit_db = tmp_path / "audit.db"
        wh_db = tmp_path / "wh.db"

        # 2 old conversations (>10 days), 1 recent
        _create_conversations_db(conv_db, [
            ("c1", _iso(20)),
            ("c2", _iso(15)),
            ("c3", _iso(1)),
        ])
        # 1 old audit event (>5 days), 1 recent
        _create_audit_db(audit_db, [
            (1, _iso(10)),
            (2, _iso(1)),
        ])
        # 3 webhook deliveries, max_count=2
        _create_webhooks_db(wh_db, [
            (1, _iso(3)),
            (2, _iso(2)),
            (3, _iso(0)),
        ])

        policies = [
            RetentionPolicy("conversations", max_age_days=10, max_count=0),
            RetentionPolicy("audit_logs", max_age_days=5, max_count=0),
            RetentionPolicy("webhook_deliveries", max_age_days=0, max_count=2),
        ]
        db_paths = {
            "conversations": str(conv_db),
            "audit_logs": str(audit_db),
            "webhook_deliveries": str(wh_db),
        }
        rm = RetentionManager(policies=policies, db_paths=db_paths)

        results = rm.run_cleanup()
        assert results["conversations"] == 2
        assert results["audit_logs"] == 1
        assert results["webhook_deliveries"] == 1

    def test_returns_deletion_counts_dict(self, tmp_path):
        conv_db = tmp_path / "conv.db"
        _create_conversations_db(conv_db, [("c1", _iso(0))])

        policies = [RetentionPolicy("conversations", max_age_days=90, max_count=0)]
        db_paths = {"conversations": str(conv_db)}
        rm = RetentionManager(policies=policies, db_paths=db_paths)

        results = rm.run_cleanup()
        assert isinstance(results, dict)
        assert "conversations" in results
        assert results["conversations"] == 0


# ---------------------------------------------------------------------------
# Missing DB graceful handling
# ---------------------------------------------------------------------------

class TestMissingDB:

    def test_run_cleanup_no_crash_on_missing_dbs(self, tmp_path):
        """All DB paths point to non-existent files -- should return 0s."""
        db_paths = {
            "conversations": str(tmp_path / "no1.db"),
            "audit_logs": str(tmp_path / "no2.db"),
            "webhook_deliveries": str(tmp_path / "no3.db"),
        }
        rm = RetentionManager(db_paths=db_paths)
        results = rm.run_cleanup()
        assert results["conversations"] == 0
        assert results["audit_logs"] == 0
        assert results["webhook_deliveries"] == 0

    def test_get_stats_no_crash_on_missing_dbs(self, tmp_path):
        db_paths = {
            "conversations": str(tmp_path / "no1.db"),
            "audit_logs": str(tmp_path / "no2.db"),
            "webhook_deliveries": str(tmp_path / "no3.db"),
        }
        rm = RetentionManager(db_paths=db_paths)
        stats = rm.get_stats()
        for cat in ["conversations", "audit_logs", "webhook_deliveries"]:
            assert stats[cat]["total"] == 0
