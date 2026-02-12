"""
flux-openclaw 중앙 집중식 설정 모듈

모든 설정값을 단일 모듈로 통합합니다.
우선순위: 환경변수 > config.json > 기본값

사용법:
    from config import get_config
    cfg = get_config()
    print(cfg.max_tool_rounds)  # 10
"""

import os
import json
import dataclasses
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Config:
    """중앙 집중식 설정 (불변 객체)"""

    # LLM 설정
    default_model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096
    max_tool_rounds: int = 10
    max_daily_calls: int = 100
    max_history: int = 50

    # 복원력 설정
    llm_retry_count: int = 3
    llm_retry_base_delay: float = 1.0
    llm_retry_max_delay: float = 16.0
    tool_timeout_seconds: float = 30.0

    # Rate limiting
    ws_rate_limit: int = 30          # WebSocket: msg/min
    bot_rate_limit: int = 10          # Telegram/Discord/Slack: msg/min
    ws_max_connections: int = 10

    # 메시지 제한
    max_message_length: int = 10000
    discord_msg_limit: int = 2000
    slack_msg_limit: int = 4000
    telegram_msg_limit: int = 4000

    # 대시보드
    dashboard_port: int = 8080
    health_port: int = 8766

    # 데몬 설정
    daemon_max_restarts: int = 5
    daemon_restart_delay: int = 5

    # 로깅
    log_level: str = "INFO"
    log_format: str = "text"           # "text" | "json"
    log_file: str = "logs/flux-openclaw.log"
    log_max_bytes: int = 10_485_760    # 10MB
    log_backup_count: int = 5

    # 스트리밍
    streaming_enabled: bool = True

    # 대화 영속성
    conversation_db_path: str = "data/conversations.db"

    # Phase 8: Multi-User + Deployment
    auth_enabled: bool = False
    auth_db_path: str = "data/auth.db"
    audit_db_path: str = "data/audit.db"
    default_user_id: str = "default"
    per_user_daily_calls: int = 100
    backup_dir: str = "backups"
    api_version: str = "v1"

    # Phase 9: JWT + API Gateway
    jwt_secret: str = ""
    jwt_access_ttl: int = 3600          # 1 hour
    jwt_refresh_ttl: int = 604800       # 7 days
    api_rate_limit: int = 60            # HTTP requests/min
    api_rate_window: int = 60           # Rate limit window (seconds)
    cors_allowed_origins: str = "*"     # Comma-separated origins
    cors_max_age: int = 86400           # CORS max age (seconds)


def _str_to_bool(s: str) -> bool:
    """문자열을 bool로 변환"""
    return s.lower() in ("true", "1", "yes")


# 환경변수 매핑 (ENV_NAME -> (field_name, type_converter))
_ENV_MAP = {
    "LLM_MODEL": ("default_model", str),
    "MAX_TOKENS": ("max_tokens", int),
    "MAX_TOOL_ROUNDS": ("max_tool_rounds", int),
    "MAX_DAILY_CALLS": ("max_daily_calls", int),
    "MAX_HISTORY": ("max_history", int),
    "LLM_RETRY_COUNT": ("llm_retry_count", int),
    "LLM_RETRY_BASE_DELAY": ("llm_retry_base_delay", float),
    "TOOL_TIMEOUT": ("tool_timeout_seconds", float),
    "WS_RATE_LIMIT": ("ws_rate_limit", int),
    "BOT_RATE_LIMIT": ("bot_rate_limit", int),
    "WS_MAX_CONNECTIONS": ("ws_max_connections", int),
    "DASHBOARD_PORT": ("dashboard_port", int),
    "HEALTH_PORT": ("health_port", int),
    "DAEMON_MAX_RESTARTS": ("daemon_max_restarts", int),
    "DAEMON_RESTART_DELAY": ("daemon_restart_delay", int),
    "LOG_LEVEL": ("log_level", str),
    "LOG_FORMAT": ("log_format", str),
    "LOG_FILE": ("log_file", str),
    "LOG_MAX_BYTES": ("log_max_bytes", int),
    "LOG_BACKUP_COUNT": ("log_backup_count", int),
    "STREAMING_ENABLED": ("streaming_enabled", _str_to_bool),
    "CONVERSATION_DB_PATH": ("conversation_db_path", str),
    "AUTH_ENABLED": ("auth_enabled", _str_to_bool),
    "AUTH_DB_PATH": ("auth_db_path", str),
    "AUDIT_DB_PATH": ("audit_db_path", str),
    "DEFAULT_USER_ID": ("default_user_id", str),
    "PER_USER_DAILY_CALLS": ("per_user_daily_calls", int),
    "BACKUP_DIR": ("backup_dir", str),
    "JWT_SECRET": ("jwt_secret", str),
    "JWT_ACCESS_TTL": ("jwt_access_ttl", int),
    "JWT_REFRESH_TTL": ("jwt_refresh_ttl", int),
    "API_RATE_LIMIT": ("api_rate_limit", int),
    "API_RATE_WINDOW": ("api_rate_window", int),
    "CORS_ALLOWED_ORIGINS": ("cors_allowed_origins", str),
    "CORS_MAX_AGE": ("cors_max_age", int),
}


# 설정 필드 범위 제한
_FIELD_BOUNDS = {
    "max_tool_rounds": (1, 50),
    "llm_retry_count": (0, 10),
    "llm_retry_base_delay": (0.1, 60.0),
    "llm_retry_max_delay": (1.0, 300.0),
    "tool_timeout_seconds": (1.0, 300.0),
    "max_history": (2, 500),
    "ws_rate_limit": (1, 1000),
    "bot_rate_limit": (1, 100),
    "max_daily_calls": (1, 100000),
    "max_tokens": (100, 32000),
    "max_message_length": (100, 100000),
    "per_user_daily_calls": (1, 100000),
    "jwt_access_ttl": (60, 86400),       # 1 min ~ 24 hours
    "jwt_refresh_ttl": (3600, 2592000),  # 1 hour ~ 30 days
    "api_rate_limit": (1, 10000),
    "api_rate_window": (1, 3600),
    "cors_max_age": (0, 86400),
}


def _clamp(field_name, value):
    """설정값의 범위를 제한"""
    if field_name in _FIELD_BOUNDS:
        lo, hi = _FIELD_BOUNDS[field_name]
        return type(value)(max(lo, min(hi, value)))
    return value


def _load_config_file(path: str = "config.json") -> dict:
    """config.json 로드 (없으면 빈 dict 반환)"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def load_config(config_path: str = "config.json") -> Config:
    """설정 로드 (환경변수 > config.json > 기본값)"""
    file_config = _load_config_file(config_path)
    overrides = {}

    for env_name, (field_name, converter) in _ENV_MAP.items():
        # 1. 환경변수 확인
        env_val = os.environ.get(env_name)
        if env_val is not None:
            try:
                overrides[field_name] = _clamp(field_name, converter(env_val))
            except (ValueError, TypeError):
                pass  # 변환 실패 시 무시
            continue

        # 2. config.json 확인
        if field_name in file_config:
            try:
                overrides[field_name] = _clamp(field_name, converter(file_config[field_name]))
            except (ValueError, TypeError):
                pass

    return Config(**overrides)


# 싱글턴 캐시
_cached_config: Optional[Config] = None


def get_config(config_path: str = "config.json") -> Config:
    """설정 싱글턴 반환 (최초 호출 시 로드)"""
    global _cached_config
    if _cached_config is None:
        _cached_config = load_config(config_path)
    return _cached_config


def reset_config() -> None:
    """설정 캐시 초기화 (테스트용)"""
    global _cached_config
    _cached_config = None
