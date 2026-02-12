import pytest
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from openclaw.llm_provider import (
    TextBlock, ToolUseBlock, Usage, LLMResponse,
    AnthropicProvider, OpenAIProvider, GoogleProvider,
    get_provider, list_providers, PROVIDERS,
)


# ============================================================
# 데이터클래스 테스트
# ============================================================

def test_text_block_defaults():
    """TextBlock 기본값 테스트"""
    block = TextBlock()
    assert block.type == "text"
    assert block.text == ""


def test_tool_use_block_defaults():
    """ToolUseBlock 기본값 테스트"""
    block = ToolUseBlock()
    assert block.type == "tool_use"
    assert block.id == ""
    assert block.name == ""
    assert block.input == {}


def test_usage_defaults():
    """Usage 기본값 테스트"""
    usage = Usage()
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0


def test_llm_response_defaults():
    """LLMResponse 기본값 테스트"""
    response = LLMResponse()
    assert response.content == []
    assert response.stop_reason == "end_turn"
    assert response.usage.input_tokens == 0
    assert response.usage.output_tokens == 0
    assert response.raw is None


def test_llm_response_with_content():
    """내용 있는 LLMResponse 테스트"""
    response = LLMResponse(
        content=[
            TextBlock(text="Hello"),
            ToolUseBlock(id="tool_1", name="test_tool", input={"arg": "value"}),
        ],
        stop_reason="tool_use",
        usage=Usage(input_tokens=100, output_tokens=50),
    )
    assert len(response.content) == 2
    assert response.content[0].text == "Hello"
    assert response.content[1].name == "test_tool"
    assert response.stop_reason == "tool_use"
    assert response.usage.input_tokens == 100


# ============================================================
# 프로바이더 팩토리 테스트
# ============================================================

def test_list_providers():
    """list_providers가 3개 프로바이더를 반환하는지 확인"""
    providers = list_providers()
    assert len(providers) == 3
    names = [p["name"] for p in providers]
    assert "anthropic" in names
    assert "openai" in names
    assert "google" in names


def test_providers_dict():
    """PROVIDERS 딕셔너리 키 확인"""
    assert "anthropic" in PROVIDERS
    assert "openai" in PROVIDERS
    assert "google" in PROVIDERS
    assert PROVIDERS["anthropic"] == AnthropicProvider
    assert PROVIDERS["openai"] == OpenAIProvider
    assert PROVIDERS["google"] == GoogleProvider


def test_get_provider_unknown():
    """알 수 없는 프로바이더 시 ValueError"""
    with pytest.raises(ValueError, match="알 수 없는 프로바이더"):
        get_provider("unknown_provider", api_key="test")


def test_get_provider_no_api_key():
    """API 키 없을 때 ValueError"""
    # 환경변수 제거 후 테스트
    old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        with pytest.raises(ValueError, match="환경변수가 설정되지 않았습니다"):
            get_provider("anthropic")
    finally:
        if old_key:
            os.environ["ANTHROPIC_API_KEY"] = old_key


def test_get_provider_anthropic():
    """Anthropic 프로바이더 정상 초기화 (anthropic 설치 시)"""
    try:
        import anthropic
        provider = get_provider("anthropic", api_key="test-key")
        assert isinstance(provider, AnthropicProvider)
        assert provider.api_key == "test-key"
        assert provider.model == "claude-sonnet-4-20250514"
    except ImportError:
        pytest.skip("anthropic 라이브러리가 설치되지 않음")


# ============================================================
# OpenAI 변환 테스트 (API 호출 없이)
# ============================================================

class MockOpenAIProvider(OpenAIProvider):
    """openai import를 우회하여 변환 메서드만 테스트"""
    def __init__(self):
        # __init__ 건너뛰기
        self.api_key = "test"
        self.model = "gpt-4o"
        self.client = None


def test_openai_convert_tools():
    """Anthropic → OpenAI 도구 변환"""
    provider = MockOpenAIProvider()
    anthropic_tools = [
        {
            "name": "test_tool",
            "description": "테스트 도구",
            "input_schema": {
                "type": "object",
                "properties": {
                    "arg1": {"type": "string", "description": "인자1"},
                },
                "required": ["arg1"],
            },
        },
    ]

    openai_tools = provider.convert_tools(anthropic_tools)
    assert len(openai_tools) == 1
    assert openai_tools[0]["type"] == "function"
    assert openai_tools[0]["function"]["name"] == "test_tool"
    assert openai_tools[0]["function"]["description"] == "테스트 도구"
    assert "parameters" in openai_tools[0]["function"]
    assert openai_tools[0]["function"]["parameters"]["type"] == "object"
    assert "arg1" in openai_tools[0]["function"]["parameters"]["properties"]


def test_openai_convert_tools_empty():
    """빈 도구 리스트"""
    provider = MockOpenAIProvider()
    assert provider.convert_tools(None) is None
    assert provider.convert_tools([]) is None


def test_openai_convert_messages_simple():
    """간단한 메시지 변환"""
    provider = MockOpenAIProvider()
    anthropic_messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ]

    openai_messages = provider.convert_messages(anthropic_messages)
    assert len(openai_messages) == 2
    assert openai_messages[0]["role"] == "user"
    assert openai_messages[0]["content"] == "Hello"
    assert openai_messages[1]["role"] == "assistant"
    assert openai_messages[1]["content"] == "Hi there"


def test_openai_convert_messages_with_system():
    """system 메시지 포함"""
    provider = MockOpenAIProvider()
    anthropic_messages = [
        {"role": "user", "content": "Hello"},
    ]

    openai_messages = provider.convert_messages(anthropic_messages, system="You are a helpful assistant.")
    assert len(openai_messages) == 2
    assert openai_messages[0]["role"] == "system"
    assert openai_messages[0]["content"] == "You are a helpful assistant."
    assert openai_messages[1]["role"] == "user"


def test_openai_convert_messages_with_tool_results():
    """tool_result 변환"""
    provider = MockOpenAIProvider()
    anthropic_messages = [
        {
            "role": "assistant",
            "content": [
                ToolUseBlock(id="tool_123", name="test_tool", input={"arg": "value"}),
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "tool_123", "content": "Success"},
            ],
        },
    ]

    openai_messages = provider.convert_messages(anthropic_messages)

    # assistant 메시지 확인
    assert openai_messages[0]["role"] == "assistant"
    assert "tool_calls" in openai_messages[0]
    assert len(openai_messages[0]["tool_calls"]) == 1
    assert openai_messages[0]["tool_calls"][0]["id"] == "tool_123"
    assert openai_messages[0]["tool_calls"][0]["function"]["name"] == "test_tool"

    # tool 메시지 확인
    assert openai_messages[1]["role"] == "tool"
    assert openai_messages[1]["tool_call_id"] == "tool_123"
    assert openai_messages[1]["content"] == "Success"


# ============================================================
# 호환성 테스트
# ============================================================

def test_response_attribute_access():
    """response.usage.input_tokens, response.stop_reason 접근"""
    response = LLMResponse(
        content=[TextBlock(text="test")],
        stop_reason="end_turn",
        usage=Usage(input_tokens=100, output_tokens=50),
    )

    # 기존 코드 패턴 테스트
    assert response.usage.input_tokens == 100
    assert response.usage.output_tokens == 50
    assert response.stop_reason == "end_turn"
    assert len(response.content) == 1


def test_text_block_has_text_attr():
    """TextBlock은 text 속성을 가진다"""
    block = TextBlock(text="Hello")
    assert hasattr(block, "text")
    assert block.text == "Hello"


def test_tool_use_block_no_text_attr():
    """ToolUseBlock은 text 속성을 가지지 않는다 (중요!)"""
    block = ToolUseBlock(id="1", name="tool", input={})
    # hasattr는 False이지만, dataclass는 기본값이 없는 속성도 존재할 수 있음
    # 대신 type으로 구분해야 함
    assert not hasattr(block, "text")


def test_content_block_type_check():
    """block.type == "text" / "tool_use" 구분"""
    text_block = TextBlock(text="Hello")
    tool_block = ToolUseBlock(id="1", name="tool", input={})

    assert text_block.type == "text"
    assert tool_block.type == "tool_use"

    # 기존 코드 패턴: block.type으로 분기
    content = [text_block, tool_block]
    for block in content:
        if block.type == "text":
            assert hasattr(block, "text")
        elif block.type == "tool_use":
            assert hasattr(block, "name")
            assert hasattr(block, "input")
