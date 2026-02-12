"""cors module tests: CORSConfig, is_allowed_origin, get_cors_headers, create_cors_config."""
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from cors import CORSConfig, is_allowed_origin, get_cors_headers, create_cors_config


# ---------------------------------------------------------------------------
# CORSConfig defaults
# ---------------------------------------------------------------------------

class TestCORSConfigDefaults:
    """CORSConfig dataclass default values."""

    def test_default_allowed_origins_wildcard(self):
        """Default allowed_origins is ['*']."""
        cfg = CORSConfig()
        assert cfg.allowed_origins == ["*"]

    def test_default_max_age(self):
        """Default max_age is 86400."""
        cfg = CORSConfig()
        assert cfg.max_age == 86400

    def test_default_allowed_methods(self):
        """Default allowed_methods contains GET, POST, DELETE, OPTIONS."""
        cfg = CORSConfig()
        assert "GET" in cfg.allowed_methods
        assert "POST" in cfg.allowed_methods
        assert "DELETE" in cfg.allowed_methods
        assert "OPTIONS" in cfg.allowed_methods

    def test_default_allowed_headers(self):
        """Default allowed_headers contains Authorization, Content-Type."""
        cfg = CORSConfig()
        assert "Authorization" in cfg.allowed_headers
        assert "Content-Type" in cfg.allowed_headers

    def test_frozen(self):
        """CORSConfig is immutable (frozen dataclass)."""
        cfg = CORSConfig()
        with pytest.raises(Exception):  # FrozenInstanceError
            cfg.max_age = 0


# ---------------------------------------------------------------------------
# is_allowed_origin
# ---------------------------------------------------------------------------

class TestIsAllowedOrigin:
    """is_allowed_origin function tests."""

    def test_wildcard_allows_any_origin(self):
        """Wildcard config allows any non-empty origin."""
        cfg = CORSConfig(allowed_origins=["*"])
        assert is_allowed_origin("https://example.com", cfg) is True
        assert is_allowed_origin("http://localhost:3000", cfg) is True

    def test_specific_origin_matches(self):
        """Exact origin match returns True."""
        cfg = CORSConfig(allowed_origins=["https://app.example.com"])
        assert is_allowed_origin("https://app.example.com", cfg) is True

    def test_non_matching_origin_rejected(self):
        """Non-matching origin returns False."""
        cfg = CORSConfig(allowed_origins=["https://allowed.com"])
        assert is_allowed_origin("https://evil.com", cfg) is False

    def test_empty_origin_rejected(self):
        """Empty origin string returns False."""
        cfg = CORSConfig(allowed_origins=["*"])
        assert is_allowed_origin("", cfg) is False

    def test_none_config_uses_defaults(self):
        """Passing config=None uses default CORSConfig (wildcard)."""
        assert is_allowed_origin("https://anything.com") is True

    def test_multiple_allowed_origins(self):
        """Origin matching one of several allowed origins returns True."""
        cfg = CORSConfig(allowed_origins=["https://a.com", "https://b.com"])
        assert is_allowed_origin("https://a.com", cfg) is True
        assert is_allowed_origin("https://b.com", cfg) is True
        assert is_allowed_origin("https://c.com", cfg) is False


# ---------------------------------------------------------------------------
# get_cors_headers
# ---------------------------------------------------------------------------

class TestGetCorsHeaders:
    """get_cors_headers function tests."""

    def test_wildcard_returns_star(self):
        """Wildcard config sets Access-Control-Allow-Origin to '*'."""
        cfg = CORSConfig(allowed_origins=["*"])
        headers = get_cors_headers("https://example.com", cfg)
        assert headers["Access-Control-Allow-Origin"] == "*"

    def test_specific_origin_returns_origin(self):
        """Specific origin config returns the origin itself."""
        cfg = CORSConfig(allowed_origins=["https://app.com"])
        headers = get_cors_headers("https://app.com", cfg)
        assert headers["Access-Control-Allow-Origin"] == "https://app.com"

    def test_specific_origin_includes_vary(self):
        """Specific origin config includes Vary: Origin."""
        cfg = CORSConfig(allowed_origins=["https://app.com"])
        headers = get_cors_headers("https://app.com", cfg)
        assert headers.get("Vary") == "Origin"

    def test_wildcard_no_vary(self):
        """Wildcard config does not set Vary header."""
        cfg = CORSConfig(allowed_origins=["*"])
        headers = get_cors_headers("https://example.com", cfg)
        assert "Vary" not in headers

    def test_includes_methods(self):
        """Headers include Access-Control-Allow-Methods."""
        headers = get_cors_headers("https://example.com")
        assert "Access-Control-Allow-Methods" in headers

    def test_includes_headers(self):
        """Headers include Access-Control-Allow-Headers."""
        headers = get_cors_headers("https://example.com")
        assert "Access-Control-Allow-Headers" in headers

    def test_includes_max_age(self):
        """Headers include Access-Control-Max-Age matching config."""
        cfg = CORSConfig(max_age=7200)
        headers = get_cors_headers("https://example.com", cfg)
        assert headers["Access-Control-Max-Age"] == "7200"

    def test_disallowed_origin_still_has_methods(self):
        """Disallowed origin still includes methods/headers/max-age but no Allow-Origin."""
        cfg = CORSConfig(allowed_origins=["https://allowed.com"])
        headers = get_cors_headers("https://evil.com", cfg)
        assert "Access-Control-Allow-Origin" not in headers
        assert "Access-Control-Allow-Methods" in headers


# ---------------------------------------------------------------------------
# create_cors_config
# ---------------------------------------------------------------------------

class TestCreateCorsConfig:
    """create_cors_config factory function tests."""

    def test_single_origin(self):
        """Single origin string creates single-element list."""
        cfg = create_cors_config("https://example.com")
        assert cfg.allowed_origins == ["https://example.com"]

    def test_comma_separated_origins(self):
        """Comma-separated string is split into list."""
        cfg = create_cors_config("https://a.com,https://b.com,https://c.com")
        assert cfg.allowed_origins == ["https://a.com", "https://b.com", "https://c.com"]

    def test_trims_whitespace(self):
        """Whitespace around origins is trimmed."""
        cfg = create_cors_config("  https://a.com , https://b.com  ")
        assert cfg.allowed_origins == ["https://a.com", "https://b.com"]

    def test_empty_string_defaults_to_wildcard(self):
        """Empty string defaults to ['*']."""
        cfg = create_cors_config("")
        assert cfg.allowed_origins == ["*"]

    def test_wildcard_string(self):
        """Wildcard '*' is preserved as-is."""
        cfg = create_cors_config("*")
        assert cfg.allowed_origins == ["*"]

    def test_custom_max_age(self):
        """max_age parameter is passed through."""
        cfg = create_cors_config("*", max_age=300)
        assert cfg.max_age == 300

    def test_whitespace_only_defaults_to_wildcard(self):
        """Whitespace-only string defaults to ['*']."""
        cfg = create_cors_config("   ,  , ")
        assert cfg.allowed_origins == ["*"]
