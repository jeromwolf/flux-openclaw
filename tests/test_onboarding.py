"""
tests/test_onboarding.py

온보딩 마법사 테스트 (12-15 tests)
- 건너뜀 조건
- API 키 검증
- .env 파일 생성
- SCHEMA 확인
"""

import pytest
import sys
import os
import stat
import glob
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import onboarding


class TestShouldRun:
    """온보딩 실행 조건 (4 tests)"""

    def test_skip_if_env_exists_with_key(self, tmp_path, monkeypatch):
        """valid .env 있으면 건너뜀"""
        monkeypatch.chdir(tmp_path)
        env_file = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_API_KEY=sk-ant-test123456789012345")

        wizard = onboarding.OnboardingWizard()
        assert wizard.should_run() == False

    def test_run_if_env_missing(self, tmp_path, monkeypatch):
        """.env 없으면 실행 필요"""
        monkeypatch.chdir(tmp_path)
        wizard = onboarding.OnboardingWizard()
        assert wizard.should_run() == True

    def test_run_if_env_empty_key(self, tmp_path, monkeypatch):
        """빈 키면 실행 필요"""
        monkeypatch.chdir(tmp_path)
        env_file = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_API_KEY=")
        wizard = onboarding.OnboardingWizard()
        assert wizard.should_run() == True

    def test_skip_non_interactive(self, tmp_path, monkeypatch):
        """비대화형 환경에서 건너뜀"""
        monkeypatch.chdir(tmp_path)
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = False
        monkeypatch.setattr('sys.stdin', mock_stdin)
        result = onboarding.check_and_run_onboarding()
        assert result == True


class TestAPIKeyValidation:
    """API 키 검증 (3 tests)"""

    def test_valid_key_format(self):
        """sk-ant- 접두사 키 허용"""
        key = "sk-ant-test123456789012345678901234567890"
        assert onboarding._API_KEY_RE.match(key) is not None

    def test_invalid_key_format(self):
        """잘못된 형식 거부"""
        key = "invalid-key"
        assert onboarding._API_KEY_RE.match(key) is None

    def test_key_too_short(self):
        """너무 짧은 키 거부"""
        key = "sk-ant-short"
        assert onboarding._API_KEY_RE.match(key) is None


class TestEnvFile:
    """env 파일 생성 및 관리 (5 tests)"""

    def test_env_created(self, tmp_path, monkeypatch):
        """.env 파일 생성"""
        monkeypatch.chdir(tmp_path)
        wizard = onboarding.OnboardingWizard()
        config = {"ANTHROPIC_API_KEY": "sk-ant-test12345678901234567890"}
        wizard._write_env(config)
        assert (tmp_path / ".env").exists()

    def test_env_permissions(self, tmp_path, monkeypatch):
        """.env 퍼미션 0o600"""
        monkeypatch.chdir(tmp_path)
        wizard = onboarding.OnboardingWizard()
        config = {"ANTHROPIC_API_KEY": "sk-ant-test12345678901234567890"}
        wizard._write_env(config)
        mode = os.stat(tmp_path / ".env").st_mode
        assert stat.S_IMODE(mode) == 0o600

    def test_env_content(self, tmp_path, monkeypatch):
        """.env 내용 올바른지"""
        monkeypatch.chdir(tmp_path)
        wizard = onboarding.OnboardingWizard()
        config = {"ANTHROPIC_API_KEY": "sk-ant-test12345678901234567890"}
        wizard._write_env(config)
        content = (tmp_path / ".env").read_text()
        assert "ANTHROPIC_API_KEY=sk-ant-test12345678901234567890" in content

    def test_env_backup(self, tmp_path, monkeypatch):
        """기존 .env 백업"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("OLD_KEY=value")
        wizard = onboarding.OnboardingWizard()
        config = {"ANTHROPIC_API_KEY": "sk-ant-test12345678901234567890"}
        wizard._write_env(config)
        # 백업 파일 존재 확인
        backups = glob.glob(str(tmp_path / ".env.backup.*"))
        assert len(backups) >= 1

    def test_env_with_provider(self, tmp_path, monkeypatch):
        """LLM 프로바이더 설정 포함"""
        monkeypatch.chdir(tmp_path)
        wizard = onboarding.OnboardingWizard()
        config = {
            "ANTHROPIC_API_KEY": "sk-ant-test12345678901234567890",
            "LLM_PROVIDER": "openai",
        }
        wizard._write_env(config)
        content = (tmp_path / ".env").read_text()
        assert "LLM_PROVIDER=openai" in content


class TestOnboardingModule:
    """온보딩 모듈 전체 (1 test)"""

    def test_module_functions(self):
        """모듈에 필수 함수 존재"""
        assert hasattr(onboarding, 'check_and_run_onboarding')
        assert hasattr(onboarding, 'OnboardingWizard')
        assert callable(onboarding.check_and_run_onboarding)
        assert callable(onboarding.OnboardingWizard)


class TestWizardFlow:
    """온보딩 마법사 플로우 (3 tests)"""

    def test_step_welcome(self, tmp_path, monkeypatch, capsys):
        """환영 메시지 출력"""
        monkeypatch.chdir(tmp_path)
        wizard = onboarding.OnboardingWizard()
        wizard._step_welcome()
        captured = capsys.readouterr()
        assert "flux-openclaw" in captured.out
        assert "마법사" in captured.out

    def test_step_api_key_cancel(self, tmp_path, monkeypatch):
        """API 키 입력 취소"""
        monkeypatch.chdir(tmp_path)
        wizard = onboarding.OnboardingWizard()
        with patch('getpass.getpass', side_effect=KeyboardInterrupt):
            result = wizard._step_api_key()
            assert result is None

    def test_step_summary(self, tmp_path, monkeypatch, capsys):
        """설정 요약 출력"""
        monkeypatch.chdir(tmp_path)
        wizard = onboarding.OnboardingWizard()
        config = {"ANTHROPIC_API_KEY": "sk-ant-test12345678901234567890"}
        wizard._step_summary(config)
        captured = capsys.readouterr()
        assert "설정 완료" in captured.out
        assert "sk-ant-" in captured.out


class TestEdgeCases:
    """엣지 케이스 (2 tests)"""

    def test_env_with_placeholder_key(self, tmp_path, monkeypatch):
        """플레이스홀더 키는 실행 필요"""
        monkeypatch.chdir(tmp_path)
        env_file = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_API_KEY=your-api-key-here")
        wizard = onboarding.OnboardingWizard()
        assert wizard.should_run() == True

    def test_interface_tokens_written(self, tmp_path, monkeypatch):
        """인터페이스 토큰이 .env에 포함"""
        monkeypatch.chdir(tmp_path)
        wizard = onboarding.OnboardingWizard()
        config = {
            "ANTHROPIC_API_KEY": "sk-ant-test12345678901234567890",
            "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF",
        }
        wizard._write_env(config)
        content = (tmp_path / ".env").read_text()
        assert "TELEGRAM_BOT_TOKEN=123456:ABC-DEF" in content
