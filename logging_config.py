"""
flux-openclaw 구조화된 로깅 설정

모든 print() 호출을 Python logging으로 대체합니다.
text/JSON 포맷 지원, 로그 회전, 비밀 자동 마스킹.

사용법:
    from logging_config import setup_logging, get_logger
    setup_logging(level="INFO", log_format="text")
    logger = get_logger("my_module")
    logger.info("작업 완료")
"""

import os
import re
import json
import logging
import logging.handlers
from datetime import datetime
from typing import Optional


# 비밀 마스킹 패턴 (core.py _SECRET_RE와 동일)
_SECRET_RE = re.compile(
    r"(sk-ant-[a-zA-Z0-9_-]+|AIza[a-zA-Z0-9_-]+|sk-[a-zA-Z0-9_-]{20,}"
    r"|ghp_[a-zA-Z0-9]{36,}|glpat-[a-zA-Z0-9_-]{20,}"
    r"|xox[bpsa]-[a-zA-Z0-9-]{10,})"
)


def _mask_secrets(text: str) -> str:
    """API 키 등 비밀값 마스킹"""
    return _SECRET_RE.sub("[REDACTED]", str(text))


class SecretMaskingFilter(logging.Filter):
    """로그 레코드에서 비밀값 자동 마스킹"""
    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = _mask_secrets(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: _mask_secrets(str(v)) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(_mask_secrets(str(a)) for a in record.args)
        return True


class JSONFormatter(logging.Formatter):
    """JSON 구조화 로그 포매터"""

    def format(self, record):
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": _mask_secrets(record.getMessage()),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        # 개행/제어문자 이스케이프 (로그 인젝션 방지)
        return json.dumps(log_entry, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """텍스트 로그 포매터"""

    def __init__(self):
        super().__init__(
            fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


_initialized = False


def setup_logging(
    level: str = "INFO",
    log_format: str = "text",
    log_file: Optional[str] = None,
    max_bytes: int = 10_485_760,
    backup_count: int = 5,
) -> None:
    """전역 로깅 설정

    Args:
        level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR)
        log_format: 포맷 ("text" 또는 "json")
        log_file: 로그 파일 경로 (None이면 stdout만)
        max_bytes: 로그 파일 최대 크기 (기본 10MB)
        backup_count: 보관할 백업 파일 수
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    # 루트 로거 설정
    root_logger = logging.getLogger("flux-openclaw")
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 포매터 선택
    if log_format == "json":
        formatter = JSONFormatter()
    else:
        formatter = TextFormatter()

    # 비밀 마스킹 필터
    secret_filter = SecretMaskingFilter()

    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(secret_filter)
    root_logger.addHandler(console_handler)

    # 파일 핸들러 (선택적)
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(secret_filter)
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """모듈별 로거 반환

    Args:
        name: 모듈 이름 (예: "core", "main", "ws_server")

    Returns:
        flux-openclaw.{name} 로거
    """
    return logging.getLogger(f"flux-openclaw.{name}")


def reset_logging() -> None:
    """로깅 설정 초기화 (테스트용)"""
    global _initialized
    _initialized = False
    logger = logging.getLogger("flux-openclaw")
    logger.handlers.clear()
    logger.setLevel(logging.WARNING)
