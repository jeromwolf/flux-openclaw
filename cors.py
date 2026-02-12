"""
CORS (Cross-Origin Resource Sharing) support module.

Provides configurable CORS headers and preflight handling
for the dashboard HTTP server.

Thread-safe: stateless after initialization.
No external dependencies (stdlib only).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class CORSConfig:
    """Immutable CORS configuration.

    Attributes:
        allowed_origins: List of allowed origins. ["*"] allows all origins.
        max_age: Preflight cache duration in seconds.
        allowed_methods: Comma-separated HTTP methods.
        allowed_headers: Comma-separated allowed request headers.
    """
    allowed_origins: list[str] = field(default_factory=lambda: ["*"])
    max_age: int = 86400
    allowed_methods: str = "GET, POST, DELETE, OPTIONS"
    allowed_headers: str = "Authorization, Content-Type"


def is_allowed_origin(origin: str, config: Optional[CORSConfig] = None) -> bool:
    """Check if the given origin is allowed by the CORS configuration.

    Args:
        origin: The Origin header value from the request.
        config: CORSConfig instance. Uses default if None.

    Returns:
        True if the origin is allowed, False otherwise.
    """
    if config is None:
        config = CORSConfig()
    if not origin:
        return False
    if "*" in config.allowed_origins:
        return True
    return origin in config.allowed_origins


def get_cors_headers(origin: str, config: Optional[CORSConfig] = None) -> dict[str, str]:
    """Build CORS response headers for the given origin.

    Args:
        origin: The Origin header value from the request.
        config: CORSConfig instance. Uses default if None.

    Returns:
        Dictionary of CORS headers to include in the response.
        Empty dict if the origin is not allowed and no wildcard is set.
    """
    if config is None:
        config = CORSConfig()

    headers: dict[str, str] = {}

    if is_allowed_origin(origin, config):
        # Use the specific origin rather than "*" when credentials may be involved
        if "*" in config.allowed_origins:
            headers["Access-Control-Allow-Origin"] = "*"
        else:
            headers["Access-Control-Allow-Origin"] = origin
            headers["Vary"] = "Origin"

    headers["Access-Control-Allow-Methods"] = config.allowed_methods
    headers["Access-Control-Allow-Headers"] = config.allowed_headers
    headers["Access-Control-Max-Age"] = str(config.max_age)

    return headers


def create_cors_config(
    allowed_origins_str: str = "*",
    max_age: int = 86400,
) -> CORSConfig:
    """Create a CORSConfig from a comma-separated origins string.

    Args:
        allowed_origins_str: Comma-separated list of allowed origins.
            Use "*" to allow all origins.
        max_age: Preflight cache duration in seconds.

    Returns:
        CORSConfig instance.
    """
    origins = [o.strip() for o in allowed_origins_str.split(",") if o.strip()]
    if not origins:
        origins = ["*"]
    return CORSConfig(allowed_origins=origins, max_age=max_age)
