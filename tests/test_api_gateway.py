"""Tests for api_gateway.py (ChatAPI class).

Covers:
- __init__: stores engine and conv_store references
- chat_sync: message handling, conversation IDs, error paths, conv_store persistence
- chat_stream: SSE event yielding for text_delta, tool_use_start, tool_use_end,
               tool_result, turn_complete, error events, and exception handling
"""
import os
import sys
import uuid
import pytest
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api_gateway import ChatAPI


# ============================================================
# Helpers / Fixtures
# ============================================================

@dataclass
class FakeTurnResult:
    """Mimics conversation_engine.TurnResult for mocking."""
    text: str = ""
    tool_rounds: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    stop_reason: str = ""
    error: Optional[str] = None


@dataclass
class FakeStreamEvent:
    """Mimics llm_provider.StreamEvent for mocking."""
    type: str
    data: object = None


def _make_engine():
    """Return a MagicMock engine with sensible defaults."""
    engine = MagicMock()
    engine.run_turn.return_value = FakeTurnResult(
        text="Hello from engine",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.001,
    )
    return engine


def _make_conv_store():
    """Return a MagicMock conversation store."""
    store = MagicMock()
    store.get_messages.return_value = []
    return store


# ============================================================
# __init__ Tests
# ============================================================

class TestChatAPIInit:
    def test_stores_engine_reference(self):
        engine = _make_engine()
        api = ChatAPI(engine)
        assert api.engine is engine

    def test_stores_conv_store_reference(self):
        engine = _make_engine()
        store = _make_conv_store()
        api = ChatAPI(engine, conv_store=store)
        assert api.conv_store is store

    def test_conv_store_defaults_to_none(self):
        engine = _make_engine()
        api = ChatAPI(engine)
        assert api.conv_store is None


# ============================================================
# chat_sync Tests
# ============================================================

class TestChatSync:
    def test_calls_engine_run_turn_with_user_message(self):
        engine = _make_engine()
        api = ChatAPI(engine)
        api.chat_sync("Hi there")
        args, kwargs = engine.run_turn.call_args
        messages = args[0]
        assert any(m["role"] == "user" and m["content"] == "Hi there" for m in messages)

    def test_returns_dict_with_response_key(self):
        engine = _make_engine()
        api = ChatAPI(engine)
        result = api.chat_sync("Hello")
        assert "response" in result
        assert result["response"] == "Hello from engine"

    def test_returns_dict_with_conversation_id(self):
        engine = _make_engine()
        api = ChatAPI(engine)
        result = api.chat_sync("Hello")
        assert "conversation_id" in result
        assert isinstance(result["conversation_id"], str)
        assert len(result["conversation_id"]) > 0

    def test_returns_dict_with_usage(self):
        engine = _make_engine()
        api = ChatAPI(engine)
        result = api.chat_sync("Hello")
        assert "usage" in result
        assert result["usage"]["input_tokens"] == 10
        assert result["usage"]["output_tokens"] == 5
        assert result["usage"]["cost_usd"] == 0.001

    def test_auto_generates_conversation_id_when_not_provided(self):
        engine = _make_engine()
        api = ChatAPI(engine)
        result = api.chat_sync("Hello")
        conv_id = result["conversation_id"]
        # Should be a valid UUID
        uuid.UUID(conv_id)  # raises ValueError if invalid

    def test_uses_provided_conversation_id(self):
        engine = _make_engine()
        api = ChatAPI(engine)
        result = api.chat_sync("Hello", conversation_id="my-conv-123")
        assert result["conversation_id"] == "my-conv-123"

    def test_handles_engine_exception_gracefully(self):
        engine = _make_engine()
        engine.run_turn.side_effect = RuntimeError("LLM provider down")
        api = ChatAPI(engine)
        result = api.chat_sync("Hello")
        # Should return error dict, NOT raise
        assert "error" in result
        assert result["response"] == ""
        assert result["usage"]["input_tokens"] == 0
        assert result["usage"]["output_tokens"] == 0

    def test_error_dict_preserves_conversation_id(self):
        engine = _make_engine()
        engine.run_turn.side_effect = RuntimeError("fail")
        api = ChatAPI(engine)
        result = api.chat_sync("Hello", conversation_id="keep-me")
        assert result["conversation_id"] == "keep-me"

    def test_saves_to_conv_store_when_provided(self):
        engine = _make_engine()
        store = _make_conv_store()
        api = ChatAPI(engine, conv_store=store)
        result = api.chat_sync("Hello", conversation_id="conv-1")
        store.ensure_conversation.assert_called_once_with("conv-1", interface="rest_api")
        store.add_message.assert_any_call("conv-1", "user", "Hello")
        store.add_message.assert_any_call("conv-1", "assistant", "Hello from engine")

    def test_no_conv_store_no_save_attempt(self):
        engine = _make_engine()
        api = ChatAPI(engine, conv_store=None)
        result = api.chat_sync("Hello")
        # Should succeed without error; no store calls possible
        assert result["response"] == "Hello from engine"

    def test_includes_error_field_when_turn_result_has_error(self):
        engine = _make_engine()
        engine.run_turn.return_value = FakeTurnResult(
            text="partial",
            input_tokens=5,
            output_tokens=2,
            cost_usd=0.0,
            error="rate_limit_exceeded",
        )
        api = ChatAPI(engine)
        result = api.chat_sync("Hello")
        assert result["error"] == "rate_limit_exceeded"
        assert result["response"] == "partial"

    def test_no_error_field_when_turn_result_error_is_none(self):
        engine = _make_engine()
        api = ChatAPI(engine)
        result = api.chat_sync("Hello")
        assert "error" not in result

    def test_empty_text_when_turn_result_text_is_none(self):
        engine = _make_engine()
        engine.run_turn.return_value = FakeTurnResult(text=None, input_tokens=0, output_tokens=0, cost_usd=0.0)
        api = ChatAPI(engine)
        result = api.chat_sync("Hello")
        assert result["response"] == ""

    def test_passes_user_id_to_engine(self):
        engine = _make_engine()
        api = ChatAPI(engine)
        api.chat_sync("Hello", user_id="user-42")
        _, kwargs = engine.run_turn.call_args
        assert kwargs["user_id"] == "user-42"

    def test_conv_store_failure_does_not_raise(self):
        engine = _make_engine()
        store = _make_conv_store()
        store.ensure_conversation.side_effect = RuntimeError("DB locked")
        api = ChatAPI(engine, conv_store=store)
        # Should not raise
        result = api.chat_sync("Hello", conversation_id="conv-x")
        assert result["response"] == "Hello from engine"


# ============================================================
# chat_stream Tests
# ============================================================

class TestChatStream:
    def _stream_events(self, events):
        """Helper: make engine that yields given FakeStreamEvents."""
        engine = MagicMock()
        engine.run_turn_stream.return_value = iter(events)
        return engine

    def test_yields_tuples(self):
        engine = self._stream_events([
            FakeStreamEvent(type="text_delta", data="Hi"),
        ])
        api = ChatAPI(engine)
        results = list(api.chat_stream("Hello"))
        assert len(results) >= 1
        for item in results:
            assert isinstance(item, tuple)
            assert len(item) == 2

    def test_yields_data_for_text_delta(self):
        engine = self._stream_events([
            FakeStreamEvent(type="text_delta", data="chunk1"),
            FakeStreamEvent(type="text_delta", data="chunk2"),
        ])
        api = ChatAPI(engine)
        results = list(api.chat_stream("Hello"))
        assert ("data", "chunk1") in results
        assert ("data", "chunk2") in results

    def test_yields_tool_start_for_tool_use_start(self):
        engine = self._stream_events([
            FakeStreamEvent(type="tool_use_start", data={"name": "web_search"}),
        ])
        api = ChatAPI(engine)
        results = list(api.chat_stream("Hello"))
        assert ("tool_start", {"tool": "web_search"}) in results

    def test_tool_start_with_missing_name(self):
        engine = self._stream_events([
            FakeStreamEvent(type="tool_use_start", data={}),
        ])
        api = ChatAPI(engine)
        results = list(api.chat_stream("Hello"))
        assert ("tool_start", {"tool": ""}) in results

    def test_yields_tool_end_for_tool_use_end(self):
        engine = self._stream_events([
            FakeStreamEvent(type="tool_use_end", data={"name": "calculator"}),
        ])
        api = ChatAPI(engine)
        results = list(api.chat_stream("Hello"))
        assert ("tool_end", {"tool": "calculator"}) in results

    def test_yields_tool_end_for_tool_result(self):
        engine = self._stream_events([
            FakeStreamEvent(type="tool_result", data={"name": "fetch"}),
        ])
        api = ChatAPI(engine)
        results = list(api.chat_stream("Hello"))
        assert ("tool_end", {"tool": "fetch"}) in results

    def test_yields_done_on_turn_complete(self):
        turn_result = FakeTurnResult(
            text="final",
            input_tokens=20,
            output_tokens=10,
            cost_usd=0.002,
        )
        engine = self._stream_events([
            FakeStreamEvent(type="turn_complete", data=turn_result),
        ])
        api = ChatAPI(engine)
        results = list(api.chat_stream("Hello"))
        done_events = [r for r in results if r[0] == "done"]
        assert len(done_events) == 1
        done_data = done_events[0][1]
        assert done_data["usage"]["input_tokens"] == 20
        assert done_data["usage"]["output_tokens"] == 10
        assert done_data["usage"]["cost_usd"] == 0.002
        assert "conversation_id" in done_data

    def test_done_includes_error_when_turn_result_has_error(self):
        turn_result = FakeTurnResult(
            text="",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            error="timeout",
        )
        engine = self._stream_events([
            FakeStreamEvent(type="turn_complete", data=turn_result),
        ])
        api = ChatAPI(engine)
        results = list(api.chat_stream("Hello"))
        done_events = [r for r in results if r[0] == "done"]
        assert done_events[0][1]["error"] == "timeout"

    def test_yields_error_on_exception(self):
        engine = MagicMock()
        engine.run_turn_stream.side_effect = RuntimeError("stream broke")
        api = ChatAPI(engine)
        results = list(api.chat_stream("Hello"))
        error_events = [r for r in results if r[0] == "error"]
        assert len(error_events) == 1
        assert "stream broke" in error_events[0][1]["message"]

    def test_yields_error_for_error_event_type(self):
        engine = self._stream_events([
            FakeStreamEvent(type="error", data="something went wrong"),
        ])
        api = ChatAPI(engine)
        results = list(api.chat_stream("Hello"))
        error_events = [r for r in results if r[0] == "error"]
        assert len(error_events) == 1
        assert "something went wrong" in error_events[0][1]["message"]

    def test_saves_to_conv_store_on_completion(self):
        store = _make_conv_store()
        turn_result = FakeTurnResult(
            text="streamed text",
            input_tokens=15,
            output_tokens=8,
            cost_usd=0.001,
        )
        engine = self._stream_events([
            FakeStreamEvent(type="text_delta", data="streamed "),
            FakeStreamEvent(type="text_delta", data="text"),
            FakeStreamEvent(type="turn_complete", data=turn_result),
        ])
        api = ChatAPI(engine, conv_store=store)
        list(api.chat_stream("Hello", conversation_id="conv-s1"))
        store.ensure_conversation.assert_called_once_with("conv-s1", interface="rest_api")
        store.add_message.assert_any_call("conv-s1", "user", "Hello")
        store.add_message.assert_any_call("conv-s1", "assistant", "streamed text")

    def test_auto_generates_conversation_id(self):
        turn_result = FakeTurnResult(text="ok", input_tokens=1, output_tokens=1, cost_usd=0.0)
        engine = self._stream_events([
            FakeStreamEvent(type="turn_complete", data=turn_result),
        ])
        api = ChatAPI(engine)
        results = list(api.chat_stream("Hello"))
        done_events = [r for r in results if r[0] == "done"]
        conv_id = done_events[0][1]["conversation_id"]
        uuid.UUID(conv_id)  # validates format

    def test_uses_provided_conversation_id(self):
        turn_result = FakeTurnResult(text="ok", input_tokens=1, output_tokens=1, cost_usd=0.0)
        engine = self._stream_events([
            FakeStreamEvent(type="turn_complete", data=turn_result),
        ])
        api = ChatAPI(engine)
        results = list(api.chat_stream("Hello", conversation_id="my-stream-id"))
        done_events = [r for r in results if r[0] == "done"]
        assert done_events[0][1]["conversation_id"] == "my-stream-id"

    def test_conv_store_failure_during_stream_does_not_crash(self):
        store = _make_conv_store()
        store.ensure_conversation.side_effect = RuntimeError("DB locked")
        turn_result = FakeTurnResult(text="ok", input_tokens=1, output_tokens=1, cost_usd=0.0)
        engine = self._stream_events([
            FakeStreamEvent(type="text_delta", data="ok"),
            FakeStreamEvent(type="turn_complete", data=turn_result),
        ])
        api = ChatAPI(engine, conv_store=store)
        results = list(api.chat_stream("Hello", conversation_id="conv-fail"))
        done_events = [r for r in results if r[0] == "done"]
        assert len(done_events) == 1
