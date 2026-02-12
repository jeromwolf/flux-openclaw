"""audit 모듈 테스트"""
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openclaw.audit import AuditLogger, AuditEvent


class TestAuditLogger:
    @pytest.fixture
    def logger(self, tmp_path):
        db_path = str(tmp_path / "test_audit.db")
        al = AuditLogger(db_path=db_path)
        yield al
        al.close()

    def test_schema_creation(self, logger):
        """스키마 생성 확인"""
        tables = logger._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [t[0] for t in tables]
        assert "audit_events" in table_names

    def test_log_event(self, logger):
        """이벤트 기록"""
        event = logger.log("test.event", user_id="user1", details={"key": "value"})
        assert event.event_type == "test.event"
        assert event.user_id == "user1"
        assert event.details == {"key": "value"}

        events = logger.query(limit=1)
        assert len(events) == 1
        assert events[0].event_type == "test.event"
        assert events[0].user_id == "user1"

    def test_query_by_event_type(self, logger):
        """이벤트 타입 필터"""
        logger.log("auth_login")
        logger.log("auth_failure")
        logger.log("auth_login")
        events = logger.query(event_type="auth_login")
        assert len(events) == 2
        assert all(e.event_type == "auth_login" for e in events)

    def test_query_by_user(self, logger):
        """사용자 필터"""
        logger.log("test", user_id="user1")
        logger.log("test", user_id="user2")
        events = logger.query(user_id="user1")
        assert len(events) == 1
        assert events[0].user_id == "user1"

    def test_query_limit(self, logger):
        """쿼리 제한"""
        for i in range(10):
            logger.log(f"event_{i}")
        events = logger.query(limit=5)
        assert len(events) == 5

    def test_log_auth_success(self, logger):
        """인증 성공 기록"""
        event = logger.log_auth_success("user1", interface="web", source_ip="127.0.0.1")
        assert event.event_type == "auth_success"
        assert event.user_id == "user1"
        assert event.interface == "web"
        assert event.source_ip == "127.0.0.1"
        assert event.severity == "info"
        assert event.details["status"] == "success"

    def test_log_auth_failure(self, logger):
        """인증 실패 기록"""
        event = logger.log_auth_failure(source_ip="1.2.3.4", interface="api", reason="invalid_key")
        assert event.event_type == "auth_failure"
        assert event.source_ip == "1.2.3.4"
        assert event.interface == "api"
        assert event.severity == "warning"
        assert event.details["reason"] == "invalid_key"

    def test_log_tool_approval(self, logger):
        """도구 승인 기록"""
        event = logger.log_tool_approval("admin1", "web_fetch", True)
        assert event.event_type == "tool_approval"
        assert event.user_id == "admin1"
        assert event.details["tool_name"] == "web_fetch"
        assert event.details["approved"] is True
        assert event.details["status"] == "approved"

    def test_log_tool_denial(self, logger):
        """도구 거부 기록"""
        event = logger.log_tool_approval("admin1", "dangerous_tool", False)
        assert event.event_type == "tool_approval"
        assert event.details["approved"] is False
        assert event.details["status"] == "denied"

    def test_log_config_change(self, logger):
        """설정 변경 기록"""
        event = logger.log_config_change("admin1", "max_tokens", 4096, 8192)
        assert event.event_type == "config_change"
        assert event.user_id == "admin1"
        assert event.details["key"] == "max_tokens"
        assert event.details["old_value"] == "4096"
        assert event.details["new_value"] == "8192"

    def test_log_user_created(self, logger):
        """사용자 생성 기록"""
        event = logger.log_user_created("admin1", "user2", "newuser", "editor")
        assert event.event_type == "user_created"
        assert event.user_id == "admin1"
        assert event.details["new_user_id"] == "user2"
        assert event.details["username"] == "newuser"
        assert event.details["role"] == "editor"

    def test_log_backup(self, logger):
        """백업 기록"""
        event = logger.log_backup("admin1", "flux-backup-2026.tar.gz", 1048576)
        assert event.event_type == "backup"
        assert event.user_id == "admin1"
        assert event.details["backup_file"] == "flux-backup-2026.tar.gz"
        assert event.details["size_bytes"] == 1048576
        assert event.details["size_mb"] == 1.0

    def test_wal_mode(self, logger):
        """WAL 모드 확인"""
        result = logger._conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0].lower() == "wal"

    def test_severity_levels(self, logger):
        """심각도 레벨"""
        logger.log("critical_event", severity="critical")
        logger.log("info_event", severity="info")
        logger.log("warning_event", severity="warning")
        logger.log("error_event", severity="error")

        events = logger.query(limit=10)
        severities = {e.severity for e in events}
        assert "critical" in severities
        assert "info" in severities
        assert "warning" in severities
        assert "error" in severities

    def test_details_json_round_trip(self, logger):
        """세부사항 JSON 직렬화"""
        complex_details = {"nested": {"key": [1, 2, 3]}, "unicode": "한글"}
        logger.log("test", details=complex_details)
        events = logger.query(limit=1)
        assert events[0].details == complex_details

    def test_query_since_filter(self, logger):
        """시간 범위 필터"""
        from datetime import datetime
        logger.log("event1")
        timestamp_before = datetime.utcnow().isoformat()
        logger.log("event2")
        events = logger.query(since=timestamp_before, limit=10)
        assert len(events) == 1
        assert events[0].event_type == "event2"

    def test_audit_event_dataclass(self, logger):
        """AuditEvent 데이터클래스"""
        event = logger.log("test", user_id="user1", source_ip="1.2.3.4", interface="api")
        assert isinstance(event, AuditEvent)
        assert event.id > 0
        assert event.event_type == "test"
        assert event.user_id == "user1"
        assert event.source_ip == "1.2.3.4"
        assert event.interface == "api"
        assert event.timestamp  # ISO format
        assert event.severity == "info"
        assert event.details == {}
