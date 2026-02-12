"""Data retention manager.

Automatically cleans up old data based on configurable policies.
Supports: conversations, audit_logs, webhook_deliveries.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


@dataclass
class RetentionPolicy:
    """Retention policy for a data category."""
    category: str           # "conversations", "audit_logs", "webhook_deliveries"
    max_age_days: int       # Max age in days (0 = never delete)
    max_count: int          # Max records to keep (0 = unlimited)


DEFAULT_POLICIES = [
    RetentionPolicy("conversations", max_age_days=90, max_count=0),
    RetentionPolicy("audit_logs", max_age_days=365, max_count=0),
    RetentionPolicy("webhook_deliveries", max_age_days=30, max_count=10000),
]


# Allowlist of valid categories for security
_VALID_CATEGORIES = {"conversations", "audit_logs", "webhook_deliveries"}


# DB path mapping per category
_DB_PATHS: dict[str, str] = {
    "conversations": "data/conversations.db",
    "audit_logs": "data/audit.db",
    "webhook_deliveries": "data/webhooks.db",
}


class RetentionManager:
    """Policy-based data retention manager."""

    def __init__(
        self,
        policies: Optional[list[RetentionPolicy]] = None,
        db_paths: Optional[dict[str, str]] = None,
    ):
        """Initialize.

        Args:
            policies: List of retention policies. Uses DEFAULT_POLICIES if None.
            db_paths: Override DB paths per category. Uses _DB_PATHS if None.
        """
        self._policies = policies or list(DEFAULT_POLICIES)
        self._db_paths = db_paths or dict(_DB_PATHS)

    def get_policy(self, category: str) -> Optional[RetentionPolicy]:
        """Get policy for a category."""
        for p in self._policies:
            if p.category == category:
                return p
        return None

    def get_stats(self) -> dict:
        """Get retention statistics for each category.

        Returns:
            {
                "conversations": {"total": N, "policy": {...}},
                "audit_logs": {"total": N, "policy": {...}},
                "webhook_deliveries": {"total": N, "policy": {...}},
            }
        """
        stats = {}
        for policy in self._policies:
            stats[policy.category] = {
                "policy": {
                    "max_age_days": policy.max_age_days,
                    "max_count": policy.max_count,
                },
                "total": self._count_records(policy.category),
            }
        return stats

    def run_cleanup(self) -> dict:
        """Execute retention cleanup for all categories.

        Returns:
            {"conversations": N_deleted, "audit_logs": N_deleted, ...}
        """
        results = {}
        for policy in self._policies:
            deleted = self._cleanup_category(policy)
            results[policy.category] = deleted
            if deleted > 0:
                logger.info(
                    f"Retention cleanup: {policy.category} - deleted {deleted} records"
                )
        return results

    def _get_db_path(self, category: str) -> str:
        """Get database path for a category."""
        return self._db_paths.get(category, "")

    def _connect(self, category: str) -> Optional[sqlite3.Connection]:
        """Create a connection to the category's DB. Returns None if DB missing."""
        db_path = self._get_db_path(category)
        if not db_path or not Path(db_path).exists():
            return None
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA busy_timeout=5000")
            return conn
        except Exception as e:
            logger.warning(f"Cannot connect to {db_path}: {e}")
            return None

    def _count_records(self, category: str) -> int:
        """Count records in a category."""
        conn = self._connect(category)
        if not conn:
            return 0
        try:
            table = self._get_table_name(category)
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            return cursor.fetchone()[0]
        except Exception as e:
            logger.warning(f"Count failed for {category}: {e}")
            return 0
        finally:
            conn.close()

    def _cleanup_category(self, policy: RetentionPolicy) -> int:
        """Clean up records for a single category based on policy."""
        # Validate category is in allowlist
        if policy.category not in _VALID_CATEGORIES:
            logger.error(f"Invalid category for cleanup: {policy.category}")
            return 0

        deleted = 0
        try:
            if policy.max_age_days > 0:
                deleted += self._delete_older_than(
                    policy.category, policy.max_age_days
                )
            if policy.max_count > 0:
                deleted += self._delete_excess(
                    policy.category, policy.max_count
                )
        except Exception as e:
            logger.error(f"Retention cleanup error for {policy.category}: {e}")
        return deleted

    def _get_table_name(self, category: str) -> str:
        """Get primary table name for category."""
        return {
            "conversations": "conversations",
            "audit_logs": "audit_events",
            "webhook_deliveries": "webhook_deliveries",
        }.get(category, "")

    def _get_timestamp_column(self, category: str) -> str:
        """Get timestamp column name for category."""
        return {
            "conversations": "updated_at",
            "audit_logs": "timestamp",
            "webhook_deliveries": "delivered_at",
        }.get(category, "")

    def _get_id_column(self, category: str) -> str:
        """Get primary key column for category."""
        return {
            "conversations": "id",
            "audit_logs": "id",
            "webhook_deliveries": "id",
        }.get(category, "")

    def _delete_older_than(self, category: str, max_age_days: int) -> int:
        """Delete records older than max_age_days."""
        conn = self._connect(category)
        if not conn:
            return 0
        try:
            cutoff = (
                datetime.utcnow() - timedelta(days=max_age_days)
            ).isoformat()
            table = self._get_table_name(category)
            ts_col = self._get_timestamp_column(category)

            # Special handling for conversations: delete messages first
            if category == "conversations":
                # Enable foreign keys so CASCADE works, or delete manually
                conn.execute("PRAGMA foreign_keys=ON")
                cursor = conn.execute(
                    f"DELETE FROM {table} WHERE {ts_col} < ?",  # noqa: S608
                    (cutoff,),
                )
            else:
                cursor = conn.execute(
                    f"DELETE FROM {table} WHERE {ts_col} < ?",  # noqa: S608
                    (cutoff,),
                )

            deleted = cursor.rowcount
            conn.commit()
            return deleted
        except Exception as e:
            logger.warning(f"Delete older_than failed for {category}: {e}")
            return 0
        finally:
            conn.close()

    def _delete_excess(self, category: str, max_count: int) -> int:
        """Delete records exceeding max_count (keep newest)."""
        conn = self._connect(category)
        if not conn:
            return 0
        try:
            table = self._get_table_name(category)
            ts_col = self._get_timestamp_column(category)
            id_col = self._get_id_column(category)

            # Count total
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            total = cursor.fetchone()[0]

            if total <= max_count:
                return 0

            # Special handling for conversations: enable CASCADE
            if category == "conversations":
                conn.execute("PRAGMA foreign_keys=ON")

            # Delete oldest records exceeding max_count
            excess = total - max_count
            cursor = conn.execute(
                f"DELETE FROM {table} WHERE {id_col} IN "  # noqa: S608
                f"(SELECT {id_col} FROM {table} ORDER BY {ts_col} ASC LIMIT ?)",
                (excess,),
            )
            deleted = cursor.rowcount
            conn.commit()
            return deleted
        except Exception as e:
            logger.warning(f"Delete excess failed for {category}: {e}")
            return 0
        finally:
            conn.close()
