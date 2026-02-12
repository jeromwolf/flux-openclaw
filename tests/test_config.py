"""config 모듈 테스트"""
import os
import json
import pytest
import tempfile
from dataclasses import FrozenInstanceError
from unittest.mock import patch
from config import Config, load_config, get_config, reset_config, _load_config_file


class TestConfig:
    """Config 클래스 및 설정 로딩 테스트"""

    def setup_method(self):
        """각 테스트 전 설정 캐시 초기화"""
        reset_config()

    def teardown_method(self):
        """각 테스트 후 설정 캐시 초기화"""
        reset_config()

    def test_config_defaults(self):
        """기본값 검증"""
        cfg = Config()
        assert cfg.default_model == "claude-sonnet-4-20250514"
        assert cfg.max_tokens == 4096
        assert cfg.max_tool_rounds == 10
        assert cfg.max_daily_calls == 100
        assert cfg.max_history == 50
        assert cfg.llm_retry_count == 3
        assert cfg.llm_retry_base_delay == 1.0
        assert cfg.llm_retry_max_delay == 16.0
        assert cfg.tool_timeout_seconds == 30.0
        assert cfg.ws_rate_limit == 30
        assert cfg.bot_rate_limit == 10
        assert cfg.ws_max_connections == 10
        assert cfg.max_message_length == 10000
        assert cfg.discord_msg_limit == 2000
        assert cfg.slack_msg_limit == 4000
        assert cfg.telegram_msg_limit == 4000
        assert cfg.dashboard_port == 8080
        assert cfg.health_port == 8766
        assert cfg.daemon_max_restarts == 5
        assert cfg.daemon_restart_delay == 5
        assert cfg.log_level == "INFO"
        assert cfg.log_format == "text"
        assert cfg.log_file == "logs/flux-openclaw.log"
        assert cfg.log_max_bytes == 10_485_760
        assert cfg.log_backup_count == 5

    def test_config_is_frozen(self):
        """불변 객체 검증 - 필드 수정 시 예외 발생"""
        cfg = Config()
        with pytest.raises(FrozenInstanceError):
            cfg.max_tokens = 8192

    def test_load_config_defaults_only(self):
        """환경변수 없고 config.json 없으면 기본값 사용"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = load_config(os.path.join(tmpdir, "nonexistent.json"))
            assert cfg.max_tokens == 4096
            assert cfg.max_tool_rounds == 10

    def test_load_config_env_var_override(self):
        """환경변수가 기본값 오버라이드"""
        with patch.dict(os.environ, {"MAX_TOKENS": "8192", "MAX_TOOL_ROUNDS": "20"}):
            cfg = load_config("nonexistent.json")
            assert cfg.max_tokens == 8192
            assert cfg.max_tool_rounds == 20

    def test_load_config_file_override(self):
        """config.json이 기본값 오버라이드"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"max_tokens": 16384, "max_tool_rounds": 15}, f)
            config_path = f.name

        try:
            cfg = load_config(config_path)
            assert cfg.max_tokens == 16384
            assert cfg.max_tool_rounds == 15
        finally:
            os.unlink(config_path)

    def test_load_config_env_var_trumps_file(self):
        """환경변수가 config.json보다 우선"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"max_tokens": 2048}, f)
            config_path = f.name

        try:
            with patch.dict(os.environ, {"MAX_TOKENS": "8192"}):
                cfg = load_config(config_path)
                assert cfg.max_tokens == 8192
        finally:
            os.unlink(config_path)

    def test_load_config_invalid_env_var_ignored(self):
        """잘못된 타입의 환경변수는 무시되고 기본값 사용"""
        with patch.dict(os.environ, {"MAX_TOKENS": "invalid_number"}):
            cfg = load_config("nonexistent.json")
            assert cfg.max_tokens == 4096  # 기본값 유지

    def test_get_config_singleton(self):
        """get_config는 싱글턴 반환"""
        cfg1 = get_config("nonexistent.json")
        cfg2 = get_config("nonexistent.json")
        assert cfg1 is cfg2

    def test_reset_config(self):
        """reset_config 후 get_config는 재로드"""
        cfg1 = get_config("nonexistent.json")
        reset_config()
        cfg2 = get_config("nonexistent.json")
        # 새 객체가 생성되어야 함
        assert cfg1 is not cfg2

    def test_load_config_file_missing(self):
        """_load_config_file: 파일 없으면 빈 dict 반환"""
        data = _load_config_file("nonexistent_file.json")
        assert data == {}

    def test_load_config_file_invalid_json(self):
        """_load_config_file: 잘못된 JSON이면 빈 dict 반환"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json")
            config_path = f.name

        try:
            data = _load_config_file(config_path)
            assert data == {}
        finally:
            os.unlink(config_path)

    def test_load_config_multiple_env_vars(self):
        """여러 환경변수 동시 오버라이드"""
        with patch.dict(
            os.environ,
            {
                "LLM_MODEL": "claude-opus-4",
                "MAX_TOKENS": "16384",
                "LOG_LEVEL": "DEBUG",
                "LOG_FORMAT": "json",
                "DASHBOARD_PORT": "9090",
            },
        ):
            cfg = load_config("nonexistent.json")
            assert cfg.default_model == "claude-opus-4"
            assert cfg.max_tokens == 16384
            assert cfg.log_level == "DEBUG"
            assert cfg.log_format == "json"
            assert cfg.dashboard_port == 9090

    def test_load_config_float_env_var(self):
        """float 타입 환경변수 처리"""
        with patch.dict(os.environ, {"LLM_RETRY_BASE_DELAY": "2.5", "TOOL_TIMEOUT": "60.0"}):
            cfg = load_config("nonexistent.json")
            assert cfg.llm_retry_base_delay == 2.5
            assert cfg.tool_timeout_seconds == 60.0

    def test_load_config_file_non_dict_ignored(self):
        """config.json이 dict가 아니면 무시"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([1, 2, 3], f)  # list 저장
            config_path = f.name

        try:
            cfg = load_config(config_path)
            assert cfg.max_tokens == 4096  # 기본값 유지
        finally:
            os.unlink(config_path)
