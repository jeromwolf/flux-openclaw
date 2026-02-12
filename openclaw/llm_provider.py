"""
flux-openclaw Multi-LLM 프로바이더 추상화 레이어

기존 Anthropic Claude API 형식을 내부 표준으로 사용하며,
각 프로바이더가 내부적으로 형식 변환을 수행합니다.

지원 프로바이더:
- anthropic: Claude (기본값) - claude-sonnet-4-20250514
- openai: GPT-4o, GPT-4-turbo
- google: Gemini 2.5 Pro, Gemini 2.5 Flash

환경변수:
- LLM_PROVIDER: anthropic|openai|google (기본: anthropic)
- LLM_MODEL: 모델명 (기본: 프로바이더별 기본 모델)
- ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY

사용법:
    from openclaw.llm_provider import get_provider

    provider = get_provider()  # 환경변수 기반 자동 선택
    response = provider.create_message(
        messages=messages,
        system=system_prompt,
        tools=tool_mgr.schemas,
        max_tokens=4096,
    )
    # response.content = [TextBlock(...), ToolUseBlock(...), ...]
    # response.stop_reason = "end_turn" | "tool_use" | "max_tokens"
    # response.usage.input_tokens, response.usage.output_tokens
"""

from dataclasses import dataclass, field
from typing import Any

# 로깅 설정
try:
    from logging_config import get_logger
    logger = get_logger("llm_provider")
except ImportError:
    import logging
    logger = logging.getLogger("llm_provider")


# ============================================================
# 통일된 응답 객체 (Anthropic 형식 호환)
# ============================================================

@dataclass
class ToolUseBlock:
    """도구 호출 블록 (Anthropic tool_use 호환)"""
    type: str = "tool_use"
    id: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)


@dataclass
class TextBlock:
    """텍스트 블록 (Anthropic text 호환)"""
    type: str = "text"
    text: str = ""


@dataclass
class Usage:
    """토큰 사용량"""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class StreamEvent:
    """스트리밍 이벤트

    type:
      - "text_delta": 텍스트 청크 (data = str)
      - "tool_use_start": 도구 호출 시작 (data = {"id": str, "name": str})
      - "tool_use_delta": 도구 입력 청크 (data = {"id": str, "partial_json": str})
      - "tool_use_end": 도구 호출 완성 (data = {"id": str, "name": str, "input": dict})
      - "message_start": 메시지 시작 (data = {"model": str})
      - "message_end": 메시지 종료 (data = {"stop_reason": str, "usage": Usage})
      - "content_complete": 전체 내용 완성 (data = LLMResponse)
      - "error": 에러 (data = str)
    """
    type: str
    data: Any = None


@dataclass
class LLMResponse:
    """프로바이더 통일 응답 (Anthropic 형식 호환)

    기존 코드에서 response.content, response.stop_reason,
    response.usage.input_tokens 등으로 접근하던 패턴을 그대로 유지합니다.
    """
    content: list = field(default_factory=list)  # [TextBlock, ToolUseBlock, ...]
    stop_reason: str = "end_turn"  # "end_turn" | "tool_use" | "max_tokens"
    usage: Usage = field(default_factory=Usage)
    raw: Any = None  # 원본 응답 (디버깅용)


# ============================================================
# 기본 프로바이더 클래스
# ============================================================

class BaseLLMProvider:
    """LLM 프로바이더 기본 클래스

    모든 프로바이더는 이 클래스를 상속하며,
    Anthropic 스타일 인터페이스를 구현합니다.
    """

    PROVIDER_NAME = "base"
    DEFAULT_MODEL = ""

    def __init__(self, api_key: str, model: str = None):
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL

    def create_message(self, messages, system="", tools=None, max_tokens=4096) -> LLMResponse:
        """메시지 생성 (Anthropic 호환 인터페이스)

        Args:
            messages: Anthropic 형식 메시지 리스트
                      [{"role": "user", "content": "..."}, ...]
            system: 시스템 프롬프트 문자열
            tools: Anthropic 형식 도구 스키마 리스트
                   [{"name": "...", "description": "...", "input_schema": {...}}, ...]
            max_tokens: 최대 출력 토큰 수

        Returns:
            LLMResponse: 통일된 응답 객체
        """
        raise NotImplementedError

    def create_message_stream(self, messages, system="", tools=None, max_tokens=4096):
        """스트리밍 메시지 생성 (제너레이터).

        Yields:
            StreamEvent

        기본 구현: create_message()를 호출하고 결과를 한 번에 yield.
        프로바이더별로 오버라이드하여 실제 스트리밍 구현.
        """
        # 기본 fallback: 비스트리밍으로 동작
        response = self.create_message(messages, system, tools, max_tokens)
        yield StreamEvent(type="message_start", data={"model": self.model})
        for block in response.content:
            if hasattr(block, "text") and block.text:
                yield StreamEvent(type="text_delta", data=block.text)
            elif hasattr(block, "name") and block.name:
                yield StreamEvent(type="tool_use_start", data={"id": block.id, "name": block.name})
                yield StreamEvent(type="tool_use_end", data={"id": block.id, "name": block.name, "input": block.input})
        yield StreamEvent(type="message_end", data={"stop_reason": response.stop_reason, "usage": response.usage})
        yield StreamEvent(type="content_complete", data=response)

    def convert_tools(self, anthropic_tools):
        """Anthropic 도구 스키마를 이 프로바이더 형식으로 변환"""
        raise NotImplementedError

    def convert_messages(self, anthropic_messages, system=""):
        """Anthropic 메시지를 이 프로바이더 형식으로 변환"""
        raise NotImplementedError


# ============================================================
# Anthropic 프로바이더
# ============================================================

class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude 프로바이더 (기존 동작 래핑)

    기존 코드의 anthropic.Anthropic 사용을 그대로 래핑합니다.
    형식 변환이 필요 없으므로 가장 단순합니다.
    """

    PROVIDER_NAME = "anthropic"
    DEFAULT_MODEL = "claude-sonnet-4-20250514"

    def __init__(self, api_key, model=None):
        super().__init__(api_key, model)
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)

    def create_message(self, messages, system="", tools=None, max_tokens=4096):
        logger.debug(f"Anthropic API call: model={self.model}")
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        response = self.client.messages.create(**kwargs)

        # Anthropic 응답을 LLMResponse로 변환
        content = []
        for block in response.content:
            if block.type == "text":
                content.append(TextBlock(text=block.text))
            elif block.type == "tool_use":
                content.append(ToolUseBlock(
                    id=block.id,
                    name=block.name,
                    input=block.input,
                ))

        return LLMResponse(
            content=content,
            stop_reason=response.stop_reason,
            usage=Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            raw=response,
        )

    def create_message_stream(self, messages, system="", tools=None, max_tokens=4096):
        """Anthropic 스트리밍 (client.messages.stream() 컨텍스트 매니저)"""
        logger.debug("Anthropic streaming API call: model=%s", self.model)
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        yield StreamEvent(type="message_start", data={"model": self.model})

        content = []
        current_tool = None
        tool_json_parts = []

        with self.client.messages.stream(**kwargs) as stream:
            for event in stream:
                # text delta
                if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                    yield StreamEvent(type="text_delta", data=event.delta.text)

                # tool_use start
                elif event.type == "content_block_start" and hasattr(event.content_block, "type") and event.content_block.type == "tool_use":
                    current_tool = {"id": event.content_block.id, "name": event.content_block.name}
                    tool_json_parts = []
                    yield StreamEvent(type="tool_use_start", data={"id": current_tool["id"], "name": current_tool["name"]})

                # tool input delta
                elif event.type == "content_block_delta" and hasattr(event.delta, "partial_json"):
                    tool_json_parts.append(event.delta.partial_json)
                    if current_tool:
                        yield StreamEvent(type="tool_use_delta", data={"id": current_tool["id"], "partial_json": event.delta.partial_json})

                # content block stop
                elif event.type == "content_block_stop":
                    if current_tool:
                        import json as _json
                        full_json = "".join(tool_json_parts)
                        try:
                            tool_input = _json.loads(full_json) if full_json else {}
                        except _json.JSONDecodeError:
                            tool_input = {}
                        yield StreamEvent(type="tool_use_end", data={"id": current_tool["id"], "name": current_tool["name"], "input": tool_input})
                        content.append(ToolUseBlock(id=current_tool["id"], name=current_tool["name"], input=tool_input))
                        current_tool = None
                        tool_json_parts = []

            # 최종 메시지 조립
            final_message = stream.get_final_message()

        # content 재구성
        final_content = []
        for block in final_message.content:
            if block.type == "text":
                final_content.append(TextBlock(text=block.text))
            elif block.type == "tool_use":
                final_content.append(ToolUseBlock(id=block.id, name=block.name, input=block.input))

        response = LLMResponse(
            content=final_content,
            stop_reason=final_message.stop_reason,
            usage=Usage(
                input_tokens=final_message.usage.input_tokens,
                output_tokens=final_message.usage.output_tokens,
            ),
            raw=final_message,
        )
        yield StreamEvent(type="message_end", data={"stop_reason": response.stop_reason, "usage": response.usage})
        yield StreamEvent(type="content_complete", data=response)

    def convert_tools(self, anthropic_tools):
        """Anthropic 형식이 내부 표준이므로 변환 없이 반환"""
        return anthropic_tools

    def convert_messages(self, anthropic_messages, system=""):
        """Anthropic 형식이 내부 표준이므로 변환 없이 반환"""
        return anthropic_messages


# ============================================================
# OpenAI 프로바이더
# ============================================================

class OpenAIProvider(BaseLLMProvider):
    """OpenAI GPT 프로바이더

    Anthropic 형식의 입력을 OpenAI 형식으로 변환하고,
    OpenAI 응답을 통일된 LLMResponse로 변환합니다.

    주요 변환:
    - system 메시지가 messages 배열에 포함
    - tool_result (Anthropic) -> tool role (OpenAI)
    - input_schema (Anthropic) -> parameters (OpenAI)
    - stop_reason 매핑: stop->end_turn, tool_calls->tool_use, length->max_tokens
    """

    PROVIDER_NAME = "openai"
    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, api_key, model=None):
        super().__init__(api_key, model)
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key)
        except ImportError:
            raise ImportError(
                "openai 라이브러리가 필요합니다: pip install openai"
            )

    def convert_tools(self, anthropic_tools):
        """Anthropic -> OpenAI 도구 형식 변환

        Anthropic:
          {"name": "x", "description": "y",
           "input_schema": {"type": "object", "properties": {...}, "required": [...]}}

        OpenAI:
          {"type": "function", "function":
           {"name": "x", "description": "y",
            "parameters": {"type": "object", "properties": {...}, "required": [...]}}}
        """
        if not anthropic_tools:
            return None

        openai_tools = []
        for tool in anthropic_tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get(
                        "input_schema",
                        {"type": "object", "properties": {}}
                    ),
                },
            })
        return openai_tools

    def convert_messages(self, anthropic_messages, system=""):
        """Anthropic -> OpenAI 메시지 형식 변환

        주요 차이점:
        - OpenAI: system 메시지가 messages 배열 첫 번째 요소
        - Anthropic tool_result -> OpenAI tool role
        - Anthropic assistant content 리스트 (TextBlock + ToolUseBlock 혼합)
          -> OpenAI assistant message (content + tool_calls)
        """
        import json as _json

        openai_messages = []

        if system:
            openai_messages.append({"role": "system", "content": system})

        for msg in anthropic_messages:
            role = msg["role"]
            content = msg["content"]

            if role == "user":
                if isinstance(content, str):
                    openai_messages.append({"role": "user", "content": content})
                elif isinstance(content, list):
                    # tool_result 리스트 또는 텍스트 블록 리스트
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "tool_result":
                            tool_content = item.get("content", "")
                            if isinstance(tool_content, list):
                                # content가 리스트인 경우 텍스트 추출
                                parts = []
                                for part in tool_content:
                                    if isinstance(part, dict) and part.get("type") == "text":
                                        parts.append(part.get("text", ""))
                                    else:
                                        parts.append(str(part))
                                tool_content = "\n".join(parts)
                            openai_messages.append({
                                "role": "tool",
                                "tool_call_id": item.get("tool_use_id", ""),
                                "content": str(tool_content),
                            })
                        elif isinstance(item, dict) and item.get("type") == "text":
                            openai_messages.append({
                                "role": "user",
                                "content": item.get("text", ""),
                            })
                        else:
                            openai_messages.append({
                                "role": "user",
                                "content": str(item),
                            })
                else:
                    openai_messages.append({"role": "user", "content": str(content)})

            elif role == "assistant":
                if isinstance(content, str):
                    openai_messages.append({"role": "assistant", "content": content})
                elif isinstance(content, list):
                    # TextBlock + ToolUseBlock 혼합 처리
                    text_parts = []
                    tool_calls = []

                    for block in content:
                        # dataclass 객체 (TextBlock, ToolUseBlock) 또는 dict
                        block_type = getattr(block, "type", None) or (
                            block.get("type") if isinstance(block, dict) else None
                        )

                        if block_type == "text":
                            text = getattr(block, "text", None)
                            if text is None and isinstance(block, dict):
                                text = block.get("text", "")
                            text_parts.append(text or "")

                        elif block_type == "tool_use":
                            block_id = getattr(block, "id", None)
                            block_name = getattr(block, "name", None)
                            block_input = getattr(block, "input", None)
                            if block_id is None and isinstance(block, dict):
                                block_id = block.get("id", "")
                                block_name = block.get("name", "")
                                block_input = block.get("input", {})

                            tool_calls.append({
                                "id": block_id or "",
                                "type": "function",
                                "function": {
                                    "name": block_name or "",
                                    "arguments": _json.dumps(
                                        block_input or {}, ensure_ascii=False
                                    ),
                                },
                            })

                    assistant_msg = {"role": "assistant"}
                    if text_parts:
                        assistant_msg["content"] = "\n".join(text_parts)
                    else:
                        assistant_msg["content"] = None
                    if tool_calls:
                        assistant_msg["tool_calls"] = tool_calls
                    openai_messages.append(assistant_msg)
                else:
                    openai_messages.append({
                        "role": "assistant",
                        "content": str(content),
                    })

        return openai_messages

    def create_message(self, messages, system="", tools=None, max_tokens=4096):
        import json as _json

        logger.debug(f"OpenAI API call: model={self.model}")
        openai_messages = self.convert_messages(messages, system)
        openai_tools = self.convert_tools(tools) if tools else None

        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": openai_messages,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools

        response = self.client.chat.completions.create(**kwargs)

        # OpenAI 응답 -> 통일 형식
        choice = response.choices[0]
        content = []

        if choice.message.content:
            content.append(TextBlock(text=choice.message.content))

        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = _json.loads(tc.function.arguments)
                except (_json.JSONDecodeError, TypeError):
                    args = {}
                content.append(ToolUseBlock(
                    id=tc.id,
                    name=tc.function.name,
                    input=args,
                ))

        # stop_reason 매핑: OpenAI -> Anthropic 호환
        stop_reason_map = {
            "stop": "end_turn",
            "tool_calls": "tool_use",
            "length": "max_tokens",
            "content_filter": "end_turn",
        }
        stop_reason = stop_reason_map.get(choice.finish_reason, "end_turn")

        return LLMResponse(
            content=content,
            stop_reason=stop_reason,
            usage=Usage(
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
            ),
            raw=response,
        )

    def create_message_stream(self, messages, system="", tools=None, max_tokens=4096):
        """OpenAI 스트리밍"""
        import json as _json

        logger.debug("OpenAI streaming API call: model=%s", self.model)
        openai_messages = self.convert_messages(messages, system)
        openai_tools = self.convert_tools(tools) if tools else None

        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": openai_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if openai_tools:
            kwargs["tools"] = openai_tools

        yield StreamEvent(type="message_start", data={"model": self.model})

        content = []
        tool_calls_acc = {}  # index -> {id, name, args_parts}
        finish_reason = None
        usage_data = None

        stream_response = self.client.chat.completions.create(**kwargs)
        for chunk in stream_response:
            if not chunk.choices and hasattr(chunk, "usage") and chunk.usage:
                usage_data = Usage(
                    input_tokens=chunk.usage.prompt_tokens or 0,
                    output_tokens=chunk.usage.completion_tokens or 0,
                )
                continue

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason or finish_reason

            # text delta
            if delta and delta.content:
                yield StreamEvent(type="text_delta", data=delta.content)

            # tool calls
            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"id": tc.id or "", "name": "", "args_parts": []}
                        if tc.function and tc.function.name:
                            tool_calls_acc[idx]["name"] = tc.function.name
                            yield StreamEvent(type="tool_use_start", data={"id": tc.id or "", "name": tc.function.name})
                    if tc.function and tc.function.arguments:
                        tool_calls_acc[idx]["args_parts"].append(tc.function.arguments)
                        yield StreamEvent(type="tool_use_delta", data={"id": tool_calls_acc[idx]["id"], "partial_json": tc.function.arguments})

        # tool call 완료 처리
        for idx in sorted(tool_calls_acc.keys()):
            tc_data = tool_calls_acc[idx]
            full_args = "".join(tc_data["args_parts"])
            try:
                tool_input = _json.loads(full_args) if full_args else {}
            except _json.JSONDecodeError:
                tool_input = {}
            yield StreamEvent(type="tool_use_end", data={"id": tc_data["id"], "name": tc_data["name"], "input": tool_input})
            content.append(ToolUseBlock(id=tc_data["id"], name=tc_data["name"], input=tool_input))

        # stop_reason 매핑
        stop_map = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens"}
        stop_reason = stop_map.get(finish_reason, "end_turn")

        if not usage_data:
            usage_data = Usage()

        response = LLMResponse(
            content=content,
            stop_reason=stop_reason,
            usage=usage_data,
        )
        yield StreamEvent(type="message_end", data={"stop_reason": stop_reason, "usage": usage_data})
        yield StreamEvent(type="content_complete", data=response)


# ============================================================
# Google Gemini 프로바이더
# ============================================================

class GoogleProvider(BaseLLMProvider):
    """Google Gemini 프로바이더

    Anthropic 형식의 입력을 Gemini 형식으로 변환하고,
    Gemini 응답을 통일된 LLMResponse로 변환합니다.

    주요 변환:
    - role: assistant -> model
    - tool_result -> function_response Part
    - tool_use -> function_call Part
    - system은 GenerativeModel의 system_instruction으로 전달
    - tool_use_id 대신 UUID 생성 (Gemini는 tool ID 없음)
    """

    PROVIDER_NAME = "google"
    DEFAULT_MODEL = "gemini-2.5-flash"

    def __init__(self, api_key, model=None):
        super().__init__(api_key, model)
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self.genai = genai
        except ImportError:
            raise ImportError(
                "google-generativeai 라이브러리가 필요합니다: "
                "pip install google-generativeai"
            )

    def convert_tools(self, anthropic_tools):
        """Anthropic -> Google Gemini 도구 형식 변환

        Anthropic input_schema -> Gemini FunctionDeclaration parameters
        """
        if not anthropic_tools:
            return None

        function_declarations = []
        for tool in anthropic_tools:
            schema = tool.get("input_schema", {})
            params = {
                "type": schema.get("type", "object"),
                "properties": schema.get("properties", {}),
            }
            if "required" in schema:
                params["required"] = schema["required"]

            function_declarations.append(
                self.genai.protos.FunctionDeclaration(
                    name=tool["name"],
                    description=tool.get("description", ""),
                    parameters=params,
                )
            )

        return self.genai.protos.Tool(
            function_declarations=function_declarations
        )

    def _resolve_tool_name(self, tool_use_id, messages):
        """tool_use_id에서 도구 이름을 역추적

        Gemini의 function_response에는 함수 이름이 필요하지만,
        Anthropic의 tool_result에는 tool_use_id만 있으므로
        이전 assistant 메시지에서 해당 ID의 도구 이름을 찾습니다.
        """
        for msg in reversed(messages):
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                block_type = getattr(block, "type", None) or (
                    block.get("type") if isinstance(block, dict) else None
                )
                if block_type != "tool_use":
                    continue
                block_id = getattr(block, "id", None)
                if block_id is None and isinstance(block, dict):
                    block_id = block.get("id")
                if block_id == tool_use_id:
                    block_name = getattr(block, "name", None)
                    if block_name is None and isinstance(block, dict):
                        block_name = block.get("name")
                    return block_name or "unknown"
        return "unknown"

    def convert_messages(self, anthropic_messages, system=""):
        """Anthropic -> Gemini 메시지 형식 변환

        Gemini는 role이 "user"와 "model"만 사용.
        tool_result는 function_response Part로 변환.
        tool_use는 function_call Part로 변환.
        """
        gemini_history = []

        for msg in anthropic_messages:
            role = msg["role"]
            content = msg["content"]

            if role == "user":
                if isinstance(content, str):
                    gemini_history.append({
                        "role": "user",
                        "parts": [content],
                    })
                elif isinstance(content, list):
                    parts = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "tool_result":
                            # tool_result -> function_response
                            tool_use_id = item.get("tool_use_id", "unknown")
                            tool_name = self._resolve_tool_name(
                                tool_use_id, anthropic_messages
                            )
                            result_content = item.get("content", "")
                            if isinstance(result_content, list):
                                text_parts = []
                                for part in result_content:
                                    if isinstance(part, dict) and part.get("type") == "text":
                                        text_parts.append(part.get("text", ""))
                                    else:
                                        text_parts.append(str(part))
                                result_content = "\n".join(text_parts)
                            parts.append(self.genai.protos.Part(
                                function_response=self.genai.protos.FunctionResponse(
                                    name=tool_name,
                                    response={"result": str(result_content)},
                                )
                            ))
                        elif isinstance(item, dict) and item.get("type") == "text":
                            parts.append(item.get("text", ""))
                        else:
                            parts.append(str(item))
                    if parts:
                        gemini_history.append({"role": "user", "parts": parts})

            elif role == "assistant":
                if isinstance(content, str):
                    gemini_history.append({
                        "role": "model",
                        "parts": [content],
                    })
                elif isinstance(content, list):
                    parts = []
                    for block in content:
                        block_type = getattr(block, "type", None) or (
                            block.get("type") if isinstance(block, dict) else None
                        )

                        if block_type == "text":
                            text = getattr(block, "text", None)
                            if text is None and isinstance(block, dict):
                                text = block.get("text", "")
                            if text:
                                parts.append(text)

                        elif block_type == "tool_use":
                            block_name = getattr(block, "name", None)
                            block_input = getattr(block, "input", None)
                            if block_name is None and isinstance(block, dict):
                                block_name = block.get("name", "")
                                block_input = block.get("input", {})
                            parts.append(self.genai.protos.Part(
                                function_call=self.genai.protos.FunctionCall(
                                    name=block_name or "",
                                    args=block_input or {},
                                )
                            ))

                    if parts:
                        gemini_history.append({"role": "model", "parts": parts})

        return gemini_history

    def create_message(self, messages, system="", tools=None, max_tokens=4096):
        import uuid

        logger.debug(f"Google API call: model={self.model}")
        gemini_tools = [self.convert_tools(tools)] if tools else None
        gemini_history = self.convert_messages(messages, system)

        # Gemini GenerativeModel 설정
        model_kwargs = {}
        if system:
            model_kwargs["system_instruction"] = system
        if gemini_tools:
            model_kwargs["tools"] = gemini_tools

        generation_config = self.genai.types.GenerationConfig(
            max_output_tokens=max_tokens,
        )

        model = self.genai.GenerativeModel(self.model, **model_kwargs)

        # Gemini는 chat.send_message 패턴 사용
        # 마지막 메시지를 send_message로 전송, 나머지는 history
        if not gemini_history:
            return LLMResponse()

        if len(gemini_history) > 1:
            chat = model.start_chat(history=gemini_history[:-1])
            last_msg = gemini_history[-1]
            response = chat.send_message(
                last_msg["parts"],
                generation_config=generation_config,
            )
        else:
            chat = model.start_chat()
            response = chat.send_message(
                gemini_history[0]["parts"],
                generation_config=generation_config,
            )

        # Gemini 응답 -> 통일 형식
        content = []
        has_tool_calls = False

        for part in response.parts:
            if hasattr(part, "text") and part.text:
                content.append(TextBlock(text=part.text))
            elif hasattr(part, "function_call") and part.function_call:
                has_tool_calls = True
                fc = part.function_call
                content.append(ToolUseBlock(
                    id="toolu_{}".format(uuid.uuid4().hex[:24]),
                    name=fc.name,
                    input=dict(fc.args) if fc.args else {},
                ))

        # stop_reason 매핑
        stop_reason = "tool_use" if has_tool_calls else "end_turn"
        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, "finish_reason"):
                fr = str(candidate.finish_reason)
                if "MAX_TOKENS" in fr:
                    stop_reason = "max_tokens"

        # usage 추출
        input_tokens = 0
        output_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            input_tokens = getattr(
                response.usage_metadata, "prompt_token_count", 0
            ) or 0
            output_tokens = getattr(
                response.usage_metadata, "candidates_token_count", 0
            ) or 0

        return LLMResponse(
            content=content,
            stop_reason=stop_reason,
            usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
            raw=response,
        )

    def create_message_stream(self, messages, system="", tools=None, max_tokens=4096):
        """Google Gemini 스트리밍"""
        import uuid

        logger.debug("Google streaming API call: model=%s", self.model)
        gemini_tools = [self.convert_tools(tools)] if tools else None
        gemini_history = self.convert_messages(messages, system)

        model_kwargs = {}
        if system:
            model_kwargs["system_instruction"] = system
        if gemini_tools:
            model_kwargs["tools"] = gemini_tools

        generation_config = self.genai.types.GenerationConfig(max_output_tokens=max_tokens)
        model = self.genai.GenerativeModel(self.model, **model_kwargs)

        if not gemini_history:
            yield StreamEvent(type="content_complete", data=LLMResponse())
            return

        yield StreamEvent(type="message_start", data={"model": self.model})

        if len(gemini_history) > 1:
            chat = model.start_chat(history=gemini_history[:-1])
            response_stream = chat.send_message(
                gemini_history[-1]["parts"],
                generation_config=generation_config,
                stream=True,
            )
        else:
            chat = model.start_chat()
            response_stream = chat.send_message(
                gemini_history[0]["parts"],
                generation_config=generation_config,
                stream=True,
            )

        content = []
        has_tool_calls = False

        for chunk in response_stream:
            for part in chunk.parts:
                if hasattr(part, "text") and part.text:
                    yield StreamEvent(type="text_delta", data=part.text)
                elif hasattr(part, "function_call") and part.function_call:
                    has_tool_calls = True
                    fc = part.function_call
                    tool_id = "toolu_{}".format(uuid.uuid4().hex[:24])
                    tool_input = dict(fc.args) if fc.args else {}
                    yield StreamEvent(type="tool_use_start", data={"id": tool_id, "name": fc.name})
                    yield StreamEvent(type="tool_use_end", data={"id": tool_id, "name": fc.name, "input": tool_input})
                    content.append(ToolUseBlock(id=tool_id, name=fc.name, input=tool_input))

        stop_reason = "tool_use" if has_tool_calls else "end_turn"

        # resolve()로 최종 응답 가져오기
        try:
            final_response = response_stream.resolve()
            if hasattr(final_response, "candidates") and final_response.candidates:
                candidate = final_response.candidates[0]
                if hasattr(candidate, "finish_reason"):
                    fr = str(candidate.finish_reason)
                    if "MAX_TOKENS" in fr:
                        stop_reason = "max_tokens"

            input_tokens = 0
            output_tokens = 0
            if hasattr(final_response, "usage_metadata") and final_response.usage_metadata:
                input_tokens = getattr(final_response.usage_metadata, "prompt_token_count", 0) or 0
                output_tokens = getattr(final_response.usage_metadata, "candidates_token_count", 0) or 0
            usage_data = Usage(input_tokens=input_tokens, output_tokens=output_tokens)
        except Exception:
            usage_data = Usage()

        response = LLMResponse(content=content, stop_reason=stop_reason, usage=usage_data)
        yield StreamEvent(type="message_end", data={"stop_reason": stop_reason, "usage": usage_data})
        yield StreamEvent(type="content_complete", data=response)


# ============================================================
# 프로바이더 팩토리
# ============================================================

PROVIDERS = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "google": GoogleProvider,
}

DEFAULT_PROVIDER = "anthropic"


def get_provider(provider_name=None, model=None, api_key=None):
    """환경변수 또는 인자에서 LLM 프로바이더를 생성합니다.

    Args:
        provider_name: "anthropic"|"openai"|"google"
                       None이면 환경변수 LLM_PROVIDER 사용 (기본: anthropic)
        model: 모델명. None이면 환경변수 LLM_MODEL 또는 프로바이더 기본값
        api_key: API 키. None이면 환경변수에서 자동 탐색

    Returns:
        BaseLLMProvider 인스턴스

    Raises:
        ValueError: 알 수 없는 프로바이더 또는 API 키 미설정
        ImportError: 프로바이더 라이브러리 미설치

    Examples:
        # 환경변수 기반 (가장 일반적)
        provider = get_provider()

        # 명시적 지정
        provider = get_provider("openai", model="gpt-4-turbo")

        # API 키 직접 전달
        provider = get_provider("anthropic", api_key="sk-ant-...")
    """
    import os

    provider_name = provider_name or os.environ.get(
        "LLM_PROVIDER", DEFAULT_PROVIDER
    )
    model = model or os.environ.get("LLM_MODEL")

    provider_cls = PROVIDERS.get(provider_name)
    if not provider_cls:
        available = ", ".join(PROVIDERS.keys())
        raise ValueError(
            "알 수 없는 프로바이더: {}. 사용 가능: {}".format(
                provider_name, available
            )
        )

    # API 키 자동 탐색
    if not api_key:
        key_env_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "google": "GOOGLE_API_KEY",
        }
        env_name = key_env_map.get(provider_name, "")
        api_key = os.environ.get(env_name)
        if not api_key:
            raise ValueError(
                "{} 환경변수가 설정되지 않았습니다.".format(env_name)
            )

    return provider_cls(api_key=api_key, model=model)


def list_providers():
    """사용 가능한 프로바이더 목록을 반환합니다.

    Returns:
        list[dict]: 프로바이더 정보 리스트
            [{"name": "anthropic", "default_model": "claude-sonnet-4-20250514",
              "class": "AnthropicProvider"}, ...]
    """
    result = []
    for name, cls in PROVIDERS.items():
        result.append({
            "name": name,
            "default_model": cls.DEFAULT_MODEL,
            "class": cls.__name__,
        })
    return result
