"""사용량 추적 테스트"""
import os
import json
import pytest
from datetime import datetime
from unittest.mock import patch
from core import load_usage, save_usage, check_daily_limit, increment_usage, USAGE_FILE


class TestUsageTracking:
    """사용량 추적 기능 테스트"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        """각 테스트마다 임시 디렉토리 사용"""
        monkeypatch.chdir(tmp_path)

    def test_load_empty_usage(self):
        """파일 없을 때 기본값 반환"""
        usage = load_usage()
        today = datetime.now().strftime("%Y-%m-%d")
        assert usage["date"] == today
        assert usage["calls"] == 0
        assert usage["input_tokens"] == 0
        assert usage["output_tokens"] == 0

    def test_save_and_load(self):
        """저장 후 로드"""
        today = datetime.now().strftime("%Y-%m-%d")
        data = {"date": today, "calls": 5, "input_tokens": 1000, "output_tokens": 500}
        save_usage(data)
        loaded = load_usage()
        assert loaded["calls"] == 5
        assert loaded["input_tokens"] == 1000

    def test_load_stale_date_resets(self):
        """날짜가 다르면 초기화"""
        data = {"date": "2020-01-01", "calls": 99, "input_tokens": 50000, "output_tokens": 25000}
        with open(USAGE_FILE, "w") as f:
            json.dump(data, f)
        usage = load_usage()
        assert usage["calls"] == 0

    def test_check_daily_limit_under(self):
        """한도 미만이면 True"""
        assert check_daily_limit(100) is True

    def test_check_daily_limit_at_limit(self):
        """한도 도달하면 False"""
        today = datetime.now().strftime("%Y-%m-%d")
        data = {"date": today, "calls": 100, "input_tokens": 0, "output_tokens": 0}
        with open(USAGE_FILE, "w") as f:
            json.dump(data, f)
        assert check_daily_limit(100) is False

    def test_check_daily_limit_custom(self):
        """커스텀 한도"""
        today = datetime.now().strftime("%Y-%m-%d")
        data = {"date": today, "calls": 5, "input_tokens": 0, "output_tokens": 0}
        with open(USAGE_FILE, "w") as f:
            json.dump(data, f)
        assert check_daily_limit(10) is True
        assert check_daily_limit(5) is False

    def test_increment_usage(self):
        """사용량 증가"""
        increment_usage(100, 50)
        usage = load_usage()
        assert usage["calls"] == 1
        assert usage["input_tokens"] == 100
        assert usage["output_tokens"] == 50

    def test_increment_usage_accumulates(self):
        """누적 증가"""
        increment_usage(100, 50)
        increment_usage(200, 100)
        usage = load_usage()
        assert usage["calls"] == 2
        assert usage["input_tokens"] == 300
        assert usage["output_tokens"] == 150

    def test_corrupted_file_handled(self):
        """손상된 파일 처리"""
        with open(USAGE_FILE, "w") as f:
            f.write("not json")
        usage = load_usage()
        assert usage["calls"] == 0
