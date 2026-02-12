"""admin_cli 모듈 테스트"""
import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock, mock_open
from argparse import Namespace

# admin_cli.py는 프로젝트 루트에 있음
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import admin_cli


class TestBuildParser:
    """argparse 파서 구성 테스트"""

    def test_parser_prog_name(self):
        """파서 프로그램 이름 확인"""
        parser = admin_cli.build_parser()
        assert parser.prog == "flux-admin"

    def test_parser_subcommands_exist(self):
        """필수 서브커맨드 존재 확인"""
        parser = admin_cli.build_parser()

        # status
        args = parser.parse_args(["status"])
        assert args.command == "status"

        # usage
        args = parser.parse_args(["usage"])
        assert args.command == "usage"

        # config
        args = parser.parse_args(["config", "show"])
        assert args.command == "config"
        assert args.config_action == "show"

        # conversations
        args = parser.parse_args(["conversations", "list"])
        assert args.command == "conversations"
        assert args.conv_action == "list"

        # memory
        args = parser.parse_args(["memory", "list"])
        assert args.command == "memory"
        assert args.mem_action == "list"


class TestCmdStatus:
    """cmd_status 함수 테스트"""

    @patch("openclaw.memory_store.MemoryStore")
    @patch("core.ToolManager")
    @patch("config.get_config")
    def test_status_runs_without_error(self, mock_get_config, mock_tool_mgr_cls, mock_mem_store_cls, capsys):
        """상태 명령 실행 (모든 모듈 mock)"""
        # Config mock
        mock_cfg = MagicMock()
        mock_cfg.default_model = "claude-sonnet-4-20250514"
        mock_cfg.max_tokens = 4096
        mock_cfg.max_tool_rounds = 10
        mock_cfg.max_daily_calls = 100
        mock_cfg.log_level = "INFO"
        mock_get_config.return_value = mock_cfg

        # ToolManager mock
        mock_tool_mgr = MagicMock()
        mock_tool_mgr.functions = {"tool1": {}, "tool2": {}}
        mock_tool_mgr_cls.return_value = mock_tool_mgr

        # MemoryStore mock
        mock_store = MagicMock()
        mock_store._load.return_value = [
            {"category": "user_preferences", "key": "k1"},
            {"category": "facts", "key": "k2"},
        ]
        mock_mem_store_cls.return_value = mock_store

        args = Namespace(command="status")
        admin_cli.cmd_status(args)

        captured = capsys.readouterr()
        assert "시스템 상태" in captured.out
        assert "claude-sonnet-4-20250514" in captured.out
        assert "tool1, tool2" in captured.out
        assert "2개 항목 저장됨" in captured.out


class TestCmdUsage:
    """cmd_usage 함수 테스트"""

    @patch("core.load_usage")
    def test_usage_text_output(self, mock_load_usage, capsys):
        """사용량 텍스트 출력 (cost_tracker 없이)"""
        mock_load_usage.return_value = {
            "date": "2026-02-12",
            "calls": 5,
            "input_tokens": 1000,
            "output_tokens": 500,
        }

        args = Namespace(json=False)
        admin_cli.cmd_usage(args)

        captured = capsys.readouterr()
        assert "오늘의 사용량" in captured.out
        assert "2026-02-12" in captured.out
        assert "5회" in captured.out
        assert "1,000" in captured.out
        assert "500" in captured.out
        # cost_tracker가 사용 가능하면 실제 비용 계산, 아니면 $0.0000
        assert "USD" in captured.out

    @patch("core.load_usage")
    def test_usage_json_output(self, mock_load_usage, capsys):
        """사용량 JSON 출력 (cost_tracker 없이)"""
        mock_load_usage.return_value = {
            "date": "2026-02-12",
            "calls": 5,
            "input_tokens": 1000,
            "output_tokens": 500,
        }

        args = Namespace(json=True)
        admin_cli.cmd_usage(args)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["date"] == "2026-02-12"
        assert output["calls"] == 5
        assert output["input_tokens"] == 1000
        assert output["output_tokens"] == 500
        # cost_tracker가 사용 가능하면 실제 비용 계산됨
        assert isinstance(output["cost_usd"], (int, float))


class TestCmdConfig:
    """cmd_config 함수 테스트"""

    @patch("config.get_config")
    def test_config_show(self, mock_get_config, capsys):
        """config show - 전체 설정 JSON 출력"""
        mock_cfg = MagicMock()
        mock_cfg.default_model = "claude-sonnet-4-20250514"
        mock_cfg.max_tokens = 4096
        mock_get_config.return_value = mock_cfg

        # dataclasses.asdict mock
        with patch("dataclasses.asdict") as mock_asdict:
            mock_asdict.return_value = {
                "default_model": "claude-sonnet-4-20250514",
                "max_tokens": 4096,
            }

            args = Namespace(config_action="show")
            admin_cli.cmd_config_show(args)

            captured = capsys.readouterr()
            output = json.loads(captured.out)
            assert output["default_model"] == "claude-sonnet-4-20250514"
            assert output["max_tokens"] == 4096

    @patch("config.get_config")
    def test_config_get_key(self, mock_get_config, capsys):
        """config get - 특정 키 조회"""
        mock_cfg = MagicMock()
        mock_cfg.default_model = "claude-sonnet-4-20250514"
        mock_get_config.return_value = mock_cfg

        args = Namespace(key="default_model")
        admin_cli.cmd_config_get(args)

        captured = capsys.readouterr()
        assert "claude-sonnet-4-20250514" in captured.out


class TestCmdConversations:
    """cmd_conversations 함수 테스트"""

    @patch("openclaw.conversation_store.ConversationStore")
    def test_conversations_stats(self, mock_conv_store_cls, capsys):
        """conversations stats - 대화 통계"""
        mock_store = MagicMock()
        mock_store.get_stats.return_value = {
            "total_conversations": 10,
            "total_messages": 50,
            "conversations_by_interface": {
                "cli": 5,
                "ws": 3,
                "telegram": 2,
            }
        }
        mock_conv_store_cls.return_value = mock_store

        args = Namespace(conv_action="stats")
        admin_cli.cmd_conversations_stats(args)

        captured = capsys.readouterr()
        assert "대화 통계" in captured.out
        assert "총 대화 수: 10" in captured.out
        assert "총 메시지 수: 50" in captured.out
        assert "cli: 5개" in captured.out


class TestCmdMemory:
    """cmd_memory 함수 테스트"""

    @patch("openclaw.memory_store.MemoryStore")
    def test_memory_stats(self, mock_mem_store_cls, capsys):
        """memory stats - 메모리 통계"""
        mock_store = MagicMock()
        mock_store.MAX_MEMORIES = 1000
        mock_store.VALID_CATEGORIES = ["user_preferences", "facts", "tasks"]
        mock_store.CATEGORY_LIMITS = {
            "user_preferences": 100,
            "facts": 500,
            "tasks": 200,
        }
        mock_store._load.return_value = [
            {"category": "user_preferences", "importance": 5},
            {"category": "facts", "importance": 3},
            {"category": "facts", "importance": 3},
        ]
        mock_mem_store_cls.return_value = mock_store

        args = Namespace(mem_action="stats")
        admin_cli.cmd_memory_stats(args)

        captured = capsys.readouterr()
        assert "메모리 통계" in captured.out
        assert "전체 항목 수: 3" in captured.out
        assert "최대 용량: 1000" in captured.out
        assert "user_preferences: 1/100개" in captured.out
        assert "facts: 2/500개" in captured.out


class TestMain:
    """main 함수 테스트"""

    def test_main_no_args(self, capsys):
        """인자 없이 실행 시 help 출력"""
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["admin_cli.py"]):
                admin_cli.main()

        assert exc_info.value.code == 1

    @patch("admin_cli.cmd_status")
    def test_main_status(self, mock_cmd_status):
        """main - status 명령 디스패치"""
        with patch("sys.argv", ["admin_cli.py", "status"]):
            admin_cli.main()

        mock_cmd_status.assert_called_once()

    @patch("admin_cli.cmd_usage")
    def test_main_usage(self, mock_cmd_usage):
        """main - usage 명령 디스패치"""
        with patch("sys.argv", ["admin_cli.py", "usage"]):
            admin_cli.main()

        mock_cmd_usage.assert_called_once()
