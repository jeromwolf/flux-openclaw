"""JWT token authentication module (stdlib only).

HS256 JWT implementation using hmac, hashlib, base64, json.
No external dependencies (no PyJWT).

Thread-safe: JWTManager is stateless after __init__.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Optional

try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base64url helpers (RFC 7515 - no padding)
# ---------------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """Base64url decode with padding restoration."""
    # Restore padding
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s.encode("ascii"))


# ---------------------------------------------------------------------------
# JWTManager
# ---------------------------------------------------------------------------

class JWTManager:
    """HS256 JWT token manager (stdlib only).

    Stateless after __init__ - no shared mutable state,
    so no threading.Lock is needed.

    jwt_secret must be at least MIN_SECRET_LENGTH characters.
    """

    MIN_SECRET_LENGTH = 32

    def __init__(self, secret: str):
        """Initialize with signing secret.

        Args:
            secret: HMAC signing key. Must be at least MIN_SECRET_LENGTH chars.

        Raises:
            ValueError: If secret is empty or too short.
        """
        if not secret:
            raise ValueError("JWT secret must not be empty")
        if len(secret) < self.MIN_SECRET_LENGTH:
            raise ValueError(
                f"JWT secret must be at least {self.MIN_SECRET_LENGTH} characters "
                f"(got {len(secret)}). "
                f'Use: python3 -c "import secrets; print(secrets.token_hex(32))"'
            )
        self._secret = secret.encode("utf-8")
        logger.debug("JWTManager initialized")

    # -------------------------------------------------------------------
    # Token creation
    # -------------------------------------------------------------------

    def create_access_token(
        self,
        user_id: str,
        username: str,
        role: str,
        ttl: int = 3600,
    ) -> str:
        """Create a signed JWT access token.

        Args:
            user_id: Subject claim (sub).
            username: Username claim.
            role: User role claim.
            ttl: Time-to-live in seconds (default: 3600 = 1 hour).

        Returns:
            Encoded JWT string (header.payload.signature).
        """
        now = int(time.time())

        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "sub": user_id,
            "username": username,
            "role": role,
            "iat": now,
            "exp": now + ttl,
        }

        header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

        signing_input = f"{header_b64}.{payload_b64}"
        signature = hmac.new(
            self._secret,
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        signature_b64 = _b64url_encode(signature)

        token = f"{header_b64}.{payload_b64}.{signature_b64}"
        logger.debug(f"Created access token for user: {username} (ttl={ttl}s)")
        return token

    def create_refresh_token(self) -> str:
        """Create a random refresh token.

        Returns:
            64-character hex string (32 bytes of randomness).
        """
        token = secrets.token_hex(32)
        logger.debug("Created refresh token")
        return token

    # -------------------------------------------------------------------
    # Token verification
    # -------------------------------------------------------------------

    def verify(self, token: str) -> Optional[dict]:
        """Verify a JWT token's signature and expiration.

        Args:
            token: The encoded JWT string.

        Returns:
            Decoded payload dict on success, None on failure
            (invalid format, bad signature, expired).
        """
        try:
            parts = token.split(".")
            if len(parts) != 3:
                logger.debug("JWT verification failed: invalid format (not 3 parts)")
                return None

            header_b64, payload_b64, signature_b64 = parts

            # Verify signature
            signing_input = f"{header_b64}.{payload_b64}"
            expected_sig = hmac.new(
                self._secret,
                signing_input.encode("ascii"),
                hashlib.sha256,
            ).digest()
            provided_sig = _b64url_decode(signature_b64)

            if not hmac.compare_digest(expected_sig, provided_sig):
                logger.debug("JWT verification failed: invalid signature")
                return None

            # Decode header and verify algorithm
            header = json.loads(_b64url_decode(header_b64))
            if header.get("alg") != "HS256":
                logger.debug(f"JWT verification failed: unsupported algorithm {header.get('alg')}")
                return None

            # Decode payload
            payload = json.loads(_b64url_decode(payload_b64))

            # Check expiration
            exp = payload.get("exp")
            if exp is not None and int(exp) < int(time.time()):
                logger.debug("JWT verification failed: token expired")
                return None

            logger.debug(f"JWT verified for user: {payload.get('username', 'unknown')}")
            return payload

        except (ValueError, KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.debug(f"JWT verification failed: {exc}")
            return None
        except Exception as exc:
            logger.debug(f"JWT verification failed (unexpected): {exc}")
            return None
