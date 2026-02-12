"""flux-openclaw 감사 로깅 모듈

보안 민감 작업의 구조화된 감사 기록.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
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


@dataclass
class AuditEvent:
    """감사 이벤트."""
    id: int
    timestamp: str
    event_type: str
    user_id: str
    source_ip: str
    interface: str
    details: dict[str, Any]
    severity: str


class AuditLogger:
    """SQLite 기반 구조화된 감사 로거."""

    def __init__(self, db_path: str = "data/audit.db"):
        """초기화.

        Args:
            db_path: 데이터베이스 파일 경로 (기본값: data/audit.db)
        """
        self.db_path = db_path
        self._lock = threading.Lock()

        # 디렉토리 생성
        db_dir = Path(db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        # 커넥션 초기화
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        # SQLite 설정
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")

        # 스키마 초기화
        self._init_schema()

        logger.info(f"AuditLogger initialized: {db_path}")

    def _init_schema(self):
        """스키마 초기화."""
        with self._lock:
            cursor = self._conn.cursor()

            # audit_events 테이블
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_events (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp       TEXT NOT NULL,
                    event_type      TEXT NOT NULL,
                    user_id         TEXT DEFAULT '',
                    source_ip       TEXT DEFAULT '',
                    interface       TEXT DEFAULT '',
                    details_json    TEXT DEFAULT '{}',
                    severity        TEXT DEFAULT 'info'
                )
            """)

            # 인덱스
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_timestamp
                ON audit_events(timestamp DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_event_type
                ON audit_events(event_type, timestamp DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_user
                ON audit_events(user_id, timestamp DESC)
            """)

            self._conn.commit()

    def log(
        self,
        event_type: str,
        user_id: str = "",
        source_ip: str = "",
        interface: str = "",
        details: Optional[dict[str, Any]] = None,
        severity: str = "info"
    ) -> AuditEvent:
        """감사 이벤트 기록.

        Args:
            event_type: 이벤트 타입 (auth_success, auth_failure, tool_approval 등)
            user_id: 사용자 ID
            source_ip: 소스 IP 주소
            interface: 인터페이스 타입 (cli, web, api 등)
            details: 추가 세부 정보
            severity: 심각도 (info, warning, error, critical)

        Returns:
            생성된 AuditEvent
        """
        now = datetime.utcnow().isoformat()
        details = details or {}
        details_json = json.dumps(details, ensure_ascii=False)

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("""
                INSERT INTO audit_events (timestamp, event_type, user_id, source_ip, interface, details_json, severity)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (now, event_type, user_id, source_ip, interface, details_json, severity))
            self._conn.commit()
            event_id = cursor.lastrowid

        logger.info(f"Audit event: {event_type} (user={user_id}, severity={severity})")

        return AuditEvent(
            id=event_id,
            timestamp=now,
            event_type=event_type,
            user_id=user_id,
            source_ip=source_ip,
            interface=interface,
            details=details,
            severity=severity
        )

    def query(
        self,
        event_type: Optional[str] = None,
        user_id: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 50
    ) -> list[AuditEvent]:
        """감사 이벤트 조회.

        Args:
            event_type: 필터링할 이벤트 타입 (None이면 전체)
            user_id: 필터링할 사용자 ID (None이면 전체)
            since: 시작 타임스탬프 (ISO 형식, None이면 전체)
            limit: 최대 개수

        Returns:
            AuditEvent 리스트 (최신순)
        """
        cursor = self._conn.cursor()

        query = "SELECT * FROM audit_events WHERE 1=1"
        params = []

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        if since:
            query += " AND timestamp >= ?"
            params.append(since)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        events = []
        for row in rows:
            details = json.loads(row['details_json']) if row['details_json'] else {}
            events.append(AuditEvent(
                id=row['id'],
                timestamp=row['timestamp'],
                event_type=row['event_type'],
                user_id=row['user_id'] or "",
                source_ip=row['source_ip'] or "",
                interface=row['interface'] or "",
                details=details,
                severity=row['severity'] or "info"
            ))

        return events

    # Convenience methods

    def log_auth_success(
        self,
        user_id: str,
        interface: str = "",
        source_ip: str = ""
    ) -> AuditEvent:
        """인증 성공 기록.

        Args:
            user_id: 사용자 ID
            interface: 인터페이스 타입
            source_ip: 소스 IP 주소

        Returns:
            생성된 AuditEvent
        """
        return self.log(
            event_type="auth_success",
            user_id=user_id,
            source_ip=source_ip,
            interface=interface,
            details={"status": "success"},
            severity="info"
        )

    def log_auth_failure(
        self,
        source_ip: str = "",
        interface: str = "",
        reason: str = ""
    ) -> AuditEvent:
        """인증 실패 기록.

        Args:
            source_ip: 소스 IP 주소
            interface: 인터페이스 타입
            reason: 실패 사유

        Returns:
            생성된 AuditEvent
        """
        return self.log(
            event_type="auth_failure",
            source_ip=source_ip,
            interface=interface,
            details={"reason": reason},
            severity="warning"
        )

    def log_tool_approval(
        self,
        user_id: str,
        tool_name: str,
        approved: bool
    ) -> AuditEvent:
        """툴 승인/거부 기록.

        Args:
            user_id: 사용자 ID
            tool_name: 툴 이름
            approved: 승인 여부

        Returns:
            생성된 AuditEvent
        """
        return self.log(
            event_type="tool_approval",
            user_id=user_id,
            details={
                "tool_name": tool_name,
                "approved": approved,
                "status": "approved" if approved else "denied"
            },
            severity="info"
        )

    def log_config_change(
        self,
        user_id: str,
        key: str,
        old_value: Any,
        new_value: Any
    ) -> AuditEvent:
        """설정 변경 기록.

        Args:
            user_id: 사용자 ID
            key: 설정 키
            old_value: 이전 값
            new_value: 새 값

        Returns:
            생성된 AuditEvent
        """
        return self.log(
            event_type="config_change",
            user_id=user_id,
            details={
                "key": key,
                "old_value": str(old_value),
                "new_value": str(new_value)
            },
            severity="info"
        )

    def log_user_created(
        self,
        admin_id: str,
        new_user_id: str,
        username: str,
        role: str
    ) -> AuditEvent:
        """사용자 생성 기록.

        Args:
            admin_id: 관리자 ID
            new_user_id: 새 사용자 ID
            username: 사용자명
            role: 역할

        Returns:
            생성된 AuditEvent
        """
        return self.log(
            event_type="user_created",
            user_id=admin_id,
            details={
                "new_user_id": new_user_id,
                "username": username,
                "role": role
            },
            severity="info"
        )

    def log_backup(
        self,
        user_id: str,
        backup_file: str,
        size_bytes: int
    ) -> AuditEvent:
        """백업 실행 기록.

        Args:
            user_id: 사용자 ID
            backup_file: 백업 파일명
            size_bytes: 파일 크기 (바이트)

        Returns:
            생성된 AuditEvent
        """
        return self.log(
            event_type="backup",
            user_id=user_id,
            details={
                "backup_file": backup_file,
                "size_bytes": size_bytes,
                "size_mb": round(size_bytes / (1024 * 1024), 2)
            },
            severity="info"
        )

    def log_webhook_delivery(
        self,
        webhook_id: str,
        event_type: str,
        url: str,
        status_code: int,
        success: bool,
        **kwargs,
    ) -> AuditEvent:
        """Log a webhook delivery event.

        Args:
            webhook_id: Webhook ID.
            event_type: Event type delivered.
            url: Target URL.
            status_code: HTTP response status code.
            success: Whether the delivery succeeded.
            **kwargs: Additional details to include.

        Returns:
            Created AuditEvent.
        """
        return self.log(
            event_type="webhook_delivery",
            details={
                "webhook_id": webhook_id,
                "event": event_type,
                "url": url,
                "status_code": status_code,
                "success": success,
                **kwargs,
            },
            severity="info" if success else "warning",
        )

    def close(self):
        """커넥션 종료."""
        with self._lock:
            self._conn.close()
        logger.info("AuditLogger closed")
