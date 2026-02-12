"""Multi-user authentication module.

SQLite-backed user store with API key authentication,
role-based authorization, and rate limit integration.

stdlib only, thread-safe implementation.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UserContext:
    """Immutable user context passed through call chain."""
    user_id: str
    username: str
    role: str  # "admin" | "user" | "readonly"
    max_daily_calls: int = 100


# Default user for auth_enabled=False mode
DEFAULT_USER = UserContext(
    user_id="default",
    username="default",
    role="admin",
    max_daily_calls=100,
)

# Role hierarchy (higher value = more privilege)
_ROLE_RANK: dict[str, int] = {
    "readonly": 0,
    "user": 1,
    "admin": 2,
}

# Valid roles
_VALID_ROLES = frozenset(_ROLE_RANK.keys())

# API key constants
_API_KEY_PREFIX = "flux_"
_API_KEY_HEX_LENGTH = 64  # 32 bytes = 64 hex chars
_API_KEY_TOTAL_LENGTH = len(_API_KEY_PREFIX) + _API_KEY_HEX_LENGTH  # 69


@dataclass
class User:
    """Full user record from database."""
    id: str
    username: str
    display_name: str
    role: str
    api_key_prefix: str  # first 8 hex chars for display (e.g. "flux_a1b2c3d4")
    max_daily_calls: int
    is_active: bool
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_api_key(raw_key: str) -> str:
    """Return SHA-256 hex digest of an API key."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns:
        (raw_key, key_hash, key_prefix)
        - raw_key:    flux_ + 64 hex chars (69 chars total)
        - key_hash:   SHA-256 hex digest of raw_key
        - key_prefix: flux_ + first 8 hex chars (for display)
    """
    hex_token = secrets.token_hex(32)  # 64 hex chars
    raw_key = f"{_API_KEY_PREFIX}{hex_token}"
    key_hash = _hash_api_key(raw_key)
    key_prefix = f"{_API_KEY_PREFIX}{hex_token[:8]}"
    return raw_key, key_hash, key_prefix


def _row_to_user(row: sqlite3.Row) -> User:
    """Convert a sqlite3.Row to a User dataclass."""
    return User(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        role=row["role"],
        api_key_prefix=row["api_key_prefix"],
        max_daily_calls=row["max_daily_calls"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ---------------------------------------------------------------------------
# UserStore
# ---------------------------------------------------------------------------

class UserStore:
    """SQLite-backed user store (data/auth.db)."""

    def __init__(self, db_path: str = "data/auth.db"):
        """Initialize the user store.

        Args:
            db_path: Database file path (default: data/auth.db).
        """
        self.db_path = db_path
        self._lock = threading.Lock()

        # Ensure parent directory exists
        db_dir = Path(db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        # Open connection
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        # SQLite pragmas
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")

        # Schema
        self._init_schema()

        logger.info(f"UserStore initialized: {db_path}")

    # -----------------------------------------------------------------------
    # Schema
    # -----------------------------------------------------------------------

    def _init_schema(self) -> None:
        """Create tables and indexes if they do not exist."""
        with self._lock:
            cursor = self._conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id              TEXT PRIMARY KEY,
                    username        TEXT UNIQUE NOT NULL,
                    display_name    TEXT DEFAULT '',
                    role            TEXT NOT NULL DEFAULT 'user',
                    api_key_hash    TEXT NOT NULL,
                    api_key_prefix  TEXT NOT NULL,
                    max_daily_calls INTEGER DEFAULT 100,
                    is_active       INTEGER DEFAULT 1,
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_users_api_key_hash
                ON users(api_key_hash)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_users_username
                ON users(username)
            """)

            # Phase 9: Refresh tokens table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS refresh_tokens (
                    id              TEXT PRIMARY KEY,
                    user_id         TEXT NOT NULL,
                    token_hash      TEXT NOT NULL UNIQUE,
                    expires_at      TEXT NOT NULL,
                    revoked         INTEGER DEFAULT 0,
                    created_at      TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash
                ON refresh_tokens(token_hash)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user
                ON refresh_tokens(user_id)
            """)

            self._conn.commit()

    # -----------------------------------------------------------------------
    # CRUD operations
    # -----------------------------------------------------------------------

    def create_user(
        self,
        username: str,
        role: str = "user",
        display_name: str = "",
        max_daily_calls: int = 100,
    ) -> tuple[User, str]:
        """Create a new user with a generated API key.

        Args:
            username: Unique username.
            role: One of "admin", "user", "readonly".
            display_name: Optional display name.
            max_daily_calls: Daily API call limit.

        Returns:
            Tuple of (User, raw_api_key). The raw key is shown only once.

        Raises:
            ValueError: If role is invalid or username is empty.
            sqlite3.IntegrityError: If username already exists.
        """
        username = username.strip()
        if not username:
            raise ValueError("Username must not be empty")

        if role not in _VALID_ROLES:
            raise ValueError(f"Invalid role '{role}'. Must be one of: {', '.join(sorted(_VALID_ROLES))}")

        user_id = str(uuid.uuid4())
        raw_key, key_hash, key_prefix = _generate_api_key()
        now = datetime.utcnow().isoformat()

        with self._lock:
            try:
                cursor = self._conn.cursor()
                cursor.execute("""
                    INSERT INTO users
                        (id, username, display_name, role,
                         api_key_hash, api_key_prefix,
                         max_daily_calls, is_active,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """, (
                    user_id, username, display_name, role,
                    key_hash, key_prefix,
                    max_daily_calls,
                    now, now,
                ))
                self._conn.commit()
            except sqlite3.IntegrityError:
                logger.warning(f"Duplicate username: {username}")
                raise

        user = User(
            id=user_id,
            username=username,
            display_name=display_name,
            role=role,
            api_key_prefix=key_prefix,
            max_daily_calls=max_daily_calls,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

        logger.info(f"Created user: {username} (id={user_id}, role={role})")
        return user, raw_key

    def get_user(self, user_id: str) -> Optional[User]:
        """Look up a user by ID.

        Args:
            user_id: The user's UUID.

        Returns:
            User or None if not found.
        """
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_user(row)

    def get_user_by_username(self, username: str) -> Optional[User]:
        """Look up a user by username.

        Args:
            username: The unique username.

        Returns:
            User or None if not found.
        """
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_user(row)

    def authenticate_api_key(self, api_key: str) -> Optional[User]:
        """Authenticate a user via API key.

        Uses constant-time comparison (hmac.compare_digest) to prevent
        timing attacks.

        Args:
            api_key: The raw API key string.

        Returns:
            Authenticated User, or None if invalid/deactivated.
        """
        # Quick format validation
        if not api_key or not api_key.startswith(_API_KEY_PREFIX):
            return None
        if len(api_key) != _API_KEY_TOTAL_LENGTH:
            return None

        provided_hash = _hash_api_key(api_key)

        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE api_key_hash = ? AND is_active = 1",
            (provided_hash,),
        )
        row = cursor.fetchone()

        if row is not None:
            user = _row_to_user(row)
            logger.debug(f"Authenticated user: {user.username}")
            return user

        return None

    def list_users(self, limit: int = 50) -> list[User]:
        """List all active users.

        Args:
            limit: Maximum number of users to return.

        Returns:
            List of active User records ordered by creation time.
        """
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE is_active = 1 ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [_row_to_user(row) for row in cursor.fetchall()]

    def deactivate_user(self, user_id: str) -> bool:
        """Deactivate a user (soft delete).

        Args:
            user_id: The user's UUID.

        Returns:
            True if the user was deactivated, False if not found.
        """
        now = datetime.utcnow().isoformat()

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "UPDATE users SET is_active = 0, updated_at = ? WHERE id = ? AND is_active = 1",
                (now, user_id),
            )
            self._conn.commit()
            deactivated = cursor.rowcount > 0

        if deactivated:
            logger.info(f"Deactivated user: {user_id}")

        return deactivated

    def rotate_api_key(self, user_id: str) -> tuple[Optional[User], Optional[str]]:
        """Rotate a user's API key.

        Generates a new API key and invalidates the old one.

        Args:
            user_id: The user's UUID.

        Returns:
            Tuple of (updated User, new raw API key), or (None, None)
            if user not found or inactive.
        """
        raw_key, key_hash, key_prefix = _generate_api_key()
        now = datetime.utcnow().isoformat()

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """UPDATE users
                   SET api_key_hash = ?, api_key_prefix = ?, updated_at = ?
                   WHERE id = ? AND is_active = 1""",
                (key_hash, key_prefix, now, user_id),
            )
            self._conn.commit()

            if cursor.rowcount == 0:
                return None, None

        user = self.get_user(user_id)
        if user:
            logger.info(f"Rotated API key for user: {user.username} (id={user_id})")
        return user, raw_key

    def update_user(
        self,
        user_id: str,
        display_name: Optional[str] = None,
        role: Optional[str] = None,
        max_daily_calls: Optional[int] = None,
    ) -> Optional[User]:
        """Update user attributes.

        Args:
            user_id: The user's UUID.
            display_name: New display name (if provided).
            role: New role (if provided).
            max_daily_calls: New daily call limit (if provided).

        Returns:
            Updated User or None if not found.

        Raises:
            ValueError: If role is invalid.
        """
        if role is not None and role not in _VALID_ROLES:
            raise ValueError(f"Invalid role '{role}'. Must be one of: {', '.join(sorted(_VALID_ROLES))}")

        updates: list[str] = []
        params: list[Any] = []

        if display_name is not None:
            updates.append("display_name = ?")
            params.append(display_name)
        if role is not None:
            updates.append("role = ?")
            params.append(role)
        if max_daily_calls is not None:
            updates.append("max_daily_calls = ?")
            params.append(max_daily_calls)

        if not updates:
            return self.get_user(user_id)

        now = datetime.utcnow().isoformat()
        updates.append("updated_at = ?")
        params.append(now)
        params.append(user_id)

        set_clause = ", ".join(updates)

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                f"UPDATE users SET {set_clause} WHERE id = ? AND is_active = 1",
                params,
            )
            self._conn.commit()

            if cursor.rowcount == 0:
                return None

        user = self.get_user(user_id)
        if user:
            logger.info(f"Updated user: {user.username} (id={user_id})")
        return user

    # -----------------------------------------------------------------------
    # Refresh token operations (Phase 9)
    # -----------------------------------------------------------------------

    def store_refresh_token(self, user_id: str, token_hash: str, expires_at: str) -> str:
        """Store a refresh token (thread-safe).

        Args:
            user_id: The user's UUID.
            token_hash: SHA-256 hex digest of the raw refresh token.
            expires_at: ISO 8601 expiration timestamp.

        Returns:
            The generated token record ID.
        """
        token_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("""
                INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (token_id, user_id, token_hash, expires_at, now))
            self._conn.commit()
        logger.debug(f"Stored refresh token for user: {user_id}")
        return token_id

    def validate_refresh_token(self, token_hash: str) -> Optional[dict]:
        """Validate a refresh token (read-only, no lock needed).

        Args:
            token_hash: SHA-256 hex digest of the raw refresh token.

        Returns:
            Dict with token and user info if valid, None otherwise.
        """
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT rt.*, u.username, u.role
            FROM refresh_tokens rt
            JOIN users u ON rt.user_id = u.id
            WHERE rt.token_hash = ? AND rt.revoked = 0 AND u.is_active = 1
        """, (token_hash,))
        row = cursor.fetchone()
        if not row:
            return None
        # Check expiration
        if row["expires_at"] < datetime.utcnow().isoformat():
            return None
        return dict(row)

    def revoke_refresh_token(self, token_hash: str, user_id: str) -> bool:
        """Revoke a refresh token (thread-safe).

        Args:
            token_hash: SHA-256 hex digest of the raw refresh token.
            user_id: The user's UUID (for ownership verification).

        Returns:
            True if token was revoked, False if not found.
        """
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("""
                UPDATE refresh_tokens SET revoked = 1
                WHERE token_hash = ? AND user_id = ?
            """, (token_hash, user_id))
            self._conn.commit()
            revoked = cursor.rowcount > 0
        if revoked:
            logger.debug(f"Revoked refresh token for user: {user_id}")
        return revoked

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            self._conn.close()
        logger.info("UserStore closed")


# ---------------------------------------------------------------------------
# AuthMiddleware
# ---------------------------------------------------------------------------

class AuthMiddleware:
    """Stateless auth resolver.

    Validates API keys, resolves UserContext, and optionally
    logs authentication events to an audit logger.
    """

    def __init__(self, user_store: UserStore, audit_logger: Any = None):
        """Initialize the middleware.

        Args:
            user_store: UserStore instance for user lookups.
            audit_logger: Optional audit logger with .log(event, **kwargs) method.
        """
        self._store = user_store
        self._audit = audit_logger

    def authenticate(
        self,
        token_or_api_key: str,
        interface: str = "",
        source_ip: str = "",
    ) -> Optional[UserContext]:
        """Authenticate a token or API key and return a UserContext.

        Args:
            token_or_api_key: The raw API key string.
            interface: Source interface (e.g. "cli", "web", "api").
            source_ip: Source IP address for audit logging.

        Returns:
            UserContext on success, None on failure.
        """
        if not token_or_api_key:
            self._audit_log("auth_failure", reason="empty_token", interface=interface, source_ip=source_ip)
            return None

        user = self._store.authenticate_api_key(token_or_api_key)

        if user is None:
            self._audit_log(
                "auth_failure",
                reason="invalid_key",
                interface=interface,
                source_ip=source_ip,
            )
            return None

        if not user.is_active:
            self._audit_log(
                "auth_failure",
                reason="deactivated",
                user_id=user.id,
                username=user.username,
                interface=interface,
                source_ip=source_ip,
            )
            return None

        ctx = UserContext(
            user_id=user.id,
            username=user.username,
            role=user.role,
            max_daily_calls=user.max_daily_calls,
        )

        self._audit_log(
            "auth_success",
            user_id=user.id,
            username=user.username,
            role=user.role,
            interface=interface,
            source_ip=source_ip,
        )

        return ctx

    def require_role(self, ctx: UserContext, required_role: str) -> bool:
        """Check if a user has at least the required role.

        Role hierarchy: admin > user > readonly.

        Args:
            ctx: The authenticated UserContext.
            required_role: Minimum required role.

        Returns:
            True if user's role meets or exceeds the requirement.
        """
        user_rank = _ROLE_RANK.get(ctx.role, -1)
        required_rank = _ROLE_RANK.get(required_role, 999)
        return user_rank >= required_rank

    def check_user_rate_limit(self, ctx: UserContext) -> bool:
        """Check if the user is within their daily call limit.

        Delegates to core.check_daily_limit if available, passing the
        user's max_daily_calls. Falls back to True (allow) if the
        core module is not importable.

        Args:
            ctx: The authenticated UserContext.

        Returns:
            True if under the limit, False if limit exceeded.
        """
        try:
            from core import check_daily_limit
            return check_daily_limit(max_calls=ctx.max_daily_calls)
        except ImportError:
            logger.debug("core.check_daily_limit not available, allowing request")
            return True

    def _audit_log(self, event: str, **kwargs: Any) -> None:
        """Log an authentication event to the audit logger if available."""
        if self._audit is None:
            return
        try:
            if hasattr(self._audit, "log"):
                self._audit.log(event, **kwargs)
            elif callable(self._audit):
                self._audit(event, **kwargs)
        except Exception:
            logger.debug(f"Audit log failed for event: {event}")
