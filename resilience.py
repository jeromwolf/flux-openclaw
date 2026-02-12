"""
flux-openclaw 복원력 모듈

LLM API 호출 재시도 (지수 백오프)와 도구 실행 타임아웃을 제공합니다.

사용법:
    from resilience import retry_llm_call, with_timeout
    from functools import partial

    # LLM 재시도
    response = retry_llm_call(partial(provider.create_message, messages=msgs))

    # 도구 타임아웃
    result = with_timeout(tool_func, timeout_seconds=30, text="hello")
"""

import time
import random
import signal
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from functools import partial


# 재시도 대상 HTTP 상태 코드
_RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 529)

# 최소 타임아웃 (초)
_MIN_TIMEOUT = 1.0


def _is_retryable(exc: Exception) -> bool:
    """재시도 가능한 예외인지 판별

    Anthropic/OpenAI SDK의 APIStatusError는 status_code 속성을 가짐.
    SDK를 직접 import하지 않고 속성 검사로 판별.
    """
    status_code = getattr(exc, "status_code", None)
    if status_code is not None and status_code in _RETRYABLE_STATUS_CODES:
        return True
    # 연결 오류 등 네트워크 에러
    exc_name = type(exc).__name__
    if exc_name in ("ConnectionError", "TimeoutError", "APIConnectionError"):
        return True
    return False


def retry_llm_call(
    fn,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 16.0,
):
    """LLM API 호출을 지수 백오프로 재시도

    전략: base_delay * 2^attempt + jitter (최대 max_delay)
    재시도 대상: HTTP 429/500/502/503/529, 연결 오류

    Args:
        fn: 호출할 함수 (인자 없는 callable, partial로 감싸서 전달)
        max_retries: 최대 재시도 횟수 (기본 3)
        base_delay: 기본 지연 시간 (초)
        max_delay: 최대 지연 시간 (초)

    Returns:
        fn()의 반환값

    Raises:
        마지막 시도의 예외를 그대로 전파
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries or not _is_retryable(exc):
                raise
            # 지수 백오프 + 지터
            delay = min(base_delay * (2 ** attempt), max_delay)
            jitter = random.uniform(0, delay * 0.1)
            time.sleep(delay + jitter)
    raise last_exc


async def retry_llm_call_async(
    fn,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 16.0,
):
    """LLM API 호출을 지수 백오프로 재시도 (비동기 버전)

    fn은 동기 함수 — asyncio.to_thread로 실행합니다.
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return await asyncio.to_thread(fn)
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries or not _is_retryable(exc):
                raise
            delay = min(base_delay * (2 ** attempt), max_delay)
            jitter = random.uniform(0, delay * 0.1)
            await asyncio.sleep(delay + jitter)
    raise last_exc


class _TimeoutError(Exception):
    """도구 실행 타임아웃"""
    pass


def with_timeout(fn, timeout_seconds: float = 30.0, **kwargs):
    """도구 실행에 타임아웃 적용

    ThreadPoolExecutor 기반 (크로스 플랫폼 호환).

    Args:
        fn: 실행할 함수
        timeout_seconds: 타임아웃 (초, 기본 30)
        **kwargs: fn에 전달할 인자

    Returns:
        fn(**kwargs) 결과

    Raises:
        _TimeoutError: 타임아웃 초과 시
    """
    if timeout_seconds <= 0:
        timeout_seconds = _MIN_TIMEOUT

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn, **kwargs)
        try:
            return future.result(timeout=timeout_seconds)
        except FuturesTimeoutError:
            raise _TimeoutError(
                f"도구 실행 타임아웃 ({timeout_seconds}초 초과)"
            )


async def with_timeout_async(fn, timeout_seconds: float = 30.0, **kwargs):
    """비동기 도구 실행에 타임아웃 적용

    asyncio.wait_for + to_thread 사용.

    Args:
        fn: 실행할 동기 함수
        timeout_seconds: 타임아웃 (초)
        **kwargs: fn에 전달할 인자

    Returns:
        fn(**kwargs) 결과

    Raises:
        _TimeoutError: 타임아웃 초과 시
    """
    if timeout_seconds <= 0:
        timeout_seconds = _MIN_TIMEOUT

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, **kwargs),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        raise _TimeoutError(
            f"도구 실행 타임아웃 ({timeout_seconds}초 초과)"
        )
