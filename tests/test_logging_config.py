"""logging_config 모듈 테스트"""
import logging
import json
from logging_config import (
    _mask_secrets,
    SecretMaskingFilter,
    JSONFormatter,
    TextFormatter,
    setup_logging,
    get_logger,
    reset_logging,
)


class TestLoggingConfig:
    """로깅 설정 테스트"""

    def teardown_method(self):
        """각 테스트 후 로깅 초기화"""
        reset_logging()

    def test_mask_secrets_anthropic_key(self):
        """Anthropic API 키 마스킹"""
        text = "Using key sk-ant-api03-abcdef123456"
        masked = _mask_secrets(text)
        assert "sk-ant-api03-abcdef123456" not in masked
        assert "[REDACTED]" in masked

    def test_mask_secrets_google_key(self):
        """Google API 키 마스킹"""
        text = "Google API: AIzaSyB1234567890abcdefgh"
        masked = _mask_secrets(text)
        assert "AIzaSyB1234567890abcdefgh" not in masked
        assert "[REDACTED]" in masked

    def test_mask_secrets_openai_key(self):
        """OpenAI API 키 마스킹"""
        text = "OpenAI key: sk-1234567890abcdefghijklmnopqrst"
        masked = _mask_secrets(text)
        assert "sk-1234567890abcdefghijklmnopqrst" not in masked
        assert "[REDACTED]" in masked

    def test_mask_secrets_github_token(self):
        """GitHub 토큰 마스킹"""
        text = "GitHub token: ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        masked = _mask_secrets(text)
        assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz" not in masked
        assert "[REDACTED]" in masked

    def test_mask_secrets_gitlab_token(self):
        """GitLab 토큰 마스킹"""
        text = "GitLab: glpat-abcdefghijklmnopqrst"
        masked = _mask_secrets(text)
        assert "glpat-abcdefghijklmnopqrst" not in masked
        assert "[REDACTED]" in masked

    def test_mask_secrets_slack_token(self):
        """Slack 토큰 마스킹"""
        text = "Slack: xoxb-1234567890-abcdefghijk"
        masked = _mask_secrets(text)
        assert "xoxb-1234567890-abcdefghijk" not in masked
        assert "[REDACTED]" in masked

    def test_mask_secrets_no_secrets(self):
        """비밀 없는 일반 텍스트는 변경되지 않음"""
        text = "This is normal text without secrets"
        masked = _mask_secrets(text)
        assert masked == text

    def test_mask_secrets_multiple(self):
        """여러 비밀 동시 마스킹"""
        text = "API keys: sk-ant-api03-abc and AIzaSyB123"
        masked = _mask_secrets(text)
        assert "sk-ant-api03-abc" not in masked
        assert "AIzaSyB123" not in masked
        assert masked.count("[REDACTED]") == 2

    def test_secret_masking_filter_string_msg(self):
        """SecretMaskingFilter: 문자열 메시지 마스킹"""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="API key: sk-ant-api03-secret",
            args=(),
            exc_info=None,
        )
        filter_obj = SecretMaskingFilter()
        filter_obj.filter(record)
        assert "sk-ant-api03-secret" not in record.msg
        assert "[REDACTED]" in record.msg

    def test_secret_masking_filter_dict_args(self):
        """SecretMaskingFilter: dict args 마스킹"""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Config: %(api_key)s",
            args=(),
            exc_info=None,
        )
        # dict args를 수동으로 설정 (로거가 내부적으로 처리하는 방식)
        record.args = {"api_key": "sk-ant-api03-secret"}
        filter_obj = SecretMaskingFilter()
        filter_obj.filter(record)
        assert isinstance(record.args, dict)
        assert "[REDACTED]" in record.args["api_key"]

    def test_secret_masking_filter_tuple_args(self):
        """SecretMaskingFilter: tuple args 마스킹"""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Keys: %s %s",
            args=("sk-ant-api03-secret", "AIzaSyB123"),
            exc_info=None,
        )
        filter_obj = SecretMaskingFilter()
        filter_obj.filter(record)
        assert isinstance(record.args, tuple)
        assert "[REDACTED]" in record.args[0]
        assert "[REDACTED]" in record.args[1]

    def test_json_formatter(self):
        """JSONFormatter: JSON 형식 출력"""
        record = logging.LogRecord(
            name="test_module",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        formatter = JSONFormatter()
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["module"] == "test_module"
        assert data["message"] == "Test message"
        assert "timestamp" in data

    def test_json_formatter_with_exception(self):
        """JSONFormatter: 예외 정보 포함"""
        try:
            raise ValueError("Test error")
        except ValueError:
            import sys
            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="",
                lineno=0,
                msg="Error occurred",
                args=(),
                exc_info=sys.exc_info(),
            )
            formatter = JSONFormatter()
            output = formatter.format(record)
            data = json.loads(output)
            assert "exception" in data
            assert "ValueError" in data["exception"]
            assert "Test error" in data["exception"]

    def test_text_formatter(self):
        """TextFormatter: 텍스트 형식 출력"""
        record = logging.LogRecord(
            name="test_module",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="Warning message",
            args=(),
            exc_info=None,
        )
        formatter = TextFormatter()
        output = formatter.format(record)
        assert "[WARNING]" in output
        assert "[test_module]" in output
        assert "Warning message" in output

    def test_setup_logging_creates_handlers(self):
        """setup_logging: 핸들러 생성 확인"""
        setup_logging(level="INFO", log_format="text")
        logger = logging.getLogger("flux-openclaw")
        assert len(logger.handlers) > 0
        assert logger.level == logging.INFO

    def test_get_logger_returns_correct_name(self):
        """get_logger: 올바른 이름의 로거 반환"""
        setup_logging()
        logger = get_logger("my_module")
        assert logger.name == "flux-openclaw.my_module"

    def test_reset_logging_clears_handlers(self):
        """reset_logging: 핸들러 제거 확인"""
        setup_logging()
        logger = logging.getLogger("flux-openclaw")
        assert len(logger.handlers) > 0
        reset_logging()
        assert len(logger.handlers) == 0

    def test_setup_logging_json_format(self):
        """setup_logging: JSON 포맷 설정"""
        setup_logging(level="DEBUG", log_format="json")
        logger = logging.getLogger("flux-openclaw")
        assert len(logger.handlers) > 0
        # 핸들러의 포매터가 JSONFormatter인지 확인
        handler = logger.handlers[0]
        assert isinstance(handler.formatter, JSONFormatter)

    def test_setup_logging_idempotent(self):
        """setup_logging: 중복 호출 시 무시"""
        setup_logging()
        logger = logging.getLogger("flux-openclaw")
        handler_count = len(logger.handlers)
        setup_logging()  # 두 번째 호출
        # 핸들러 수가 증가하지 않음
        assert len(logger.handlers) == handler_count
