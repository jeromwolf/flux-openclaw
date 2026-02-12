"""
flux-openclaw 대화 엔진 모듈

5개 인터페이스(main.py, ws_server.py, telegram_bot.py, discord_bot.py, slack_bot.py)에서
중복되던 ~576줄의 도구 사용 루프를 단일 ConversationEngine 클래스로 통합합니다.

설계 원칙:
- ConversationEngine은 messages 리스트를 소유하지 않음 (호출자가 참조로 전달)
- ConversationEngine은 provider/client를 소유하지 않음 (호출자가 전달)
- 콜백 기반으로 인터페이스별 동작 분리
- 동기(run_turn) + 비동기(run_turn_async) 지원
- resilience.py 연동 (재시도, 타임아웃)
- config.py 연동 (설정값)
- 신규 의존성 없음 (stdlib only)

사용법:
    from conversation_engine import ConversationEngine, TurnResult

    engine = ConversationEngine(
        provider=provider,
        client=None,
        tool_mgr=tool_mgr,
        system_prompt=system_prompt,
        restricted_tools={"save_text_file", "screen_capture"},
    )
    result = engine.run_turn(messages)
    # 또는 비동기: result = await engine.run_turn_async(messages)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from functools import partial
from typing import Callable, Optional, Set

from core import ToolManager, _filter_tool_input, increment_usage
from config import get_config
from resilience import (
    retry_llm_call,
    retry_llm_call_async,
    with_timeout,
    with_timeout_async,
    _TimeoutError,
)
from logging_config import get_logger

# 비용 추적 (선택적)
try:
    from cost_tracker import calculate_cost as _calculate_cost
    _has_cost_tracker = True
except ImportError:
    _has_cost_tracker = False

# 스트리밍 이벤트 (선택적)
try:
    from llm_provider import StreamEvent
except ImportError:
    StreamEvent = None

_logger = get_logger("conversation_engine")


@dataclass
class TurnResult:
    """단일 대화 턴의 결과"""

    text: str = ""                  # 최종 텍스트 응답
    tool_rounds: int = 0            # 도구 라운드 수
    input_tokens: int = 0           # 총 입력 토큰
    output_tokens: int = 0          # 총 출력 토큰
    cost_usd: float = 0.0           # 총 비용 (USD)
    stop_reason: str = ""           # 마지막 stop_reason
    error: str | None = None        # 에러 메시지 (있을 경우)


class ConversationEngine:
    """도구 사용 루프를 포함한 대화 엔진

    provider 또는 client 중 하나를 전달합니다.
    provider가 있으면 provider.create_message()를, 없으면
    client.messages.create()를 사용합니다.
    """

    def __init__(
        self,
        provider,
        client,
        tool_mgr: ToolManager,
        system_prompt: str,
        *,
        restricted_tools: set[str] | None = None,
        on_llm_start: Callable | None = None,
        on_tool_start: Callable | None = None,
        on_tool_end: Callable | None = None,
        on_llm_response: Callable | None = None,
    ):
        self.provider = provider
        self.client = client
        self.tool_mgr = tool_mgr
        self.system_prompt = system_prompt
        self.restricted_tools = restricted_tools or set()
        self.on_llm_start = on_llm_start
        self.on_tool_start = on_tool_start
        self.on_tool_end = on_tool_end
        self.on_llm_response = on_llm_response

        # 모델명 (비용 추적용)
        self._model_name = getattr(provider, "model", None) if provider else None

    # ------------------------------------------------------------------
    # 공용 헬퍼
    # ------------------------------------------------------------------

    def _track_cost(self, inp: int, out: int, result: TurnResult, *, user_id: str = "default") -> None:
        """비용 추적 및 사용량 증가"""
        cost_usd = 0.0
        if _has_cost_tracker and isinstance(self._model_name, str):
            cost = _calculate_cost(self._model_name, inp, out)
            cost_usd = cost.total_cost_usd
        if user_id != "default":
            increment_usage(inp, out, cost_usd=cost_usd, user_id=user_id)
        else:
            increment_usage(inp, out, cost_usd=cost_usd)
        result.input_tokens += inp
        result.output_tokens += out
        result.cost_usd += cost_usd

    @staticmethod
    def trim_history(messages: list, max_history: int) -> None:
        """messages를 in-place로 max_history 이하로 트리밍.

        트리밍 후 첫 메시지가 user 역할이 되도록 보정합니다.
        """
        if len(messages) > max_history:
            messages[:] = messages[-max_history:]
            while messages and messages[0]["role"] != "user":
                messages.pop(0)

    def _tool_schemas(self) -> list:
        """restricted_tools를 제외한 도구 스키마 목록 반환"""
        if not self.restricted_tools:
            return self.tool_mgr.schemas
        return [s for s in self.tool_mgr.schemas if s["name"] not in self.restricted_tools]

    def _find_schema(self, tool_name: str):
        """이름으로 도구 스키마 검색"""
        return next((s for s in self.tool_mgr.schemas if s["name"] == tool_name), None)

    def _make_llm_call(self, messages: list, tool_schemas: list, cfg):
        """LLM API 호출 partial 생성"""
        if self.provider:
            return partial(
                self.provider.create_message,
                messages=messages,
                system=self.system_prompt,
                tools=tool_schemas,
                max_tokens=cfg.max_tokens,
            )
        return partial(
            self.client.messages.create,
            model=cfg.default_model,
            max_tokens=cfg.max_tokens,
            system=self.system_prompt,
            tools=tool_schemas,
            messages=messages,
        )

    @staticmethod
    def _extract_text(response) -> str:
        """응답 content에서 텍스트 블록을 추출"""
        parts = []
        for block in response.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "".join(parts)

    @staticmethod
    def _max_tokens_error_results(content) -> list:
        """max_tokens로 잘린 응답의 tool_use 블록에 대한 에러 tool_result 생성"""
        tool_uses = [b for b in content if b.type == "tool_use"]
        if not tool_uses:
            return []
        return [{
            "type": "tool_result",
            "tool_use_id": b.id,
            "content": "Error: 응답이 잘려서 도구 실행 불가. 더 짧게 시도해주세요.",
            "is_error": True,
        } for b in tool_uses]

    @staticmethod
    def _safe_result(result) -> str:
        """도구 결과를 안전한 문자열로 변환 (마커 이스케이프)"""
        safe = str(result).replace("[TOOL OUTPUT]", "[TOOL_OUTPUT]").replace("[/TOOL OUTPUT]", "[/TOOL_OUTPUT]")
        return f"[TOOL OUTPUT]\n{safe}\n[/TOOL OUTPUT]"

    # ------------------------------------------------------------------
    # 동기 메서드 (main.py CLI용)
    # ------------------------------------------------------------------

    def run_turn(self, messages: list, *, user_id: str = "default") -> TurnResult:
        """동기 대화 턴 실행. messages를 in-place로 수정합니다."""
        cfg = get_config()
        result = TurnResult()

        try:
            self.tool_mgr.reload_if_changed()
            self.trim_history(messages, cfg.max_history)
            tool_schemas = self._tool_schemas()
            tool_round = 0

            while tool_round < cfg.max_tool_rounds:
                if self.on_llm_start:
                    self.on_llm_start()

                fn = self._make_llm_call(messages, tool_schemas, cfg)
                response = retry_llm_call(
                    fn,
                    max_retries=cfg.llm_retry_count,
                    base_delay=cfg.llm_retry_base_delay,
                    max_delay=cfg.llm_retry_max_delay,
                )

                if self.on_llm_response:
                    self.on_llm_response(response)

                # 사용량 추적
                inp = response.usage.input_tokens
                out = response.usage.output_tokens
                self._track_cost(inp, out, result, user_id=user_id)
                result.stop_reason = response.stop_reason

                # max_tokens 처리
                if response.stop_reason == "max_tokens":
                    messages.append({"role": "assistant", "content": response.content})
                    error_results = self._max_tokens_error_results(response.content)
                    if error_results:
                        messages.append({"role": "user", "content": error_results})
                        tool_round += 1
                        continue
                    break

                # 도구 호출 확인
                tool_uses = [b for b in response.content if b.type == "tool_use"]

                if not tool_uses:
                    messages.append({"role": "assistant", "content": response.content})
                    result.text = self._extract_text(response)
                    break

                # 도구 실행
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []

                for tool_use in tool_uses:
                    tool_name = tool_use.name

                    # 제한된 도구 차단
                    if tool_name in self.restricted_tools:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Error: '{tool_name}' 도구는 사용할 수 없습니다. (보안 제한)",
                            "is_error": True,
                        })
                        continue

                    fn = self.tool_mgr.functions.get(tool_name)
                    if not fn:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Error: 알 수 없는 도구: {tool_name}",
                        })
                        continue

                    if self.on_tool_start:
                        self.on_tool_start(tool_name, tool_use.input)

                    try:
                        schema = self._find_schema(tool_name)
                        filtered = _filter_tool_input(tool_use.input, schema) if schema else tool_use.input
                        tool_result = with_timeout(fn, timeout_seconds=cfg.tool_timeout_seconds, **filtered)
                    except _TimeoutError:
                        tool_result = "Error: 도구 실행 타임아웃"
                    except Exception:
                        _logger.exception("도구 실행 실패: %s", tool_name)
                        tool_result = "Error: 도구 실행 실패"

                    if self.on_tool_end:
                        self.on_tool_end(tool_name, tool_result)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": self._safe_result(tool_result),
                    })

                messages.append({"role": "user", "content": tool_results})
                tool_round += 1

            result.tool_rounds = tool_round
            if tool_round >= cfg.max_tool_rounds:
                result.error = f"도구 호출이 {cfg.max_tool_rounds}회를 초과하여 중단되었습니다."

        except Exception:
            result.error = "요청 처리 중 오류가 발생했습니다."

        return result

    # ------------------------------------------------------------------
    # 동기 스트리밍 메서드
    # ------------------------------------------------------------------

    def run_turn_stream(self, messages: list, *, user_id: str = "default"):
        """동기 스트리밍 대화 턴. StreamEvent를 yield합니다.

        마지막 이벤트의 type이 "turn_complete"이고 data가 TurnResult입니다.

        사용 패턴::

            for event in engine.run_turn_stream(messages):
                if event.type == "text_delta":
                    print(event.data, end="", flush=True)
                elif event.type == "turn_complete":
                    result = event.data  # TurnResult
        """
        cfg = get_config()
        result = TurnResult()

        if not self.provider or not hasattr(self.provider, "create_message_stream"):
            # 스트리밍 미지원: 비스트리밍 fallback
            result = self.run_turn(messages, user_id=user_id)
            if StreamEvent:
                yield StreamEvent(type="turn_complete", data=result)
            return

        try:
            self.tool_mgr.reload_if_changed()
            self.trim_history(messages, cfg.max_history)
            tool_schemas = self._tool_schemas()
            tool_round = 0

            while tool_round < cfg.max_tool_rounds:
                if self.on_llm_start:
                    self.on_llm_start()

                # 스트리밍 호출
                stream_gen = self.provider.create_message_stream(
                    messages=messages,
                    system=self.system_prompt,
                    tools=tool_schemas,
                    max_tokens=cfg.max_tokens,
                )

                response = None
                text_parts = []

                for event in stream_gen:
                    if event.type == "text_delta":
                        text_parts.append(event.data)
                        yield event
                    elif event.type in ("tool_use_start", "tool_use_delta", "tool_use_end",
                                        "message_start", "message_end"):
                        yield event
                    elif event.type == "content_complete":
                        response = event.data
                    elif event.type == "error":
                        yield event

                if response is None:
                    break

                if self.on_llm_response:
                    self.on_llm_response(response)

                # 사용량 추적
                inp = response.usage.input_tokens
                out = response.usage.output_tokens
                self._track_cost(inp, out, result, user_id=user_id)
                result.stop_reason = response.stop_reason

                # max_tokens 처리
                if response.stop_reason == "max_tokens":
                    messages.append({"role": "assistant", "content": response.content})
                    error_results = self._max_tokens_error_results(response.content)
                    if error_results:
                        messages.append({"role": "user", "content": error_results})
                        tool_round += 1
                        continue
                    break

                # 도구 호출 확인
                tool_uses = [b for b in response.content if b.type == "tool_use"]

                if not tool_uses:
                    messages.append({"role": "assistant", "content": response.content})
                    result.text = "".join(text_parts)
                    break

                # 도구 실행
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []

                for tool_use in tool_uses:
                    tool_name = tool_use.name

                    if tool_name in self.restricted_tools:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Error: '{tool_name}' 도구는 사용할 수 없습니다. (보안 제한)",
                            "is_error": True,
                        })
                        continue

                    fn = self.tool_mgr.functions.get(tool_name)
                    if not fn:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Error: 알 수 없는 도구: {tool_name}",
                        })
                        continue

                    if self.on_tool_start:
                        self.on_tool_start(tool_name, tool_use.input)

                    try:
                        schema = self._find_schema(tool_name)
                        filtered = _filter_tool_input(tool_use.input, schema) if schema else tool_use.input
                        tool_result = with_timeout(fn, timeout_seconds=cfg.tool_timeout_seconds, **filtered)
                    except _TimeoutError:
                        tool_result = "Error: 도구 실행 타임아웃"
                    except Exception:
                        _logger.exception("도구 실행 실패: %s", tool_name)
                        tool_result = "Error: 도구 실행 실패"

                    if self.on_tool_end:
                        self.on_tool_end(tool_name, tool_result)

                    # 도구 결과 이벤트
                    if StreamEvent:
                        yield StreamEvent(type="tool_result", data={
                            "name": tool_name, "result": str(tool_result)[:200]
                        })

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": self._safe_result(tool_result),
                    })

                messages.append({"role": "user", "content": tool_results})
                tool_round += 1
                text_parts = []  # 다음 라운드 텍스트 초기화

            result.tool_rounds = tool_round
            if tool_round >= cfg.max_tool_rounds:
                result.error = f"도구 호출이 {cfg.max_tool_rounds}회를 초과하여 중단되었습니다."

        except Exception:
            result.error = "요청 처리 중 오류가 발생했습니다."

        if StreamEvent:
            yield StreamEvent(type="turn_complete", data=result)

    # ------------------------------------------------------------------
    # 비동기 스트리밍 메서드
    # ------------------------------------------------------------------

    async def run_turn_stream_async(self, messages: list, *, user_id: str = "default"):
        """비동기 스트리밍 대화 턴. StreamEvent를 async yield합니다.

        사용 패턴::

            async for event in engine.run_turn_stream_async(messages):
                if event.type == "text_delta":
                    await ws.send(json.dumps({"type": "stream_delta", "text": event.data}))
                elif event.type == "turn_complete":
                    result = event.data
        """
        # 비동기 스트리밍은 동기 스트리밍을 asyncio.to_thread로 래핑
        # (프로바이더들이 동기 제너레이터이므로)
        cfg = get_config()
        result = TurnResult()

        if not self.provider or not hasattr(self.provider, "create_message_stream"):
            result = await self.run_turn_async(messages, user_id=user_id)
            if StreamEvent:
                yield StreamEvent(type="turn_complete", data=result)
            return

        try:
            self.tool_mgr.reload_if_changed()
            self.trim_history(messages, cfg.max_history)
            tool_schemas = self._tool_schemas()
            tool_round = 0

            while tool_round < cfg.max_tool_rounds:
                if self.on_llm_start:
                    self.on_llm_start()

                # 동기 스트리밍 제너레이터를 비동기로 실행
                stream_gen = await asyncio.to_thread(
                    self.provider.create_message_stream,
                    messages=messages,
                    system=self.system_prompt,
                    tools=tool_schemas,
                    max_tokens=cfg.max_tokens,
                )

                response = None
                text_parts = []

                for event in stream_gen:
                    if event.type == "text_delta":
                        text_parts.append(event.data)
                        yield event
                    elif event.type in ("tool_use_start", "tool_use_delta", "tool_use_end",
                                        "message_start", "message_end"):
                        yield event
                    elif event.type == "content_complete":
                        response = event.data
                    elif event.type == "error":
                        yield event

                if response is None:
                    break

                if self.on_llm_response:
                    self.on_llm_response(response)

                inp = response.usage.input_tokens
                out = response.usage.output_tokens
                self._track_cost(inp, out, result, user_id=user_id)
                result.stop_reason = response.stop_reason

                if response.stop_reason == "max_tokens":
                    messages.append({"role": "assistant", "content": response.content})
                    error_results = self._max_tokens_error_results(response.content)
                    if error_results:
                        messages.append({"role": "user", "content": error_results})
                        tool_round += 1
                        continue
                    break

                tool_uses = [b for b in response.content if b.type == "tool_use"]

                if not tool_uses:
                    messages.append({"role": "assistant", "content": response.content})
                    result.text = "".join(text_parts)
                    break

                messages.append({"role": "assistant", "content": response.content})
                tool_results = []

                for tool_use in tool_uses:
                    tool_name = tool_use.name

                    if tool_name in self.restricted_tools:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Error: '{tool_name}' 도구는 사용할 수 없습니다. (보안 제한)",
                            "is_error": True,
                        })
                        continue

                    fn_tool = self.tool_mgr.functions.get(tool_name)
                    if not fn_tool:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Error: 알 수 없는 도구: {tool_name}",
                        })
                        continue

                    if self.on_tool_start:
                        self.on_tool_start(tool_name, tool_use.input)

                    try:
                        schema = self._find_schema(tool_name)
                        filtered = _filter_tool_input(tool_use.input, schema) if schema else tool_use.input
                        tool_result = await with_timeout_async(
                            fn_tool, timeout_seconds=cfg.tool_timeout_seconds, **filtered
                        )
                    except _TimeoutError:
                        tool_result = "Error: 도구 실행 타임아웃"
                    except Exception:
                        _logger.exception("도구 실행 실패: %s", tool_name)
                        tool_result = "Error: 도구 실행 실패"

                    if self.on_tool_end:
                        self.on_tool_end(tool_name, tool_result)

                    if StreamEvent:
                        yield StreamEvent(type="tool_result", data={
                            "name": tool_name, "result": str(tool_result)[:200]
                        })

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": self._safe_result(tool_result),
                    })

                messages.append({"role": "user", "content": tool_results})
                tool_round += 1
                text_parts = []

            result.tool_rounds = tool_round
            if tool_round >= cfg.max_tool_rounds:
                result.error = f"도구 호출이 {cfg.max_tool_rounds}회를 초과하여 중단되었습니다."

        except Exception:
            result.error = "요청 처리 중 오류가 발생했습니다."

        if StreamEvent:
            yield StreamEvent(type="turn_complete", data=result)

    # ------------------------------------------------------------------
    # 비동기 메서드 (ws_server, telegram, discord, slack용)
    # ------------------------------------------------------------------

    async def run_turn_async(self, messages: list, *, user_id: str = "default") -> TurnResult:
        """비동기 대화 턴 실행. messages를 in-place로 수정합니다."""
        cfg = get_config()
        result = TurnResult()

        try:
            self.tool_mgr.reload_if_changed()
            self.trim_history(messages, cfg.max_history)
            tool_schemas = self._tool_schemas()
            tool_round = 0

            while tool_round < cfg.max_tool_rounds:
                if self.on_llm_start:
                    self.on_llm_start()

                fn = self._make_llm_call(messages, tool_schemas, cfg)
                response = await retry_llm_call_async(
                    fn,
                    max_retries=cfg.llm_retry_count,
                    base_delay=cfg.llm_retry_base_delay,
                    max_delay=cfg.llm_retry_max_delay,
                )

                if self.on_llm_response:
                    self.on_llm_response(response)

                # 사용량 추적
                inp = response.usage.input_tokens
                out = response.usage.output_tokens
                self._track_cost(inp, out, result, user_id=user_id)
                result.stop_reason = response.stop_reason

                # max_tokens 처리
                if response.stop_reason == "max_tokens":
                    messages.append({"role": "assistant", "content": response.content})
                    error_results = self._max_tokens_error_results(response.content)
                    if error_results:
                        messages.append({"role": "user", "content": error_results})
                        tool_round += 1
                        continue
                    break

                # 도구 호출 확인
                tool_uses = [b for b in response.content if b.type == "tool_use"]

                if not tool_uses:
                    messages.append({"role": "assistant", "content": response.content})
                    result.text = self._extract_text(response)
                    break

                # 도구 실행
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []

                for tool_use in tool_uses:
                    tool_name = tool_use.name

                    # 제한된 도구 차단
                    if tool_name in self.restricted_tools:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Error: '{tool_name}' 도구는 사용할 수 없습니다. (보안 제한)",
                            "is_error": True,
                        })
                        continue

                    fn_tool = self.tool_mgr.functions.get(tool_name)
                    if not fn_tool:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Error: 알 수 없는 도구: {tool_name}",
                        })
                        continue

                    if self.on_tool_start:
                        self.on_tool_start(tool_name, tool_use.input)

                    try:
                        schema = self._find_schema(tool_name)
                        filtered = _filter_tool_input(tool_use.input, schema) if schema else tool_use.input
                        tool_result = await with_timeout_async(
                            fn_tool, timeout_seconds=cfg.tool_timeout_seconds, **filtered
                        )
                    except _TimeoutError:
                        tool_result = "Error: 도구 실행 타임아웃"
                    except Exception:
                        _logger.exception("도구 실행 실패: %s", tool_name)
                        tool_result = "Error: 도구 실행 실패"

                    if self.on_tool_end:
                        self.on_tool_end(tool_name, tool_result)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": self._safe_result(tool_result),
                    })

                messages.append({"role": "user", "content": tool_results})
                tool_round += 1

            result.tool_rounds = tool_round
            if tool_round >= cfg.max_tool_rounds:
                result.error = f"도구 호출이 {cfg.max_tool_rounds}회를 초과하여 중단되었습니다."

        except Exception:
            result.error = "요청 처리 중 오류가 발생했습니다."

        return result
