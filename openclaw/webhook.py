"""flux-openclaw Webhook/Event System

SQLite-backed webhook registration and async HTTP delivery.
Uses only stdlib (no external dependencies).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

# ---- Event type constants ----

EVENT_CHAT_COMPLETED = "chat.completed"
EVENT_CHAT_ERROR = "chat.error"
EVENT_USER_CREATED = "user.created"
EVENT_BACKUP_COMPLETED = "backup.completed"


class WebhookStore:
    """SQLite-backed webhook registration store (data/webhooks.db)."""

    def __init__(self, db_path: str = "data/webhooks.db"):
        """Initialize webhook store.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self._lock = threading.Lock()

        # Create directory if needed
        db_dir = Path(db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        # Connect with WAL mode
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._init_schema()
        logger.info(f"WebhookStore initialized: {db_path}")

    def _init_schema(self):
        """Create webhooks and webhook_deliveries tables."""
        with self._lock:
            cursor = self._conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS webhooks (
                    id              TEXT PRIMARY KEY,
                    user_id         TEXT NOT NULL,
                    url             TEXT NOT NULL,
                    events          TEXT NOT NULL DEFAULT '[]',
                    secret          TEXT NOT NULL,
                    is_active       INTEGER DEFAULT 1,
                    failure_count   INTEGER DEFAULT 0,
                    max_retries     INTEGER DEFAULT 3,
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    webhook_id      TEXT NOT NULL,
                    event_type      TEXT NOT NULL,
                    payload_json    TEXT NOT NULL,
                    response_status INTEGER,
                    response_body   TEXT DEFAULT '',
                    attempt         INTEGER DEFAULT 1,
                    delivered_at    TEXT NOT NULL,
                    FOREIGN KEY (webhook_id) REFERENCES webhooks(id) ON DELETE CASCADE
                )
            """)

            # Indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_webhooks_user
                ON webhooks(user_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_webhooks_active
                ON webhooks(is_active)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_deliveries_webhook
                ON webhook_deliveries(webhook_id, delivered_at DESC)
            """)

            self._conn.commit()

    def create_webhook(
        self,
        user_id: str,
        url: str,
        events: list[str],
        secret: Optional[str] = None,
    ) -> dict:
        """Register a new webhook.

        Auto-generates a secret if not provided.

        Args:
            user_id: Owner user ID.
            url: Target URL for webhook delivery.
            events: List of event types to subscribe to.
            secret: HMAC signing secret (auto-generated if None).

        Returns:
            Webhook dict with id, url, events, secret, created_at.
        """
        webhook_id = str(uuid.uuid4())
        if not secret:
            secret = secrets.token_hex(32)
        now = datetime.utcnow().isoformat()
        events_json = json.dumps(events, ensure_ascii=False)

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO webhooks (id, user_id, url, events, secret,
                                      is_active, failure_count, max_retries,
                                      created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, 0, 3, ?, ?)
                """,
                (webhook_id, user_id, url, events_json, secret, now, now),
            )
            self._conn.commit()

        logger.info(f"Webhook created: id={webhook_id}, user={user_id}, url={url}")

        return {
            "id": webhook_id,
            "user_id": user_id,
            "url": url,
            "events": events,
            "secret": secret,
            "is_active": True,
            "failure_count": 0,
            "max_retries": 3,
            "created_at": now,
            "updated_at": now,
        }

    def list_webhooks(self, user_id: str) -> list[dict]:
        """List active webhooks for a user.

        Args:
            user_id: Owner user ID.

        Returns:
            List of webhook dicts.
        """
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT * FROM webhooks WHERE user_id = ? AND is_active = 1 ORDER BY created_at DESC",
                (user_id,),
            )
            rows = cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_webhook(self, webhook_id: str) -> Optional[dict]:
        """Get webhook by ID.

        Args:
            webhook_id: Webhook ID.

        Returns:
            Webhook dict or None if not found.
        """
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM webhooks WHERE id = ?", (webhook_id,))
            row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def delete_webhook(self, webhook_id: str, user_id: str) -> bool:
        """Delete webhook (soft delete: set is_active=0).

        User must own the webhook.

        Args:
            webhook_id: Webhook ID.
            user_id: Owner user ID (must match).

        Returns:
            True if deleted, False if not found or access denied.
        """
        now = datetime.utcnow().isoformat()
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "UPDATE webhooks SET is_active = 0, updated_at = ? WHERE id = ? AND user_id = ? AND is_active = 1",
                (now, webhook_id, user_id),
            )
            self._conn.commit()
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info(f"Webhook deleted: id={webhook_id}, user={user_id}")
        return deleted

    def get_active_webhooks(self, event_type: str) -> list[dict]:
        """Get all active webhooks subscribed to an event type.

        Args:
            event_type: The event type to match.

        Returns:
            List of matching webhook dicts.
        """
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM webhooks WHERE is_active = 1")
            rows = cursor.fetchall()

        matching = []
        for row in rows:
            events = json.loads(row["events"]) if row["events"] else []
            # Match if events list is empty (subscribe to all) or contains the event type
            if not events or event_type in events:
                matching.append(self._row_to_dict(row))

        return matching

    def record_delivery(
        self,
        webhook_id: str,
        event_type: str,
        payload_json: str,
        response_status: int,
        response_body: str,
        attempt: int,
    ) -> None:
        """Record a webhook delivery attempt.

        Args:
            webhook_id: Webhook ID.
            event_type: Event type delivered.
            payload_json: JSON payload sent.
            response_status: HTTP response status code.
            response_body: Response body (truncated).
            attempt: Attempt number (1-based).
        """
        now = datetime.utcnow().isoformat()
        # Truncate response body to prevent bloat
        truncated_body = (response_body or "")[:4096]

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO webhook_deliveries
                    (webhook_id, event_type, payload_json, response_status,
                     response_body, attempt, delivered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (webhook_id, event_type, payload_json, response_status,
                 truncated_body, attempt, now),
            )
            self._conn.commit()

    def increment_failure(self, webhook_id: str) -> None:
        """Increment failure count. Deactivate if max_retries exceeded.

        Args:
            webhook_id: Webhook ID.
        """
        now = datetime.utcnow().isoformat()
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "UPDATE webhooks SET failure_count = failure_count + 1, updated_at = ? WHERE id = ?",
                (now, webhook_id),
            )
            # Deactivate if failure_count > max_retries
            cursor.execute(
                "UPDATE webhooks SET is_active = 0, updated_at = ? WHERE id = ? AND failure_count > max_retries",
                (now, webhook_id),
            )
            self._conn.commit()

    def reset_failure(self, webhook_id: str) -> None:
        """Reset failure count on successful delivery.

        Args:
            webhook_id: Webhook ID.
        """
        now = datetime.utcnow().isoformat()
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "UPDATE webhooks SET failure_count = 0, updated_at = ? WHERE id = ?",
                (now, webhook_id),
            )
            self._conn.commit()

    def close(self):
        """Close database connection."""
        with self._lock:
            self._conn.close()
        logger.info("WebhookStore closed")

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """Convert a sqlite3.Row to a plain dict with parsed events."""
        d = dict(row)
        # Parse events JSON string to list
        if isinstance(d.get("events"), str):
            try:
                d["events"] = json.loads(d["events"])
            except (json.JSONDecodeError, TypeError):
                d["events"] = []
        # Convert is_active to boolean
        d["is_active"] = bool(d.get("is_active", 0))
        return d


class WebhookDispatcher:
    """Async webhook delivery using daemon threads.

    Each delivery runs in a separate daemon thread.
    Uses urllib.request for HTTP (no external deps).
    HMAC-SHA256 signature in X-Flux-Signature header.
    """

    DEFAULT_TIMEOUT = 10  # seconds
    BASE_BACKOFF = 1  # seconds

    def __init__(self, store: WebhookStore):
        """Initialize dispatcher.

        Args:
            store: WebhookStore instance for recording deliveries.
        """
        self._store = store
        self._lock = threading.Lock()

    def dispatch(self, event_type: str, payload: dict) -> None:
        """Fire event to all matching webhooks (non-blocking).

        Spawns daemon threads for each delivery.

        Args:
            event_type: Event type string.
            payload: Event payload dict.
        """
        webhooks = self._store.get_active_webhooks(event_type)
        for webhook in webhooks:
            thread = threading.Thread(
                target=self._deliver,
                args=(webhook, event_type, payload),
                daemon=True,
            )
            thread.start()

    def _deliver(self, webhook: dict, event_type: str, payload: dict) -> None:
        """Deliver to single webhook with retry.

        - urllib.request.Request with POST
        - Timeout: 10 seconds
        - Retries: max_retries times with exponential backoff (1s, 2s, 4s)
        - Sign payload with webhook['secret'] using HMAC-SHA256
        - X-Flux-Signature header: sha256=<hex_digest>
        - X-Flux-Event header: <event_type>
        - Content-Type: application/json
        - Record delivery to webhook_deliveries table

        Args:
            webhook: Webhook dict.
            event_type: Event type string.
            payload: Event payload dict.
        """
        max_retries = webhook.get("max_retries", 3)
        webhook_id = webhook["id"]
        url = webhook["url"]
        secret = webhook.get("secret", "")

        # Prepare payload bytes
        payload_bytes = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        signature = self._sign_payload(payload_bytes, secret)

        for attempt in range(1, max_retries + 1):
            response_status = 0
            response_body = ""

            try:
                req = urllib.request.Request(
                    url,
                    data=payload_bytes,
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "X-Flux-Signature": signature,
                        "X-Flux-Event": event_type,
                        "User-Agent": "flux-openclaw-webhook/1.0",
                    },
                )

                with urllib.request.urlopen(req, timeout=self.DEFAULT_TIMEOUT) as resp:
                    response_status = resp.status
                    response_body = resp.read(4096).decode("utf-8", errors="replace")

                # Record successful delivery
                self._store.record_delivery(
                    webhook_id=webhook_id,
                    event_type=event_type,
                    payload_json=payload_bytes.decode("utf-8"),
                    response_status=response_status,
                    response_body=response_body,
                    attempt=attempt,
                )

                # Success (2xx)
                if 200 <= response_status < 300:
                    self._store.reset_failure(webhook_id)
                    logger.info(
                        f"Webhook delivered: id={webhook_id}, event={event_type}, "
                        f"status={response_status}, attempt={attempt}"
                    )
                    return

            except urllib.error.HTTPError as e:
                response_status = e.code
                try:
                    response_body = e.read(4096).decode("utf-8", errors="replace")
                except Exception:
                    response_body = str(e)

                self._store.record_delivery(
                    webhook_id=webhook_id,
                    event_type=event_type,
                    payload_json=payload_bytes.decode("utf-8"),
                    response_status=response_status,
                    response_body=response_body,
                    attempt=attempt,
                )

            except Exception as e:
                response_body = str(e)
                self._store.record_delivery(
                    webhook_id=webhook_id,
                    event_type=event_type,
                    payload_json=payload_bytes.decode("utf-8"),
                    response_status=0,
                    response_body=response_body,
                    attempt=attempt,
                )

            # Exponential backoff before retry
            if attempt < max_retries:
                backoff = self.BASE_BACKOFF * (2 ** (attempt - 1))
                logger.warning(
                    f"Webhook delivery failed: id={webhook_id}, event={event_type}, "
                    f"status={response_status}, attempt={attempt}/{max_retries}, "
                    f"retrying in {backoff}s"
                )
                time.sleep(backoff)

        # All retries exhausted
        self._store.increment_failure(webhook_id)
        logger.error(
            f"Webhook delivery failed after {max_retries} attempts: "
            f"id={webhook_id}, event={event_type}, url={url}"
        )

    @staticmethod
    def _sign_payload(payload_bytes: bytes, secret: str) -> str:
        """HMAC-SHA256 signature.

        Args:
            payload_bytes: The raw payload bytes to sign.
            secret: The webhook secret key.

        Returns:
            Signature string in format 'sha256=<hex_digest>'.
        """
        mac = hmac.new(
            secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        )
        return f"sha256={mac.hexdigest()}"
