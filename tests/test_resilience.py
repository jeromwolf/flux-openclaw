"""resilience 모듈 테스트 (재시도, 타임아웃)"""
import os
import sys
import time
import asyncio
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from openclaw.resilience import (
    _is_retryable,
    retry_llm_call,
    retry_llm_call_async,
    with_timeout,
    with_timeout_async,
    _TimeoutError,
    _RETRYABLE_STATUS_CODES,
)


# ============================================================
# _is_retryable 테스트
# ============================================================

class TestIsRetryable:
    """_is_retryable 함수 테스트"""

    @pytest.mark.parametrize("code", [429, 500, 502, 503, 529])
    def test_retryable_status_codes(self, code):
        """재시도 가능한 HTTP 상태 코드"""
        exc = Exception("API error")
        exc.status_code = code
        assert _is_retryable(exc) is True

    @pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
    def test_non_retryable_status_codes(self, code):
        """재시도 불가능한 HTTP 상태 코드"""
        exc = Exception("Client error")
        exc.status_code = code
        assert _is_retryable(exc) is False

    def test_connection_error(self):
        """ConnectionError 재시도 가능"""
        assert _is_retryable(ConnectionError("refused")) is True

    def test_timeout_error(self):
        """TimeoutError 재시도 가능"""
        assert _is_retryable(TimeoutError("timed out")) is True

    def test_api_connection_error_by_name(self):
        """APIConnectionError (이름 기반) 재시도 가능"""
        # SDK를 import하지 않고 이름으로 판별하는 로직 테스트
        class APIConnectionError(Exception):
            pass
        assert _is_retryable(APIConnectionError("network")) is True

    def test_regular_exception_not_retryable(self):
        """일반 Exception은 재시도 불가"""
        assert _is_retryable(Exception("generic")) is False

    def test_value_error_not_retryable(self):
        """ValueError는 재시도 불가"""
        assert _is_retryable(ValueError("bad value")) is False

    def test_type_error_not_retryable(self):
        """TypeError는 재시도 불가"""
        assert _is_retryable(TypeError("wrong type")) is False


# ============================================================
# retry_llm_call 테스트
# ============================================================

class TestRetryLlmCall:
    """retry_llm_call 함수 테스트"""

    @patch("openclaw.resilience.time.sleep")
    def test_success_first_try(self, mock_sleep):
        """첫 시도에 성공"""
        fn = MagicMock(return_value="ok")
        result = retry_llm_call(fn)
        assert result == "ok"
        fn.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("openclaw.resilience.time.sleep")
    def test_success_after_retry(self, mock_sleep):
        """재시도 후 성공"""
        exc = Exception("rate limit")
        exc.status_code = 429
        fn = MagicMock(side_effect=[exc, "recovered"])

        result = retry_llm_call(fn, max_retries=3)
        assert result == "recovered"
        assert fn.call_count == 2
        assert mock_sleep.call_count == 1

    @patch("openclaw.resilience.time.sleep")
    def test_max_retries_exceeded(self, mock_sleep):
        """최대 재시도 초과"""
        exc = Exception("server error")
        exc.status_code = 500
        fn = MagicMock(side_effect=exc)

        with pytest.raises(Exception, match="server error"):
            retry_llm_call(fn, max_retries=2)

        assert fn.call_count == 3  # 초기 + 2회 재시도
        assert mock_sleep.call_count == 2

    @patch("openclaw.resilience.time.sleep")
    def test_non_retryable_raises_immediately(self, mock_sleep):
        """재시도 불가능한 에러는 즉시 발생"""
        exc = ValueError("bad request")
        fn = MagicMock(side_effect=exc)

        with pytest.raises(ValueError, match="bad request"):
            retry_llm_call(fn, max_retries=3)

        fn.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("openclaw.resilience.time.sleep")
    def test_custom_params(self, mock_sleep):
        """커스텀 재시도 파라미터"""
        exc = Exception("overloaded")
        exc.status_code = 529
        fn = MagicMock(side_effect=[exc, exc, "ok"])

        result = retry_llm_call(fn, max_retries=5, base_delay=0.5, max_delay=4.0)
        assert result == "ok"
        assert fn.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("openclaw.resilience.time.sleep")
    def test_exponential_backoff(self, mock_sleep):
        """지수 백오프 확인"""
        exc = Exception("rate limit")
        exc.status_code = 429
        fn = MagicMock(side_effect=[exc, exc, exc, "ok"])

        with patch("openclaw.resilience.random.uniform", return_value=0):  # jitter 제거
            retry_llm_call(fn, max_retries=3, base_delay=1.0, max_delay=16.0)

        # attempt 0: delay = 1.0*2^0 = 1.0
        # attempt 1: delay = 1.0*2^1 = 2.0
        # attempt 2: delay = 1.0*2^2 = 4.0
        calls = mock_sleep.call_args_list
        assert len(calls) == 3
        assert calls[0][0][0] == 1.0
        assert calls[1][0][0] == 2.0
        assert calls[2][0][0] == 4.0


# ============================================================
# with_timeout 테스트
# ============================================================

class TestWithTimeout:
    """with_timeout 함수 테스트"""

    def test_completes_in_time(self):
        """타임아웃 전에 완료"""
        def fast_fn(x=1):
            return x * 2
        result = with_timeout(fast_fn, timeout_seconds=5.0, x=21)
        assert result == 42

    def test_times_out(self):
        """타임아웃 초과"""
        def slow_fn():
            time.sleep(10)
            return "done"

        with pytest.raises(_TimeoutError):
            with_timeout(slow_fn, timeout_seconds=0.1)

    def test_zero_timeout_runs_without_timeout(self):
        """timeout_seconds=0 이면 타임아웃 없이 실행"""
        def fn(msg="hello"):
            return msg
        result = with_timeout(fn, timeout_seconds=0, msg="world")
        assert result == "world"

    def test_negative_timeout_runs_without_timeout(self):
        """timeout_seconds < 0 이면 타임아웃 없이 실행"""
        def fn():
            return "no timeout"
        result = with_timeout(fn, timeout_seconds=-1.0)
        assert result == "no timeout"

    def test_kwargs_passed(self):
        """kwargs가 fn에 전달되는지 확인"""
        def fn(a=0, b=0):
            return a + b
        result = with_timeout(fn, timeout_seconds=5.0, a=3, b=7)
        assert result == 10


# ============================================================
# with_timeout_async 테스트
# ============================================================

class TestWithTimeoutAsync:
    """with_timeout_async 함수 테스트"""

    def test_async_completes_in_time(self):
        """비동기: 타임아웃 전에 완료"""
        def fast_fn(x=1):
            return x + 1
        result = asyncio.run(with_timeout_async(fast_fn, timeout_seconds=5.0, x=9))
        assert result == 10

    def test_async_times_out(self):
        """비동기: 타임아웃 초과"""
        def slow_fn():
            time.sleep(10)
            return "done"

        with pytest.raises(_TimeoutError):
            asyncio.run(with_timeout_async(slow_fn, timeout_seconds=0.1))

    def test_async_zero_timeout(self):
        """비동기: timeout_seconds=0 이면 타임아웃 없이 실행"""
        def fn(val="default"):
            return val
        result = asyncio.run(with_timeout_async(fn, timeout_seconds=0, val="async"))
        assert result == "async"


# ============================================================
# retry_llm_call_async 테스트
# ============================================================

class TestRetryLlmCallAsync:
    """retry_llm_call_async 함수 테스트"""

    @patch("openclaw.resilience.asyncio.sleep")
    def test_async_success_first_try(self, mock_async_sleep):
        """비동기: 첫 시도에 성공"""
        mock_async_sleep.return_value = asyncio.coroutine(lambda: None)()
        fn = MagicMock(return_value="async ok")

        result = asyncio.run(retry_llm_call_async(fn))
        assert result == "async ok"
        fn.assert_called_once()

    @patch("openclaw.resilience.asyncio.sleep")
    def test_async_non_retryable_raises(self, mock_async_sleep):
        """비동기: 재시도 불가능한 에러 즉시 발생"""
        mock_async_sleep.return_value = asyncio.coroutine(lambda: None)()
        fn = MagicMock(side_effect=ValueError("bad"))

        with pytest.raises(ValueError, match="bad"):
            asyncio.run(retry_llm_call_async(fn, max_retries=3))
        fn.assert_called_once()


# ============================================================
# _TimeoutError 클래스 테스트
# ============================================================

class TestTimeoutErrorClass:
    """_TimeoutError 클래스 테스트"""

    def test_is_exception_subclass(self):
        """Exception의 서브클래스인지 확인"""
        assert issubclass(_TimeoutError, Exception)

    def test_can_be_raised_and_caught(self):
        """raise/catch 가능"""
        with pytest.raises(_TimeoutError):
            raise _TimeoutError("test timeout")

    def test_message(self):
        """에러 메시지"""
        err = _TimeoutError("custom message")
        assert str(err) == "custom message"


# ============================================================
# _RETRYABLE_STATUS_CODES 상수 테스트
# ============================================================

class TestConstants:
    """모듈 상수 테스트"""

    def test_retryable_status_codes(self):
        """재시도 대상 상태 코드 확인"""
        assert 429 in _RETRYABLE_STATUS_CODES
        assert 500 in _RETRYABLE_STATUS_CODES
        assert 502 in _RETRYABLE_STATUS_CODES
        assert 503 in _RETRYABLE_STATUS_CODES
        assert 529 in _RETRYABLE_STATUS_CODES
        assert 200 not in _RETRYABLE_STATUS_CODES
