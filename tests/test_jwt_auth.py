"""jwt_auth module tests: JWTManager, _b64url_encode, _b64url_decode."""
import os
import sys
import json
import time
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from jwt_auth import JWTManager, _b64url_encode, _b64url_decode


# ---------------------------------------------------------------------------
# Base64url helpers
# ---------------------------------------------------------------------------

class TestB64urlRoundTrip:
    """Base64url encode/decode round-trip tests."""

    def test_round_trip_ascii(self):
        """Encode then decode returns original ASCII bytes."""
        data = b"hello world"
        assert _b64url_decode(_b64url_encode(data)) == data

    def test_round_trip_binary(self):
        """Encode then decode returns original binary data."""
        data = bytes(range(256))
        assert _b64url_decode(_b64url_encode(data)) == data

    def test_round_trip_empty(self):
        """Encode then decode returns empty bytes."""
        assert _b64url_decode(_b64url_encode(b"")) == b""

    def test_encode_no_padding(self):
        """Encoded output contains no '=' padding characters."""
        # 1, 2, 3 byte inputs produce different padding in standard base64
        for length in (1, 2, 3, 4, 5):
            encoded = _b64url_encode(b"x" * length)
            assert "=" not in encoded

    def test_encode_url_safe_chars(self):
        """Encoded output uses URL-safe alphabet (no + or /)."""
        # Binary data likely to produce + and / in standard base64
        data = bytes(range(256))
        encoded = _b64url_encode(data)
        assert "+" not in encoded
        assert "/" not in encoded


# ---------------------------------------------------------------------------
# JWTManager.__init__
# ---------------------------------------------------------------------------

class TestJWTManagerInit:
    """JWTManager initialization validation."""

    def test_empty_secret_raises(self):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            JWTManager("")

    def test_short_secret_raises(self):
        """Secret shorter than 32 chars raises ValueError."""
        with pytest.raises(ValueError, match="at least 32 characters"):
            JWTManager("tooshort")

    def test_secret_31_chars_raises(self):
        """Secret of exactly 31 chars raises ValueError."""
        with pytest.raises(ValueError, match="at least 32 characters"):
            JWTManager("a" * 31)

    def test_secret_32_chars_ok(self):
        """Secret of exactly 32 chars succeeds."""
        mgr = JWTManager("a" * 32)
        assert mgr is not None

    def test_long_secret_ok(self):
        """Secret longer than 32 chars succeeds."""
        mgr = JWTManager("s" * 128)
        assert mgr is not None


# ---------------------------------------------------------------------------
# create_access_token
# ---------------------------------------------------------------------------

class TestCreateAccessToken:
    """JWTManager.create_access_token tests."""

    @pytest.fixture
    def mgr(self):
        return JWTManager("a" * 64)

    def test_returns_string(self, mgr):
        """Token is a string."""
        token = mgr.create_access_token("uid1", "alice", "admin")
        assert isinstance(token, str)

    def test_three_dot_separated_parts(self, mgr):
        """Token has exactly three dot-separated parts (header.payload.sig)."""
        token = mgr.create_access_token("uid1", "alice", "admin")
        parts = token.split(".")
        assert len(parts) == 3
        assert all(len(p) > 0 for p in parts)

    def test_payload_claims(self, mgr):
        """Decoded payload contains sub, username, role, iat, exp."""
        token = mgr.create_access_token("uid1", "alice", "admin")
        payload_b64 = token.split(".")[1]
        payload = json.loads(_b64url_decode(payload_b64))

        assert payload["sub"] == "uid1"
        assert payload["username"] == "alice"
        assert payload["role"] == "admin"
        assert "iat" in payload
        assert "exp" in payload

    def test_default_ttl_one_hour(self, mgr):
        """Default TTL is 3600 seconds."""
        token = mgr.create_access_token("uid1", "alice", "admin")
        payload_b64 = token.split(".")[1]
        payload = json.loads(_b64url_decode(payload_b64))
        assert payload["exp"] - payload["iat"] == 3600

    def test_custom_ttl(self, mgr):
        """Custom TTL is reflected in exp - iat."""
        token = mgr.create_access_token("uid1", "alice", "admin", ttl=120)
        payload_b64 = token.split(".")[1]
        payload = json.loads(_b64url_decode(payload_b64))
        assert payload["exp"] - payload["iat"] == 120

    def test_header_alg_hs256(self, mgr):
        """Header specifies HS256 algorithm and JWT type."""
        token = mgr.create_access_token("uid1", "alice", "admin")
        header_b64 = token.split(".")[0]
        header = json.loads(_b64url_decode(header_b64))
        assert header["alg"] == "HS256"
        assert header["typ"] == "JWT"


# ---------------------------------------------------------------------------
# create_refresh_token
# ---------------------------------------------------------------------------

class TestCreateRefreshToken:
    """JWTManager.create_refresh_token tests."""

    @pytest.fixture
    def mgr(self):
        return JWTManager("x" * 64)

    def test_returns_64_hex_chars(self, mgr):
        """Refresh token is 64 hex characters."""
        token = mgr.create_refresh_token()
        assert len(token) == 64
        # Verify it is valid hex
        int(token, 16)

    def test_unique_each_call(self, mgr):
        """Each call produces a different token."""
        tokens = {mgr.create_refresh_token() for _ in range(50)}
        assert len(tokens) == 50


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

class TestVerify:
    """JWTManager.verify tests."""

    @pytest.fixture
    def mgr(self):
        return JWTManager("secret-key-must-be-at-least-32-characters-long!")

    def test_valid_token(self, mgr):
        """Valid token returns payload dict."""
        token = mgr.create_access_token("u1", "bob", "user")
        payload = mgr.verify(token)
        assert isinstance(payload, dict)
        assert payload["sub"] == "u1"
        assert payload["username"] == "bob"
        assert payload["role"] == "user"

    def test_tampered_signature(self, mgr):
        """Token with altered signature returns None."""
        token = mgr.create_access_token("u1", "bob", "user")
        parts = token.split(".")
        # Flip a character in the signature
        bad_sig = parts[2][:-1] + ("A" if parts[2][-1] != "A" else "B")
        tampered = f"{parts[0]}.{parts[1]}.{bad_sig}"
        assert mgr.verify(tampered) is None

    def test_tampered_payload(self, mgr):
        """Token with altered payload returns None (signature mismatch)."""
        token = mgr.create_access_token("u1", "bob", "user")
        parts = token.split(".")
        # Replace payload with different data
        fake_payload = _b64url_encode(json.dumps({"sub": "hacker"}).encode())
        tampered = f"{parts[0]}.{fake_payload}.{parts[2]}"
        assert mgr.verify(tampered) is None

    def test_expired_token(self, mgr):
        """Expired token returns None."""
        # Create token with TTL=1 second, then advance time
        token = mgr.create_access_token("u1", "bob", "user", ttl=1)
        with patch("jwt_auth.time") as mock_time:
            # Verify reads time.time() for expiration check
            mock_time.time.return_value = time.time() + 10
            assert mgr.verify(token) is None

    def test_malformed_one_part(self, mgr):
        """Token with only one part returns None."""
        assert mgr.verify("onlyonepart") is None

    def test_malformed_two_parts(self, mgr):
        """Token with two parts returns None."""
        assert mgr.verify("part1.part2") is None

    def test_completely_garbage(self, mgr):
        """Completely invalid token string returns None."""
        assert mgr.verify("!!!not.a.token!!!") is None

    def test_wrong_algorithm_in_header(self, mgr):
        """Token with algorithm != HS256 returns None."""
        # Build a token manually with RS256 in header but signed with HS256
        import hashlib
        import hmac as hmac_mod

        header = {"alg": "RS256", "typ": "JWT"}
        payload = {"sub": "u1", "username": "bob", "role": "user",
                   "iat": int(time.time()), "exp": int(time.time()) + 3600}

        header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
        payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
        signing_input = f"{header_b64}.{payload_b64}"
        sig = hmac_mod.new(
            mgr._secret, signing_input.encode("ascii"), hashlib.sha256
        ).digest()
        sig_b64 = _b64url_encode(sig)
        token = f"{header_b64}.{payload_b64}.{sig_b64}"
        assert mgr.verify(token) is None

    def test_wrong_secret_rejects(self):
        """Token created with one secret is rejected by another."""
        mgr1 = JWTManager("first-secret-must-be-32-chars-long!")
        mgr2 = JWTManager("other-secret-must-be-32-chars-long!")
        token = mgr1.create_access_token("u1", "bob", "user")
        assert mgr2.verify(token) is None

    def test_empty_string_token(self, mgr):
        """Empty string returns None."""
        assert mgr.verify("") is None
