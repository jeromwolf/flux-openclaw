"""HTTP rate limiter module.

Sliding window counter algorithm for per-user/IP rate limiting.
In-memory storage, thread-safe with own lock.

No external dependencies.
"""
from __future__ import annotations

import threading
import time

try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class HTTPRateLimiter:
    """HTTP request rate limiter using sliding window counter.

    In-memory dict storage (resets on process restart).
    Key: user_id (authenticated) or client_ip (unauthenticated).
    Value: list of request timestamps within the window.

    Thread-safe with its own threading.Lock.
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        """Initialize the rate limiter.

        Args:
            max_requests: Maximum requests allowed per window (default: 60).
            window_seconds: Window size in seconds (default: 60).
        """
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._windows: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        logger.debug(
            f"HTTPRateLimiter initialized: {max_requests} req/{window_seconds}s"
        )

    def check(self, key: str) -> tuple[bool, dict]:
        """Check whether a request is allowed.

        Args:
            key: User ID or IP address.

        Returns:
            (allowed, headers) tuple.
            headers dict contains:
                - X-RateLimit-Limit
                - X-RateLimit-Remaining
                - X-RateLimit-Reset
                - Retry-After (only when rate limited, i.e. allowed=False)
        """
        now = time.time()
        cutoff = now - self._window_seconds

        with self._lock:
            # Prune timestamps outside the window
            if key in self._windows:
                self._windows[key] = [t for t in self._windows[key] if t > cutoff]
            else:
                self._windows[key] = []

            current_count = len(self._windows[key])
            remaining = max(0, self._max_requests - current_count)
            reset_at = int(now + self._window_seconds)

            headers = {
                "X-RateLimit-Limit": str(self._max_requests),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(reset_at),
            }

            if current_count >= self._max_requests:
                headers["Retry-After"] = str(self._window_seconds)
                logger.debug(f"Rate limit exceeded for key: {key}")
                return False, headers

            # Record this request
            self._windows[key].append(now)
            headers["X-RateLimit-Remaining"] = str(remaining - 1)
            return True, headers

    def cleanup_stale(self, max_age_seconds: int = 300) -> int:
        """Remove stale entries older than max_age_seconds.

        Args:
            max_age_seconds: Maximum age for entries (default: 300s = 5 min).

        Returns:
            Number of keys cleaned up.
        """
        now = time.time()
        cutoff = now - max_age_seconds
        cleaned = 0

        with self._lock:
            stale_keys = [
                k for k, v in self._windows.items()
                if not v or v[-1] < cutoff
            ]
            for k in stale_keys:
                del self._windows[k]
                cleaned += 1

        if cleaned:
            logger.debug(f"Rate limiter cleanup: removed {cleaned} stale entries")
        return cleaned
