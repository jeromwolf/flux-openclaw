"""REST Chat API business logic.

Provides ChatAPI class that DashboardHandler calls for /api/v1/chat endpoints.
Not an HTTP handler itself - just processes chat requests and returns results.

ChatAPI wraps ConversationEngine to provide:
- chat_sync(): synchronous chat returning JSON-serializable dict
- chat_stream(): SSE streaming chat yielding (event_type, data) tuples

Thread-safety: ChatAPI delegates to ConversationEngine which is thread-safe.
No external dependencies.
"""
from __future__ import annotations

import uuid
from typing import Generator, Optional

try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

# Optional streaming event support
try:
    from llm_provider import StreamEvent
    _has_stream_event = True
except ImportError:
    StreamEvent = None
    _has_stream_event = False


class ChatAPI:
    """REST Chat API business logic.

    DashboardHandler calls this class for chat endpoints.
    Does NOT handle HTTP requests/responses - only processes
    chat messages and returns results.

    Uses ConversationEngine for LLM interaction.
    """

    def __init__(self, engine, conv_store=None):
        """Initialize ChatAPI.

        Args:
            engine: ConversationEngine instance for LLM calls.
            conv_store: Optional ConversationStore for conversation persistence.
        """
        self.engine = engine
        self.conv_store = conv_store
        logger.info("ChatAPI initialized")

    def chat_sync(
        self,
        message: str,
        user_id: str = "default",
        conversation_id: str = None,
        system_prompt_override: str = None,
    ) -> dict:
        """Synchronous chat. Returns JSON-serializable dict.

        Creates a fresh messages list, runs engine.run_turn(), returns response.
        Optionally saves to conv_store if conversation_id provided.

        Args:
            message: User message text.
            user_id: User identifier for usage tracking.
            conversation_id: Optional conversation ID for persistence.
            system_prompt_override: Optional system prompt override (unused currently).

        Returns:
            Dict with keys:
                - response: Assistant response text
                - conversation_id: Conversation identifier
                - usage: {input_tokens, output_tokens, cost_usd}
        """
        # Generate conversation_id if not provided
        if not conversation_id:
            conversation_id = str(uuid.uuid4())

        # Load existing messages from conv_store if available
        messages = []
        if self.conv_store and conversation_id:
            try:
                existing = self.conv_store.get_messages(conversation_id, limit=50)
                if existing:
                    for msg in existing:
                        if isinstance(msg, dict):
                            messages.append(msg)
                        elif hasattr(msg, "role") and hasattr(msg, "content"):
                            messages.append({
                                "role": msg.role,
                                "content": msg.content if isinstance(msg.content, str) else str(msg.content),
                            })
            except Exception:
                logger.debug("Failed to load existing messages for conversation %s", conversation_id)

        # Add user message
        messages.append({"role": "user", "content": message})

        logger.debug("chat_sync: user_id=%s, conv_id=%s, msg_len=%d",
                      user_id, conversation_id, len(message))

        try:
            result = self.engine.run_turn(messages, user_id=user_id)
        except Exception:
            logger.exception("chat_sync: engine.run_turn failed")
            return {
                "response": "",
                "conversation_id": conversation_id,
                "error": "Internal error during chat processing",
                "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
            }

        # Save to conversation store if available
        if self.conv_store:
            try:
                self.conv_store.ensure_conversation(conversation_id, interface="rest_api")
                self.conv_store.add_message(conversation_id, "user", message)
                if result.text:
                    self.conv_store.add_message(conversation_id, "assistant", result.text)
            except Exception:
                logger.debug("Failed to save messages for conversation %s", conversation_id)

        response = {
            "response": result.text or "",
            "conversation_id": conversation_id,
            "usage": {
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cost_usd": result.cost_usd,
            },
        }

        if result.error:
            response["error"] = result.error

        logger.debug("chat_sync complete: tokens_in=%d, tokens_out=%d",
                      result.input_tokens, result.output_tokens)

        return response

    def chat_stream(
        self,
        message: str,
        user_id: str = "default",
        conversation_id: str = None,
    ) -> Generator:
        """SSE streaming chat. Yields (event_type, data) tuples.

        Args:
            message: User message text.
            user_id: User identifier for usage tracking.
            conversation_id: Optional conversation ID for persistence.

        Yields:
            (event_type, data) tuples where:
                - ("data", "text chunk") for text deltas
                - ("tool_start", {"tool": "name"}) when tool execution begins
                - ("tool_end", {"tool": "name"}) when tool execution ends
                - ("done", {"usage": {...}, "conversation_id": "..."}) on completion
                - ("error", {"message": "..."}) on error
        """
        if not conversation_id:
            conversation_id = str(uuid.uuid4())

        messages = [{"role": "user", "content": message}]

        logger.debug("chat_stream: user_id=%s, conv_id=%s", user_id, conversation_id)

        try:
            collected_text = []

            for event in self.engine.run_turn_stream(messages, user_id=user_id):
                if event.type == "text_delta":
                    collected_text.append(event.data)
                    yield ("data", event.data)

                elif event.type == "tool_use_start":
                    tool_name = ""
                    if isinstance(event.data, dict):
                        tool_name = event.data.get("name", "")
                    yield ("tool_start", {"tool": tool_name})

                elif event.type == "tool_use_end":
                    tool_name = ""
                    if isinstance(event.data, dict):
                        tool_name = event.data.get("name", "")
                    yield ("tool_end", {"tool": tool_name})

                elif event.type == "tool_result":
                    # Tool result events - pass through as tool_end
                    tool_name = ""
                    if isinstance(event.data, dict):
                        tool_name = event.data.get("name", "")
                    yield ("tool_end", {"tool": tool_name})

                elif event.type == "turn_complete":
                    # Final event with TurnResult
                    turn_result = event.data
                    usage = {
                        "input_tokens": turn_result.input_tokens,
                        "output_tokens": turn_result.output_tokens,
                        "cost_usd": turn_result.cost_usd,
                    }

                    # Save to conversation store
                    if self.conv_store:
                        try:
                            self.conv_store.ensure_conversation(conversation_id, interface="rest_api")
                            self.conv_store.add_message(conversation_id, "user", message)
                            full_text = "".join(collected_text) or turn_result.text or ""
                            if full_text:
                                self.conv_store.add_message(conversation_id, "assistant", full_text)
                        except Exception:
                            logger.debug("Failed to save streamed messages for conversation %s", conversation_id)

                    done_data = {
                        "usage": usage,
                        "conversation_id": conversation_id,
                    }
                    if turn_result.error:
                        done_data["error"] = turn_result.error

                    yield ("done", done_data)

                elif event.type == "error":
                    error_msg = event.data if isinstance(event.data, str) else str(event.data)
                    yield ("error", {"message": error_msg})

        except Exception as e:
            logger.exception("chat_stream: error during streaming")
            yield ("error", {"message": str(e)})
