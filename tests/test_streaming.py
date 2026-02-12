"""
flux-openclaw 스트리밍 테스트 스위트

StreamEvent, BaseLLMProvider.create_message_stream(), ConversationEngine.run_turn_stream()의
스트리밍 기능을 검증합니다.

테스트 대상:
1. StreamEvent dataclass 구조
2. BaseLLMProvider의 fallback 스트리밍 (create_message 결과 분해)
3. ConversationEngine의 동기/비동기 스트리밍 제너레이터
"""

import sys
import os
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from dataclasses import dataclass

# 경로 설정
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openclaw.llm_provider import StreamEvent, TextBlock, ToolUseBlock, Usage, LLMResponse, BaseLLMProvider
from openclaw.conversation_engine import ConversationEngine, TurnResult


# =============================================================================
# StreamEvent 구조 테스트
# =============================================================================

def test_stream_event_defaults():
    """StreamEvent의 기본값 테스트"""
    event = StreamEvent(type="test")
    assert event.type == "test"
    assert event.data is None


def test_stream_event_text_delta():
    """StreamEvent text_delta 타입 테스트"""
    event = StreamEvent(type="text_delta", data="Hello")
    assert event.type == "text_delta"
    assert event.data == "Hello"


def test_stream_event_tool_use_start():
    """StreamEvent tool_use_start 타입 테스트"""
    event = StreamEvent(type="tool_use_start", data={"id": "tool_123", "name": "test_tool"})
    assert event.type == "tool_use_start"
    assert event.data["id"] == "tool_123"
    assert event.data["name"] == "test_tool"


# =============================================================================
# BaseLLMProvider fallback 스트리밍 테스트
# =============================================================================

class MockProvider(BaseLLMProvider):
    """테스트용 Mock 프로바이더"""
    PROVIDER_NAME = "mock"
    DEFAULT_MODEL = "mock-model"

    def __init__(self, api_key="test_key", model=None):
        super().__init__(api_key, model)
        self.create_message = MagicMock()

    def convert_tools(self, anthropic_tools):
        return anthropic_tools

    def convert_messages(self, anthropic_messages, system=""):
        return anthropic_messages


def test_base_provider_stream_text_only():
    """BaseLLMProvider 텍스트 전용 응답 스트리밍 테스트"""
    provider = MockProvider()
    response = LLMResponse(
        content=[TextBlock(text="Hello World")],
        stop_reason="end_turn",
        usage=Usage(10, 5)
    )
    provider.create_message.return_value = response

    events = list(provider.create_message_stream(messages=[], system="", tools=None))

    # 이벤트 시퀀스 검증
    assert events[0].type == "message_start"
    assert events[0].data["model"] == "mock-model"

    assert events[1].type == "text_delta"
    assert events[1].data == "Hello World"

    assert events[2].type == "message_end"
    assert events[2].data["stop_reason"] == "end_turn"
    assert events[2].data["usage"].input_tokens == 10
    assert events[2].data["usage"].output_tokens == 5

    assert events[3].type == "content_complete"
    assert events[3].data.content[0].text == "Hello World"


def test_base_provider_stream_with_tool_use():
    """BaseLLMProvider 도구 사용 응답 스트리밍 테스트"""
    provider = MockProvider()
    response = LLMResponse(
        content=[
            TextBlock(text="Let me help"),
            ToolUseBlock(id="tool_456", name="search", input={"query": "test"})
        ],
        stop_reason="tool_use",
        usage=Usage(15, 8)
    )
    provider.create_message.return_value = response

    events = list(provider.create_message_stream(messages=[]))

    # text_delta 확인
    text_events = [e for e in events if e.type == "text_delta"]
    assert len(text_events) == 1
    assert text_events[0].data == "Let me help"

    # tool_use_start 확인
    tool_start_events = [e for e in events if e.type == "tool_use_start"]
    assert len(tool_start_events) == 1
    assert tool_start_events[0].data["id"] == "tool_456"
    assert tool_start_events[0].data["name"] == "search"

    # tool_use_end 확인
    tool_end_events = [e for e in events if e.type == "tool_use_end"]
    assert len(tool_end_events) == 1
    assert tool_end_events[0].data["input"]["query"] == "test"


def test_base_provider_stream_yields_content_complete():
    """BaseLLMProvider content_complete 이벤트 생성 확인"""
    provider = MockProvider()
    response = LLMResponse(
        content=[TextBlock(text="Done")],
        stop_reason="end_turn",
        usage=Usage(5, 3)
    )
    provider.create_message.return_value = response

    events = list(provider.create_message_stream(messages=[]))

    complete_events = [e for e in events if e.type == "content_complete"]
    assert len(complete_events) == 1
    assert complete_events[0].data == response


def test_base_provider_stream_yields_message_start_and_end():
    """BaseLLMProvider message_start 및 message_end 이벤트 확인"""
    provider = MockProvider()
    response = LLMResponse(
        content=[TextBlock(text="Test")],
        stop_reason="end_turn",
        usage=Usage(1, 1)
    )
    provider.create_message.return_value = response

    events = list(provider.create_message_stream(messages=[]))

    # message_start가 첫 번째 이벤트
    assert events[0].type == "message_start"

    # message_end가 content_complete 직전
    message_end_idx = next(i for i, e in enumerate(events) if e.type == "message_end")
    content_complete_idx = next(i for i, e in enumerate(events) if e.type == "content_complete")
    assert message_end_idx < content_complete_idx


# =============================================================================
# ConversationEngine.run_turn_stream 테스트
# =============================================================================

@pytest.fixture
def mock_tool_mgr():
    """Mock ToolManager 픽스처"""
    mgr = MagicMock()
    mgr.schemas = []
    mgr.functions = {}
    mgr.reload_if_changed = MagicMock()
    return mgr


@pytest.fixture
def mock_config():
    """Mock Config 픽스처"""
    config = MagicMock()
    config.max_history = 100
    config.max_tool_rounds = 5
    config.max_tokens = 4096
    config.tool_timeout_seconds = 30
    return config


@patch("openclaw.conversation_engine.get_config")
@patch("openclaw.conversation_engine.increment_usage")
def test_stream_text_only_response(mock_increment, mock_get_config, mock_tool_mgr, mock_config):
    """ConversationEngine 텍스트 전용 응답 스트리밍 테스트"""
    mock_get_config.return_value = mock_config

    provider = MockProvider()

    def mock_stream(*args, **kwargs):
        yield StreamEvent(type="message_start", data={"model": "test"})
        yield StreamEvent(type="text_delta", data="Hello")
        yield StreamEvent(type="text_delta", data=" World")
        yield StreamEvent(type="message_end", data={"stop_reason": "end_turn", "usage": Usage(10, 5)})
        yield StreamEvent(type="content_complete", data=LLMResponse(
            content=[TextBlock(text="Hello World")],
            stop_reason="end_turn",
            usage=Usage(10, 5)
        ))

    provider.create_message_stream = mock_stream

    engine = ConversationEngine(
        provider=provider,
        client=None,
        tool_mgr=mock_tool_mgr,
        system_prompt="Test system"
    )

    messages = [{"role": "user", "content": "Hello"}]
    events = list(engine.run_turn_stream(messages))

    # text_delta 이벤트 확인
    text_deltas = [e for e in events if e.type == "text_delta"]
    assert len(text_deltas) == 2
    assert text_deltas[0].data == "Hello"
    assert text_deltas[1].data == " World"

    # turn_complete 이벤트 확인
    turn_complete = [e for e in events if e.type == "turn_complete"]
    assert len(turn_complete) == 1
    result = turn_complete[0].data
    assert isinstance(result, TurnResult)
    assert result.text == "Hello World"
    assert result.input_tokens == 10
    assert result.output_tokens == 5


@patch("openclaw.conversation_engine.get_config")
@patch("openclaw.conversation_engine.increment_usage")
def test_stream_yields_text_deltas(mock_increment, mock_get_config, mock_tool_mgr, mock_config):
    """ConversationEngine이 text_delta를 올바르게 yield하는지 테스트"""
    mock_get_config.return_value = mock_config

    provider = MockProvider()

    def mock_stream(*args, **kwargs):
        yield StreamEvent(type="message_start", data={"model": "test"})
        for char in "ABC":
            yield StreamEvent(type="text_delta", data=char)
        yield StreamEvent(type="message_end", data={"stop_reason": "end_turn", "usage": Usage(5, 3)})
        yield StreamEvent(type="content_complete", data=LLMResponse(
            content=[TextBlock(text="ABC")],
            stop_reason="end_turn",
            usage=Usage(5, 3)
        ))

    provider.create_message_stream = mock_stream

    engine = ConversationEngine(
        provider=provider,
        client=None,
        tool_mgr=mock_tool_mgr,
        system_prompt="Test"
    )

    messages = [{"role": "user", "content": "Test"}]
    events = list(engine.run_turn_stream(messages))

    text_deltas = [e.data for e in events if e.type == "text_delta"]
    assert text_deltas == ["A", "B", "C"]


@patch("openclaw.conversation_engine.get_config")
@patch("openclaw.conversation_engine.increment_usage")
def test_stream_yields_turn_complete(mock_increment, mock_get_config, mock_tool_mgr, mock_config):
    """ConversationEngine이 마지막에 turn_complete를 yield하는지 테스트"""
    mock_get_config.return_value = mock_config

    provider = MockProvider()

    def mock_stream(*args, **kwargs):
        yield StreamEvent(type="message_start", data={"model": "test"})
        yield StreamEvent(type="text_delta", data="Done")
        yield StreamEvent(type="message_end", data={"stop_reason": "end_turn", "usage": Usage(5, 2)})
        yield StreamEvent(type="content_complete", data=LLMResponse(
            content=[TextBlock(text="Done")],
            stop_reason="end_turn",
            usage=Usage(5, 2)
        ))

    provider.create_message_stream = mock_stream

    engine = ConversationEngine(
        provider=provider,
        client=None,
        tool_mgr=mock_tool_mgr,
        system_prompt="Test"
    )

    messages = [{"role": "user", "content": "Test"}]
    events = list(engine.run_turn_stream(messages))

    # 마지막 이벤트가 turn_complete
    assert events[-1].type == "turn_complete"
    assert isinstance(events[-1].data, TurnResult)


@patch("openclaw.conversation_engine.get_config")
def test_stream_fallback_when_no_provider(mock_get_config, mock_tool_mgr, mock_config):
    """ConversationEngine에 provider가 없을 때 fallback 동작 테스트"""
    mock_get_config.return_value = mock_config

    # client only (provider 없음)
    client = MagicMock()
    response = MagicMock()
    response.content = [TextBlock(text="Fallback")]
    response.stop_reason = "end_turn"
    response.usage = Usage(3, 2)
    client.messages.create.return_value = response

    engine = ConversationEngine(
        provider=None,
        client=client,
        tool_mgr=mock_tool_mgr,
        system_prompt="Test"
    )

    with patch("openclaw.conversation_engine.retry_llm_call", return_value=response):
        with patch("openclaw.conversation_engine.increment_usage"):
            messages = [{"role": "user", "content": "Test"}]
            events = list(engine.run_turn_stream(messages))

    # fallback: turn_complete만 반환
    assert len(events) == 1
    assert events[0].type == "turn_complete"
    assert events[0].data.text == "Fallback"


@patch("openclaw.conversation_engine.get_config")
@patch("openclaw.conversation_engine.increment_usage")
@patch("openclaw.conversation_engine.with_timeout")
def test_stream_with_tool_use(mock_timeout, mock_increment, mock_get_config, mock_tool_mgr, mock_config):
    """ConversationEngine 도구 사용 시 스트리밍 테스트 (도구 실행 후 두 번째 스트리밍)"""
    mock_get_config.return_value = mock_config
    mock_timeout.return_value = "Tool result"

    # Tool 설정
    mock_tool_mgr.schemas = [{"name": "test_tool", "description": "Test"}]
    mock_tool_mgr.functions = {"test_tool": MagicMock(return_value="Tool result")}

    provider = MockProvider()

    # 첫 번째 스트림: tool_use 포함
    def first_stream(*args, **kwargs):
        yield StreamEvent(type="message_start", data={"model": "test"})
        yield StreamEvent(type="tool_use_start", data={"id": "t1", "name": "test_tool"})
        yield StreamEvent(type="tool_use_end", data={"id": "t1", "name": "test_tool", "input": {}})
        yield StreamEvent(type="message_end", data={"stop_reason": "tool_use", "usage": Usage(10, 5)})
        yield StreamEvent(type="content_complete", data=LLMResponse(
            content=[ToolUseBlock(id="t1", name="test_tool", input={})],
            stop_reason="tool_use",
            usage=Usage(10, 5)
        ))

    # 두 번째 스트림: 텍스트 응답
    def second_stream(*args, **kwargs):
        yield StreamEvent(type="message_start", data={"model": "test"})
        yield StreamEvent(type="text_delta", data="Result received")
        yield StreamEvent(type="message_end", data={"stop_reason": "end_turn", "usage": Usage(8, 4)})
        yield StreamEvent(type="content_complete", data=LLMResponse(
            content=[TextBlock(text="Result received")],
            stop_reason="end_turn",
            usage=Usage(8, 4)
        ))

    # 두 번 호출에 대응
    stream_iter = iter([first_stream, second_stream])
    provider.create_message_stream = lambda *args, **kwargs: next(stream_iter)(*args, **kwargs)

    engine = ConversationEngine(
        provider=provider,
        client=None,
        tool_mgr=mock_tool_mgr,
        system_prompt="Test"
    )

    messages = [{"role": "user", "content": "Use tool"}]
    events = list(engine.run_turn_stream(messages))

    # tool_use_start, tool_use_end 이벤트 확인
    tool_starts = [e for e in events if e.type == "tool_use_start"]
    tool_ends = [e for e in events if e.type == "tool_use_end"]
    assert len(tool_starts) == 1
    assert len(tool_ends) == 1

    # 두 번째 라운드 텍스트 확인
    text_deltas = [e.data for e in events if e.type == "text_delta"]
    assert "Result received" in text_deltas

    # turn_complete 확인
    turn_complete = [e for e in events if e.type == "turn_complete"]
    assert len(turn_complete) == 1
    assert turn_complete[0].data.tool_rounds == 1


@patch("openclaw.conversation_engine.get_config")
@patch("openclaw.conversation_engine.increment_usage")
def test_stream_cost_tracked(mock_increment, mock_get_config, mock_tool_mgr, mock_config):
    """ConversationEngine 스트리밍 시 비용 추적 확인"""
    mock_get_config.return_value = mock_config

    provider = MockProvider()
    provider.model = "test-model"

    def mock_stream(*args, **kwargs):
        yield StreamEvent(type="message_start", data={"model": "test"})
        yield StreamEvent(type="text_delta", data="Cost test")
        yield StreamEvent(type="message_end", data={"stop_reason": "end_turn", "usage": Usage(20, 10)})
        yield StreamEvent(type="content_complete", data=LLMResponse(
            content=[TextBlock(text="Cost test")],
            stop_reason="end_turn",
            usage=Usage(20, 10)
        ))

    provider.create_message_stream = mock_stream

    engine = ConversationEngine(
        provider=provider,
        client=None,
        tool_mgr=mock_tool_mgr,
        system_prompt="Test"
    )

    messages = [{"role": "user", "content": "Test"}]
    events = list(engine.run_turn_stream(messages))

    result = events[-1].data
    assert result.input_tokens == 20
    assert result.output_tokens == 10
    # increment_usage 호출 확인
    mock_increment.assert_called()


# =============================================================================
# ConversationEngine.run_turn_stream_async 테스트
# =============================================================================

@pytest.mark.asyncio
@patch("openclaw.conversation_engine.get_config")
@patch("openclaw.conversation_engine.increment_usage")
async def test_async_stream_text_response(mock_increment, mock_get_config, mock_tool_mgr, mock_config):
    """ConversationEngine 비동기 스트리밍 텍스트 응답 테스트"""
    mock_get_config.return_value = mock_config

    provider = MockProvider()

    def mock_stream(*args, **kwargs):
        yield StreamEvent(type="message_start", data={"model": "test"})
        yield StreamEvent(type="text_delta", data="Async")
        yield StreamEvent(type="text_delta", data=" Stream")
        yield StreamEvent(type="message_end", data={"stop_reason": "end_turn", "usage": Usage(7, 3)})
        yield StreamEvent(type="content_complete", data=LLMResponse(
            content=[TextBlock(text="Async Stream")],
            stop_reason="end_turn",
            usage=Usage(7, 3)
        ))

    provider.create_message_stream = mock_stream

    engine = ConversationEngine(
        provider=provider,
        client=None,
        tool_mgr=mock_tool_mgr,
        system_prompt="Test"
    )

    messages = [{"role": "user", "content": "Test"}]
    events = []
    async for event in engine.run_turn_stream_async(messages):
        events.append(event)

    text_deltas = [e.data for e in events if e.type == "text_delta"]
    assert text_deltas == ["Async", " Stream"]

    turn_complete = [e for e in events if e.type == "turn_complete"]
    assert len(turn_complete) == 1
    assert turn_complete[0].data.text == "Async Stream"


@pytest.mark.asyncio
@patch("openclaw.conversation_engine.get_config")
@patch("openclaw.conversation_engine.increment_usage")
async def test_async_stream_yields_turn_complete(mock_increment, mock_get_config, mock_tool_mgr, mock_config):
    """ConversationEngine 비동기 스트리밍이 turn_complete를 yield하는지 테스트"""
    mock_get_config.return_value = mock_config

    provider = MockProvider()

    def mock_stream(*args, **kwargs):
        yield StreamEvent(type="message_start", data={"model": "test"})
        yield StreamEvent(type="text_delta", data="Done")
        yield StreamEvent(type="message_end", data={"stop_reason": "end_turn", "usage": Usage(4, 2)})
        yield StreamEvent(type="content_complete", data=LLMResponse(
            content=[TextBlock(text="Done")],
            stop_reason="end_turn",
            usage=Usage(4, 2)
        ))

    provider.create_message_stream = mock_stream

    engine = ConversationEngine(
        provider=provider,
        client=None,
        tool_mgr=mock_tool_mgr,
        system_prompt="Test"
    )

    messages = [{"role": "user", "content": "Test"}]
    events = []
    async for event in engine.run_turn_stream_async(messages):
        events.append(event)

    # 마지막 이벤트가 turn_complete
    assert events[-1].type == "turn_complete"
    result = events[-1].data
    assert isinstance(result, TurnResult)
    assert result.text == "Done"
    assert result.input_tokens == 4
    assert result.output_tokens == 2
