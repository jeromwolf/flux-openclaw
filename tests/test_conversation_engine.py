"""ConversationEngine 및 TurnResult 테스트"""
import os
import sys
import asyncio
import pytest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from openclaw.llm_provider import TextBlock, ToolUseBlock, Usage, LLMResponse
from openclaw.conversation_engine import ConversationEngine, TurnResult


# ============================================================
# 헬퍼
# ============================================================

def _make_cfg():
    """테스트용 Config mock 생성"""
    cfg = MagicMock()
    cfg.max_history = 50
    cfg.max_tool_rounds = 10
    cfg.max_tokens = 4096
    cfg.default_model = "claude-sonnet-4-20250514"
    cfg.llm_retry_count = 3
    cfg.llm_retry_base_delay = 1.0
    cfg.llm_retry_max_delay = 16.0
    cfg.tool_timeout_seconds = 30.0
    return cfg


def _make_response(content=None, stop_reason="end_turn", input_tokens=10, output_tokens=5):
    """테스트용 LLMResponse 생성"""
    return LLMResponse(
        content=content or [TextBlock(text="Hello")],
        stop_reason=stop_reason,
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _make_engine(restricted_tools=None, on_llm_start=None, on_tool_start=None,
                 on_tool_end=None, on_llm_response=None):
    """테스트용 ConversationEngine 생성"""
    provider = MagicMock()
    tool_mgr = MagicMock()
    tool_mgr.schemas = [
        {"name": "tool_a", "input_schema": {"type": "object", "properties": {"x": {"type": "string"}}}},
        {"name": "tool_b", "input_schema": {"type": "object", "properties": {"y": {"type": "integer"}}}},
    ]
    tool_mgr.functions = {"tool_a": MagicMock(return_value="result_a"), "tool_b": MagicMock(return_value="result_b")}
    return ConversationEngine(
        provider=provider,
        client=None,
        tool_mgr=tool_mgr,
        system_prompt="You are a test assistant.",
        restricted_tools=restricted_tools,
        on_llm_start=on_llm_start,
        on_tool_start=on_tool_start,
        on_tool_end=on_tool_end,
        on_llm_response=on_llm_response,
    )


# ============================================================
# TurnResult 테스트
# ============================================================

class TestTurnResult:
    """TurnResult 데이터클래스 테스트"""

    def test_defaults(self):
        """모든 기본값 확인"""
        r = TurnResult()
        assert r.text == ""
        assert r.tool_rounds == 0
        assert r.input_tokens == 0
        assert r.output_tokens == 0
        assert r.stop_reason == ""
        assert r.error is None

    def test_custom_values(self):
        """커스텀 값 설정"""
        r = TurnResult(text="hi", tool_rounds=3, input_tokens=100, output_tokens=50,
                       stop_reason="end_turn", error="oops")
        assert r.text == "hi"
        assert r.tool_rounds == 3
        assert r.input_tokens == 100
        assert r.output_tokens == 50
        assert r.stop_reason == "end_turn"
        assert r.error == "oops"


# ============================================================
# 정적/인스턴스 헬퍼 메서드 테스트
# ============================================================

class TestTrimHistory:
    """trim_history 정적 메서드 테스트"""

    def test_empty_list(self):
        """빈 리스트 처리"""
        msgs = []
        ConversationEngine.trim_history(msgs, 10)
        assert msgs == []

    def test_under_limit(self):
        """제한 미만이면 변경 없음"""
        msgs = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        original = list(msgs)
        ConversationEngine.trim_history(msgs, 10)
        assert msgs == original

    def test_over_limit_basic(self):
        """제한 초과 시 잘림"""
        msgs = [{"role": "user", "content": str(i)} for i in range(20)]
        ConversationEngine.trim_history(msgs, 5)
        assert len(msgs) <= 5

    def test_user_first_after_trim(self):
        """트리밍 후 첫 메시지가 user 역할"""
        msgs = [
            {"role": "user", "content": "1"},
            {"role": "assistant", "content": "2"},
            {"role": "assistant", "content": "3"},
            {"role": "user", "content": "4"},
            {"role": "assistant", "content": "5"},
            {"role": "user", "content": "6"},
        ]
        # max_history=3 -> 마지막 3개: assistant, user, user? 아니 -> ["3"(asst), "4"(user), "5"(asst), "6"(user)]? 아님
        # 6개, max_history=3 -> [-3:] = [asst:"5", user:"6"]? 아니 msgs[-3:] = 인덱스 3,4,5
        # msgs[-3:] = [user:"4", asst:"5", user:"6"] -> 이미 user first
        ConversationEngine.trim_history(msgs, 3)
        assert len(msgs) <= 3
        if msgs:
            assert msgs[0]["role"] == "user"

    def test_trim_removes_leading_assistant(self):
        """트리밍 후 앞의 assistant 메시지 제거"""
        msgs = [
            {"role": "assistant", "content": "a0"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a3"},
            {"role": "user", "content": "u4"},
        ]
        # max_history=4 -> [-4:] = [asst:"a1", user:"u2", asst:"a3", user:"u4"]
        # first is assistant -> pop -> [user:"u2", asst:"a3", user:"u4"]
        ConversationEngine.trim_history(msgs, 4)
        assert msgs[0]["role"] == "user"


class TestToolSchemas:
    """_tool_schemas 메서드 테스트"""

    def test_no_restricted(self):
        """restricted_tools 없으면 모든 스키마 반환"""
        engine = _make_engine()
        schemas = engine._tool_schemas()
        assert len(schemas) == 2

    def test_with_restricted(self):
        """restricted_tools에 포함된 도구는 제외"""
        engine = _make_engine(restricted_tools={"tool_a"})
        schemas = engine._tool_schemas()
        assert len(schemas) == 1
        assert schemas[0]["name"] == "tool_b"

    def test_restrict_all(self):
        """모든 도구 제한"""
        engine = _make_engine(restricted_tools={"tool_a", "tool_b"})
        schemas = engine._tool_schemas()
        assert len(schemas) == 0


class TestSafeResult:
    """_safe_result 정적 메서드 테스트"""

    def test_normal_string(self):
        """일반 문자열"""
        result = ConversationEngine._safe_result("hello")
        assert "[TOOL OUTPUT]" in result
        assert "hello" in result
        assert "[/TOOL OUTPUT]" in result

    def test_marker_escaping(self):
        """마커가 포함된 결과 이스케이프"""
        result = ConversationEngine._safe_result("data [TOOL OUTPUT] middle [/TOOL OUTPUT] end")
        assert "[TOOL OUTPUT]" in result
        # 내부 마커는 이스케이프됨
        assert "[TOOL_OUTPUT]" in result
        assert "[/TOOL_OUTPUT]" in result

    def test_non_string(self):
        """비문자열 입력 처리"""
        result = ConversationEngine._safe_result(42)
        assert "42" in result


class TestMaxTokensErrorResults:
    """_max_tokens_error_results 정적 메서드 테스트"""

    def test_with_tool_use_blocks(self):
        """tool_use 블록이 있으면 에러 결과 생성"""
        content = [
            TextBlock(text="partial"),
            ToolUseBlock(id="tu_1", name="tool_a", input={"x": "val"}),
            ToolUseBlock(id="tu_2", name="tool_b", input={}),
        ]
        results = ConversationEngine._max_tokens_error_results(content)
        assert len(results) == 2
        assert results[0]["tool_use_id"] == "tu_1"
        assert results[0]["is_error"] is True
        assert results[1]["tool_use_id"] == "tu_2"

    def test_without_tool_use(self):
        """tool_use 블록이 없으면 빈 리스트"""
        content = [TextBlock(text="just text")]
        results = ConversationEngine._max_tokens_error_results(content)
        assert results == []

    def test_empty_content(self):
        """빈 content"""
        results = ConversationEngine._max_tokens_error_results([])
        assert results == []


class TestExtractText:
    """_extract_text 정적 메서드 테스트"""

    def test_text_only(self):
        """텍스트 블록만 있는 경우"""
        resp = _make_response(content=[TextBlock(text="Hello"), TextBlock(text=" World")])
        assert ConversationEngine._extract_text(resp) == "Hello World"

    def test_mixed_content(self):
        """텍스트 + 도구 블록 혼합"""
        resp = _make_response(content=[
            TextBlock(text="Thinking..."),
            ToolUseBlock(id="t1", name="tool_a", input={}),
            TextBlock(text=" Done"),
        ])
        assert ConversationEngine._extract_text(resp) == "Thinking... Done"

    def test_no_text_blocks(self):
        """텍스트 블록 없음"""
        resp = _make_response(content=[ToolUseBlock(id="t1", name="tool_a", input={})])
        assert ConversationEngine._extract_text(resp) == ""


# ============================================================
# run_turn 동기 테스트
# ============================================================

class TestRunTurn:
    """run_turn 동기 메서드 테스트"""

    @patch("openclaw.conversation_engine.increment_usage")
    @patch("openclaw.conversation_engine.retry_llm_call", side_effect=lambda fn, **kw: fn())
    @patch("openclaw.conversation_engine.get_config")
    def test_normal_text_response(self, mock_config, mock_retry, mock_usage):
        """일반 텍스트 응답"""
        mock_config.return_value = _make_cfg()
        engine = _make_engine()
        response = _make_response(content=[TextBlock(text="Hi there")])
        engine.provider.create_message.return_value = response

        messages = [{"role": "user", "content": "hello"}]
        result = engine.run_turn(messages)

        assert result.text == "Hi there"
        assert result.stop_reason == "end_turn"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.error is None
        assert result.tool_rounds == 0
        # messages에 assistant 메시지 추가됨
        assert len(messages) == 2
        assert messages[1]["role"] == "assistant"

    @patch("openclaw.conversation_engine.with_timeout", side_effect=lambda fn, **kw: fn(**{k: v for k, v in kw.items() if k != "timeout_seconds"}))
    @patch("openclaw.conversation_engine.increment_usage")
    @patch("openclaw.conversation_engine.retry_llm_call", side_effect=lambda fn, **kw: fn())
    @patch("openclaw.conversation_engine.get_config")
    def test_tool_use_single_round(self, mock_config, mock_retry, mock_usage, mock_timeout):
        """단일 도구 사용 라운드"""
        mock_config.return_value = _make_cfg()
        engine = _make_engine()

        tool_response = _make_response(
            content=[ToolUseBlock(id="tu_1", name="tool_a", input={"x": "val"})],
            stop_reason="tool_use",
        )
        final_response = _make_response(content=[TextBlock(text="Tool done")])

        engine.provider.create_message.side_effect = [tool_response, final_response]

        messages = [{"role": "user", "content": "use a tool"}]
        result = engine.run_turn(messages)

        assert result.text == "Tool done"
        assert result.tool_rounds == 1
        assert result.input_tokens == 20  # 10 + 10
        assert result.output_tokens == 10  # 5 + 5

    @patch("openclaw.conversation_engine.with_timeout", side_effect=lambda fn, **kw: fn(**{k: v for k, v in kw.items() if k != "timeout_seconds"}))
    @patch("openclaw.conversation_engine.increment_usage")
    @patch("openclaw.conversation_engine.retry_llm_call", side_effect=lambda fn, **kw: fn())
    @patch("openclaw.conversation_engine.get_config")
    def test_restricted_tool_blocked(self, mock_config, mock_retry, mock_usage, mock_timeout):
        """제한된 도구가 차단됨"""
        mock_config.return_value = _make_cfg()
        engine = _make_engine(restricted_tools={"tool_a"})

        tool_response = _make_response(
            content=[ToolUseBlock(id="tu_1", name="tool_a", input={"x": "val"})],
            stop_reason="tool_use",
        )
        final_response = _make_response(content=[TextBlock(text="OK")])
        engine.provider.create_message.side_effect = [tool_response, final_response]

        messages = [{"role": "user", "content": "use tool_a"}]
        result = engine.run_turn(messages)

        # tool_results에 에러가 들어있는지 확인
        user_msg = messages[2]  # user -> assistant -> user(tool_results)
        assert user_msg["role"] == "user"
        tool_results = user_msg["content"]
        assert any("보안 제한" in tr["content"] for tr in tool_results)
        assert any(tr.get("is_error") for tr in tool_results)

    @patch("openclaw.conversation_engine.increment_usage")
    @patch("openclaw.conversation_engine.retry_llm_call", side_effect=lambda fn, **kw: fn())
    @patch("openclaw.conversation_engine.get_config")
    def test_unknown_tool(self, mock_config, mock_retry, mock_usage):
        """알 수 없는 도구 처리"""
        mock_config.return_value = _make_cfg()
        engine = _make_engine()
        engine.tool_mgr.functions = {}  # 등록된 함수 없음

        tool_response = _make_response(
            content=[ToolUseBlock(id="tu_1", name="unknown_tool", input={})],
            stop_reason="tool_use",
        )
        final_response = _make_response(content=[TextBlock(text="Sorry")])
        engine.provider.create_message.side_effect = [tool_response, final_response]

        messages = [{"role": "user", "content": "do something"}]
        result = engine.run_turn(messages)

        # tool_results에 알 수 없는 도구 에러
        user_msg = messages[2]
        tool_results = user_msg["content"]
        assert any("알 수 없는 도구" in tr["content"] for tr in tool_results)

    @patch("openclaw.conversation_engine.increment_usage")
    @patch("openclaw.conversation_engine.retry_llm_call", side_effect=lambda fn, **kw: fn())
    @patch("openclaw.conversation_engine.get_config")
    def test_max_tokens_with_tool_use(self, mock_config, mock_retry, mock_usage):
        """max_tokens + tool_use 블록: 에러 결과 후 계속"""
        mock_config.return_value = _make_cfg()
        engine = _make_engine()

        truncated_response = _make_response(
            content=[ToolUseBlock(id="tu_1", name="tool_a", input={})],
            stop_reason="max_tokens",
        )
        final_response = _make_response(content=[TextBlock(text="Retried")])
        engine.provider.create_message.side_effect = [truncated_response, final_response]

        messages = [{"role": "user", "content": "test"}]
        result = engine.run_turn(messages)

        assert result.text == "Retried"
        assert result.tool_rounds == 1

    @patch("openclaw.conversation_engine.increment_usage")
    @patch("openclaw.conversation_engine.retry_llm_call", side_effect=lambda fn, **kw: fn())
    @patch("openclaw.conversation_engine.get_config")
    def test_max_tokens_without_tool_use(self, mock_config, mock_retry, mock_usage):
        """max_tokens + 텍스트만: 바로 중단"""
        mock_config.return_value = _make_cfg()
        engine = _make_engine()

        truncated_response = _make_response(
            content=[TextBlock(text="Partial")],
            stop_reason="max_tokens",
        )
        engine.provider.create_message.return_value = truncated_response

        messages = [{"role": "user", "content": "test"}]
        result = engine.run_turn(messages)

        assert result.stop_reason == "max_tokens"
        assert result.text == ""  # max_tokens -> break, no extract
        assert result.tool_rounds == 0

    @patch("openclaw.conversation_engine.increment_usage")
    @patch("openclaw.conversation_engine.retry_llm_call", side_effect=lambda fn, **kw: fn())
    @patch("openclaw.conversation_engine.get_config")
    def test_tool_round_limit(self, mock_config, mock_retry, mock_usage):
        """도구 라운드 제한 초과"""
        cfg = _make_cfg()
        cfg.max_tool_rounds = 2
        mock_config.return_value = cfg
        engine = _make_engine()

        # 항상 tool_use 응답을 반환하여 무한 루프 유도
        tool_response = _make_response(
            content=[ToolUseBlock(id="tu_1", name="tool_a", input={"x": "v"})],
            stop_reason="tool_use",
        )
        engine.provider.create_message.return_value = tool_response
        engine.tool_mgr.functions = {"tool_a": MagicMock(return_value="ok")}

        messages = [{"role": "user", "content": "loop"}]

        with patch("openclaw.conversation_engine.with_timeout", side_effect=lambda fn, **kw: fn(**{k: v for k, v in kw.items() if k != "timeout_seconds"})):
            result = engine.run_turn(messages)

        assert result.tool_rounds == 2
        assert result.error is not None
        assert "2" in result.error

    @patch("openclaw.conversation_engine.increment_usage")
    @patch("openclaw.conversation_engine.retry_llm_call", side_effect=lambda fn, **kw: fn())
    @patch("openclaw.conversation_engine.get_config")
    def test_llm_exception(self, mock_config, mock_retry, mock_usage):
        """LLM 호출 예외 처리"""
        mock_config.return_value = _make_cfg()
        engine = _make_engine()
        engine.provider.create_message.side_effect = RuntimeError("API Error")
        # retry_llm_call은 fn()을 호출하므로 예외가 전파됨
        # 하지만 run_turn에서 try/except로 잡힘

        messages = [{"role": "user", "content": "fail"}]
        result = engine.run_turn(messages)

        assert result.error == "요청 처리 중 오류가 발생했습니다."

    @patch("openclaw.conversation_engine.with_timeout", side_effect=lambda fn, **kw: (_ for _ in ()).throw(__import__("openclaw.resilience", fromlist=["_TimeoutError"])._TimeoutError("timeout")))
    @patch("openclaw.conversation_engine.increment_usage")
    @patch("openclaw.conversation_engine.retry_llm_call", side_effect=lambda fn, **kw: fn())
    @patch("openclaw.conversation_engine.get_config")
    def test_tool_timeout(self, mock_config, mock_retry, mock_usage, mock_timeout):
        """도구 실행 타임아웃"""
        mock_config.return_value = _make_cfg()
        engine = _make_engine()

        tool_response = _make_response(
            content=[ToolUseBlock(id="tu_1", name="tool_a", input={"x": "val"})],
            stop_reason="tool_use",
        )
        final_response = _make_response(content=[TextBlock(text="After timeout")])
        engine.provider.create_message.side_effect = [tool_response, final_response]

        messages = [{"role": "user", "content": "use tool"}]
        result = engine.run_turn(messages)

        # 타임아웃이지만 루프는 계속 → 결과에 타임아웃 메시지
        user_msg = messages[2]
        tool_results = user_msg["content"]
        assert any("타임아웃" in tr["content"] for tr in tool_results)

    @patch("openclaw.conversation_engine.with_timeout", side_effect=lambda fn, **kw: fn(**{k: v for k, v in kw.items() if k != "timeout_seconds"}))
    @patch("openclaw.conversation_engine.increment_usage")
    @patch("openclaw.conversation_engine.retry_llm_call", side_effect=lambda fn, **kw: fn())
    @patch("openclaw.conversation_engine.get_config")
    def test_callbacks_called(self, mock_config, mock_retry, mock_usage, mock_timeout):
        """콜백 호출 확인"""
        mock_config.return_value = _make_cfg()
        on_llm_start = MagicMock()
        on_tool_start = MagicMock()
        on_tool_end = MagicMock()
        on_llm_response = MagicMock()

        engine = _make_engine(
            on_llm_start=on_llm_start,
            on_tool_start=on_tool_start,
            on_tool_end=on_tool_end,
            on_llm_response=on_llm_response,
        )

        tool_response = _make_response(
            content=[ToolUseBlock(id="tu_1", name="tool_a", input={"x": "val"})],
            stop_reason="tool_use",
        )
        final_response = _make_response(content=[TextBlock(text="Done")])
        engine.provider.create_message.side_effect = [tool_response, final_response]

        messages = [{"role": "user", "content": "go"}]
        engine.run_turn(messages)

        assert on_llm_start.call_count == 2  # 2 LLM calls
        assert on_llm_response.call_count == 2
        on_tool_start.assert_called_once_with("tool_a", {"x": "val"})
        on_tool_end.assert_called_once()

    @patch("openclaw.conversation_engine.increment_usage")
    @patch("openclaw.conversation_engine.retry_llm_call", side_effect=lambda fn, **kw: fn())
    @patch("openclaw.conversation_engine.get_config")
    def test_usage_accumulated(self, mock_config, mock_retry, mock_usage):
        """토큰 사용량 누적"""
        mock_config.return_value = _make_cfg()
        engine = _make_engine()
        resp = _make_response(input_tokens=100, output_tokens=50)
        engine.provider.create_message.return_value = resp

        messages = [{"role": "user", "content": "hi"}]
        result = engine.run_turn(messages)

        assert result.input_tokens == 100
        assert result.output_tokens == 50
        mock_usage.assert_called_once_with(100, 50, cost_usd=0.0)

    @patch("openclaw.conversation_engine.with_timeout", side_effect=lambda fn, **kw: (_ for _ in ()).throw(ValueError("tool crash")))
    @patch("openclaw.conversation_engine.increment_usage")
    @patch("openclaw.conversation_engine.retry_llm_call", side_effect=lambda fn, **kw: fn())
    @patch("openclaw.conversation_engine.get_config")
    def test_tool_generic_exception(self, mock_config, mock_retry, mock_usage, mock_timeout):
        """도구 실행 일반 예외 처리"""
        mock_config.return_value = _make_cfg()
        engine = _make_engine()

        tool_response = _make_response(
            content=[ToolUseBlock(id="tu_1", name="tool_a", input={"x": "val"})],
            stop_reason="tool_use",
        )
        final_response = _make_response(content=[TextBlock(text="Recovered")])
        engine.provider.create_message.side_effect = [tool_response, final_response]

        messages = [{"role": "user", "content": "use tool"}]
        result = engine.run_turn(messages)

        user_msg = messages[2]
        tool_results = user_msg["content"]
        assert any("실패" in tr["content"] for tr in tool_results)


# ============================================================
# run_turn_async 비동기 테스트
# ============================================================

class TestRunTurnAsync:
    """run_turn_async 비동기 메서드 테스트"""

    @patch("openclaw.conversation_engine.increment_usage")
    @patch("openclaw.conversation_engine.retry_llm_call_async")
    @patch("openclaw.conversation_engine.get_config")
    def test_async_normal_response(self, mock_config, mock_retry_async, mock_usage):
        """비동기 일반 텍스트 응답"""
        mock_config.return_value = _make_cfg()
        engine = _make_engine()
        response = _make_response(content=[TextBlock(text="Async hello")])

        async def fake_retry(fn, **kw):
            return response
        mock_retry_async.side_effect = fake_retry

        messages = [{"role": "user", "content": "async test"}]
        result = asyncio.run(engine.run_turn_async(messages))

        assert result.text == "Async hello"
        assert result.error is None
        assert result.tool_rounds == 0

    @patch("openclaw.conversation_engine.with_timeout_async")
    @patch("openclaw.conversation_engine.increment_usage")
    @patch("openclaw.conversation_engine.retry_llm_call_async")
    @patch("openclaw.conversation_engine.get_config")
    def test_async_tool_use(self, mock_config, mock_retry_async, mock_usage, mock_timeout_async):
        """비동기 도구 사용 라운드"""
        mock_config.return_value = _make_cfg()
        engine = _make_engine()

        tool_response = _make_response(
            content=[ToolUseBlock(id="tu_1", name="tool_a", input={"x": "v"})],
            stop_reason="tool_use",
        )
        final_response = _make_response(content=[TextBlock(text="Async done")])

        call_count = {"n": 0}

        async def fake_retry(fn, **kw):
            r = tool_response if call_count["n"] == 0 else final_response
            call_count["n"] += 1
            return r
        mock_retry_async.side_effect = fake_retry

        async def fake_timeout(fn, **kw):
            filtered = {k: v for k, v in kw.items() if k != "timeout_seconds"}
            return fn(**filtered)
        mock_timeout_async.side_effect = fake_timeout

        messages = [{"role": "user", "content": "async tool"}]
        result = asyncio.run(engine.run_turn_async(messages))

        assert result.text == "Async done"
        assert result.tool_rounds == 1

    @patch("openclaw.conversation_engine.increment_usage")
    @patch("openclaw.conversation_engine.retry_llm_call_async")
    @patch("openclaw.conversation_engine.get_config")
    def test_async_llm_exception(self, mock_config, mock_retry_async, mock_usage):
        """비동기 LLM 예외 처리"""
        mock_config.return_value = _make_cfg()
        engine = _make_engine()

        async def fake_retry(fn, **kw):
            raise RuntimeError("Async API error")
        mock_retry_async.side_effect = fake_retry

        messages = [{"role": "user", "content": "fail async"}]
        result = asyncio.run(engine.run_turn_async(messages))

        assert result.error == "요청 처리 중 오류가 발생했습니다."

    @patch("openclaw.conversation_engine.with_timeout_async")
    @patch("openclaw.conversation_engine.increment_usage")
    @patch("openclaw.conversation_engine.retry_llm_call_async")
    @patch("openclaw.conversation_engine.get_config")
    def test_async_restricted_tool(self, mock_config, mock_retry_async, mock_usage, mock_timeout_async):
        """비동기 제한된 도구 차단"""
        mock_config.return_value = _make_cfg()
        engine = _make_engine(restricted_tools={"tool_a"})

        tool_response = _make_response(
            content=[ToolUseBlock(id="tu_1", name="tool_a", input={"x": "v"})],
            stop_reason="tool_use",
        )
        final_response = _make_response(content=[TextBlock(text="Blocked")])

        call_count = {"n": 0}

        async def fake_retry(fn, **kw):
            r = tool_response if call_count["n"] == 0 else final_response
            call_count["n"] += 1
            return r
        mock_retry_async.side_effect = fake_retry

        messages = [{"role": "user", "content": "async restricted"}]
        result = asyncio.run(engine.run_turn_async(messages))

        user_msg = messages[2]
        tool_results = user_msg["content"]
        assert any("보안 제한" in tr["content"] for tr in tool_results)


# ============================================================
# _make_llm_call 테스트
# ============================================================

class TestMakeLlmCall:
    """_make_llm_call 메서드 테스트"""

    def test_uses_provider(self):
        """provider가 있으면 provider.create_message 사용"""
        engine = _make_engine()
        cfg = _make_cfg()
        fn = engine._make_llm_call([], [], cfg)
        fn()
        engine.provider.create_message.assert_called_once()

    def test_uses_client(self):
        """provider 없으면 client.messages.create 사용"""
        engine = _make_engine()
        engine.provider = None
        engine.client = MagicMock()
        cfg = _make_cfg()
        fn = engine._make_llm_call([], [], cfg)
        fn()
        engine.client.messages.create.assert_called_once()


# ============================================================
# _find_schema 테스트
# ============================================================

class TestFindSchema:
    """_find_schema 메서드 테스트"""

    def test_found(self):
        """이름으로 스키마 검색 성공"""
        engine = _make_engine()
        schema = engine._find_schema("tool_a")
        assert schema is not None
        assert schema["name"] == "tool_a"

    def test_not_found(self):
        """이름으로 스키마 검색 실패"""
        engine = _make_engine()
        schema = engine._find_schema("nonexistent")
        assert schema is None
