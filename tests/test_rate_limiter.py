"""rate_limiter module tests: HTTPRateLimiter."""
import os
import sys
import time
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rate_limiter import HTTPRateLimiter


# ---------------------------------------------------------------------------
# check - basic behaviour
# ---------------------------------------------------------------------------

class TestRateLimiterCheck:
    """HTTPRateLimiter.check basic tests."""

    def test_first_request_allowed(self):
        """First request for a key is always allowed."""
        rl = HTTPRateLimiter(max_requests=5, window_seconds=60)
        allowed, headers = rl.check("user1")
        assert allowed is True

    def test_headers_present(self):
        """Response includes X-RateLimit-Limit, Remaining, Reset."""
        rl = HTTPRateLimiter(max_requests=10, window_seconds=60)
        allowed, headers = rl.check("user1")
        assert "X-RateLimit-Limit" in headers
        assert "X-RateLimit-Remaining" in headers
        assert "X-RateLimit-Reset" in headers

    def test_limit_header_matches_config(self):
        """X-RateLimit-Limit reflects configured max_requests."""
        rl = HTTPRateLimiter(max_requests=42, window_seconds=60)
        _, headers = rl.check("user1")
        assert headers["X-RateLimit-Limit"] == "42"

    def test_remaining_decrements(self):
        """X-RateLimit-Remaining decreases with each request."""
        rl = HTTPRateLimiter(max_requests=5, window_seconds=60)
        _, h1 = rl.check("user1")
        _, h2 = rl.check("user1")
        r1 = int(h1["X-RateLimit-Remaining"])
        r2 = int(h2["X-RateLimit-Remaining"])
        assert r2 == r1 - 1

    def test_all_requests_within_limit_allowed(self):
        """All max_requests requests succeed."""
        rl = HTTPRateLimiter(max_requests=5, window_seconds=60)
        results = [rl.check("user1")[0] for _ in range(5)]
        assert all(results)

    def test_reset_header_is_future_timestamp(self):
        """X-RateLimit-Reset is a future UNIX timestamp."""
        rl = HTTPRateLimiter(max_requests=10, window_seconds=60)
        _, headers = rl.check("user1")
        reset = int(headers["X-RateLimit-Reset"])
        assert reset > int(time.time())

    def test_independent_keys(self):
        """Different keys have independent counters."""
        rl = HTTPRateLimiter(max_requests=2, window_seconds=60)
        rl.check("user_a")
        rl.check("user_a")
        # user_a is now at limit
        allowed_a, _ = rl.check("user_a")
        assert allowed_a is False
        # user_b should still be fine
        allowed_b, _ = rl.check("user_b")
        assert allowed_b is True


# ---------------------------------------------------------------------------
# check - rate limiting triggered
# ---------------------------------------------------------------------------

class TestRateLimiterExceeded:
    """HTTPRateLimiter.check when limit is exceeded."""

    def test_exceeding_limit_returns_false(self):
        """Request beyond max_requests returns (False, headers)."""
        rl = HTTPRateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            rl.check("user1")
        allowed, headers = rl.check("user1")
        assert allowed is False

    def test_retry_after_present_when_limited(self):
        """Retry-After header is present when rate limited."""
        rl = HTTPRateLimiter(max_requests=1, window_seconds=30)
        rl.check("user1")
        allowed, headers = rl.check("user1")
        assert allowed is False
        assert "Retry-After" in headers
        assert headers["Retry-After"] == "30"

    def test_remaining_zero_when_limited(self):
        """X-RateLimit-Remaining is 0 when rate limited."""
        rl = HTTPRateLimiter(max_requests=2, window_seconds=60)
        rl.check("user1")
        rl.check("user1")
        _, headers = rl.check("user1")
        assert headers["X-RateLimit-Remaining"] == "0"


# ---------------------------------------------------------------------------
# Sliding window behaviour
# ---------------------------------------------------------------------------

class TestRateLimiterSlidingWindow:
    """Sliding window expiry tests."""

    def test_window_expiry_allows_new_requests(self):
        """After the window elapses, requests are allowed again."""
        rl = HTTPRateLimiter(max_requests=2, window_seconds=10)
        rl.check("user1")
        rl.check("user1")

        # Exhaust the limit
        allowed, _ = rl.check("user1")
        assert allowed is False

        # Advance time beyond the window
        with patch("rate_limiter.time") as mock_time:
            mock_time.time.return_value = time.time() + 11
            allowed, headers = rl.check("user1")
            assert allowed is True
            # Remaining should reflect a fresh window
            assert int(headers["X-RateLimit-Remaining"]) >= 0


# ---------------------------------------------------------------------------
# cleanup_stale
# ---------------------------------------------------------------------------

class TestRateLimiterCleanup:
    """HTTPRateLimiter.cleanup_stale tests."""

    def test_removes_old_entries(self):
        """Entries with all timestamps older than max_age are removed."""
        rl = HTTPRateLimiter(max_requests=10, window_seconds=60)
        # Insert requests, then pretend they are old
        rl.check("old_user")
        # Manually age the timestamps
        rl._windows["old_user"] = [time.time() - 600]
        removed = rl.cleanup_stale(max_age_seconds=300)
        assert removed == 1
        assert "old_user" not in rl._windows

    def test_preserves_recent_entries(self):
        """Entries with recent timestamps are kept."""
        rl = HTTPRateLimiter(max_requests=10, window_seconds=60)
        rl.check("active_user")
        removed = rl.cleanup_stale(max_age_seconds=300)
        assert removed == 0
        assert "active_user" in rl._windows

    def test_returns_count_of_removed(self):
        """Return value matches number of removed keys."""
        rl = HTTPRateLimiter(max_requests=10, window_seconds=60)
        now = time.time()
        rl._windows["stale1"] = [now - 400]
        rl._windows["stale2"] = [now - 500]
        rl._windows["fresh"] = [now - 10]
        removed = rl.cleanup_stale(max_age_seconds=300)
        assert removed == 2
        assert "fresh" in rl._windows

    def test_cleanup_empty_entries(self):
        """Entries with empty timestamp lists are removed."""
        rl = HTTPRateLimiter(max_requests=10, window_seconds=60)
        rl._windows["empty_user"] = []
        removed = rl.cleanup_stale(max_age_seconds=300)
        assert removed == 1
        assert "empty_user" not in rl._windows
