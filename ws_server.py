#!/usr/bin/env python3
"""
WebSocket 서버 인터페이스 - flux-openclaw AI 챗봇
켈리(AI 어시스턴트)를 WebSocket으로 접근할 수 있게 제공합니다.

보안 기능:
- Origin 검증 (CVE-2026-25253 방지)
- 토큰 인증 (쿼리 파라미터)
- 로컬 바인딩 (127.0.0.1)
- Rate Limiting (분당 30 메시지)
"""

import os
import sys
import json
import hmac
import asyncio
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
from collections import defaultdict

from dotenv import load_dotenv
import anthropic

# LLM Provider 폴백 지원
try:
    from openclaw.llm_provider import get_provider
    _use_provider = True
except ImportError:
    _use_provider = False

try:
    import websockets
    from websockets.server import serve
except ImportError:
    print("오류: websockets 라이브러리가 설치되지 않았습니다.")
    print("설치 명령: pip install websockets")
    sys.exit(1)

load_dotenv()

# core.py에서 공유 모듈 임포트
from core import (
    ToolManager, _mask_secrets,
    load_usage, check_daily_limit,
    load_system_prompt,
)
from openclaw.conversation_engine import ConversationEngine
from config import get_config
from openclaw.conversation_store import ConversationStore


def _get_auth_middleware():
    """Return AuthMiddleware if auth_enabled, else None."""
    try:
        from config import get_config as _cfg
        cfg = _cfg()
        if cfg.auth_enabled:
            from openclaw.auth import UserStore, AuthMiddleware
            store = UserStore(cfg.auth_db_path)
            return AuthMiddleware(store)
    except Exception:
        pass
    return None


# === 설정 ===
WS_AUTH_TOKEN = os.environ.get("WS_AUTH_TOKEN")
if not WS_AUTH_TOKEN:
    print("오류: WS_AUTH_TOKEN 환경변수가 설정되지 않았습니다.")
    print(".env 파일에 WS_AUTH_TOKEN=your-secret-token 을 추가하세요.")
    sys.exit(1)
if len(WS_AUTH_TOKEN) < 32:
    print("오류: WS_AUTH_TOKEN이 너무 짧습니다 (최소 32자 필요).")
    sys.exit(1)

WS_ALLOWED_ORIGINS = os.environ.get(
    "WS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000"
).split(",")
WS_ALLOWED_ORIGINS = [origin.strip() for origin in WS_ALLOWED_ORIGINS]

WS_PORT = int(os.environ.get("WS_PORT", "8765"))
WS_HOST = os.environ.get("WS_HOST", "127.0.0.1")

# 보안 경고: 비-로컬 바인딩 감지
if WS_HOST not in ("127.0.0.1", "::1", "localhost"):
    print(f" [보안 경고] WS_HOST={WS_HOST} — 로컬이 아닌 주소에 바인딩됩니다!")
    print(f" [보안 경고] 외부 네트워크에서 AI 에이전트에 접근할 수 있습니다.")
    if not os.environ.get("WS_ALLOW_REMOTE"):
        print(f" [보안 경고] 허용하려면 WS_ALLOW_REMOTE=true를 설정하세요.")
        sys.exit(1)

# Rate Limiting 설정
RATE_LIMIT_MAX_MESSAGES = 30
RATE_LIMIT_WINDOW = timedelta(minutes=1)
MAX_CONNECTIONS = 10

# API 일일 호출 제한
MAX_DAILY_CALLS = max(1, min(int(os.environ.get("MAX_DAILY_CALLS", "100")), 10000))


# === Rate Limiting ===
class RateLimiter:
    """연결별 Rate Limiting"""

    def __init__(self):
        self.message_times = defaultdict(list)

    def check_rate_limit(self, connection_id):
        """Rate limit 확인. 초과 시 False 반환"""
        now = datetime.now()
        times = self.message_times[connection_id]
        times = [t for t in times if now - t < RATE_LIMIT_WINDOW]
        self.message_times[connection_id] = times
        if len(times) >= RATE_LIMIT_MAX_MESSAGES:
            return False
        times.append(now)
        return True

    def cleanup_connection(self, connection_id):
        """연결 종료 시 데이터 정리"""
        if connection_id in self.message_times:
            del self.message_times[connection_id]

    def cleanup_stale(self):
        """오래된 연결 데이터 정리 (비정상 종료 대비)"""
        now = datetime.now()
        stale = [cid for cid, times in self.message_times.items()
                 if not times or (now - times[-1]) > timedelta(minutes=5)]
        for cid in stale:
            del self.message_times[cid]


# === WebSocket 서버 ===
class ChatbotServer:
    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")

        # LLM Provider 초기화 (폴백: Anthropic 직접 사용)
        self.provider = None
        self.client = None

        if _use_provider:
            try:
                self.provider = get_provider()
                print(f" [LLM] {self.provider.PROVIDER_NAME} ({self.provider.model})")
            except Exception as e:
                print(f" [LLM] 프로바이더 초기화 실패, Anthropic 직접 사용: {e}")
                self.provider = None

        if self.provider is None:
            if not self.api_key:
                print("오류: ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
                sys.exit(1)
            self.client = anthropic.Anthropic(api_key=self.api_key)

        self.tool_mgr = ToolManager()
        self.rate_limiter = RateLimiter()

        # 시스템 프롬프트 구성 (core.py 통합 함수 사용)
        self.system_prompt = load_system_prompt()

        # ConversationEngine 초기화
        self.engine = ConversationEngine(
            provider=self.provider,
            client=self.client,
            tool_mgr=self.tool_mgr,
            system_prompt=self.system_prompt,
        )

        # ConversationStore 초기화
        try:
            cfg = get_config()
            self.conv_store = ConversationStore(cfg.conversation_db_path)
        except Exception:
            self.conv_store = None

        # 인증 미들웨어 (auth_enabled=True인 경우에만 활성)
        self.auth_middleware = _get_auth_middleware()

        # 활성 연결 추적
        self.active_connections = set()

        print(f" [시스템 프롬프트] {len(self.system_prompt)}자 로드됨")
        print(f" [도구] {len(self.tool_mgr.functions)}개 로드됨: {', '.join(self.tool_mgr.functions.keys())}")

    def _validate_origin(self, origin):
        """Origin 헤더 검증 (CVE-2026-25253 방지)"""
        if not origin:
            return False
        parsed = urlparse(origin)
        origin_normalized = f"{parsed.scheme}://{parsed.netloc}"
        return origin_normalized in WS_ALLOWED_ORIGINS

    def _validate_token(self, token):
        """인증 토큰 검증 (타이밍 공격 방지)"""
        if not token:
            return False
        return hmac.compare_digest(token, WS_AUTH_TOKEN)

    async def _send_json(self, websocket, data):
        """JSON 메시지 전송 (비밀 마스킹 적용)"""
        json_str = json.dumps(data, ensure_ascii=False)
        masked_str = _mask_secrets(json_str)
        await websocket.send(masked_str)

    async def _send_error(self, websocket, message):
        """에러 메시지 전송"""
        await self._send_json(websocket, {
            "type": "error",
            "content": message
        })

    async def _process_message(self, websocket, user_message, messages, conversation_id=None, user_id="default"):
        """사용자 메시지 처리 및 응답 생성"""
        if not check_daily_limit(MAX_DAILY_CALLS):
            usage_data = load_usage()
            await self._send_error(
                websocket,
                f"일일 API 호출 제한에 도달했습니다 ({usage_data['calls']}/{MAX_DAILY_CALLS}). 내일 다시 시도하세요."
            )
            return

        messages.append({"role": "user", "content": user_message})

        # ConversationStore에 사용자 메시지 저장
        if self.conv_store and conversation_id:
            try:
                self.conv_store.add_message(conversation_id, "user", user_message)
            except Exception:
                pass

        try:
            cfg = get_config()
            if cfg.streaming_enabled and hasattr(self.engine, 'run_turn_stream_async'):
                # 스트리밍 모드
                await websocket.send(json.dumps({"type": "stream_start"}))
                result = None
                async for event in self.engine.run_turn_stream_async(messages, user_id=user_id):
                    if event.type == "text_delta":
                        await websocket.send(json.dumps({"type": "stream_delta", "text": event.data}))
                    elif event.type == "tool_use_start":
                        await websocket.send(json.dumps({"type": "stream_tool_start", "tool": event.data.get("name", "")}))
                    elif event.type == "tool_use_end":
                        await websocket.send(json.dumps({"type": "stream_tool_end", "tool": event.data.get("name", "")}))
                    elif event.type == "turn_complete":
                        result = event.data
                if result is None:
                    result = await self.engine.run_turn_async(messages, user_id=user_id)

                await websocket.send(json.dumps({
                    "type": "stream_end",
                    "usage": {
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "cost_usd": result.cost_usd,
                    }
                }))
            else:
                # 비스트리밍 모드
                result = await self.engine.run_turn_async(messages, user_id=user_id)

            if result.error and not result.text:
                await self._send_error(websocket, result.error)
                return

            if not result.text:
                await self._send_error(websocket, "응답 생성에 실패했습니다.")
                return

            # 비스트리밍인 경우에만 전체 응답 전송 (스트리밍은 이미 전송됨)
            if not (cfg.streaming_enabled and hasattr(self.engine, 'run_turn_stream_async')):
                await self._send_json(websocket, {
                    "type": "response",
                    "content": result.text,
                    "usage": {
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "cost_usd": result.cost_usd,
                    }
                })

            # ConversationStore에 AI 응답 저장
            if self.conv_store and conversation_id and result.text:
                try:
                    self.conv_store.add_message(conversation_id, "assistant", result.text, token_count=result.output_tokens)
                except Exception:
                    pass

        except Exception as e:
            print(f" [오류] {_mask_secrets(str(e))}")
            await self._send_error(websocket, "요청 처리 중 오류가 발생했습니다.")

    async def handle_connection(self, websocket):
        """WebSocket 연결 핸들러"""
        connection_id = id(websocket)
        remote_addr = websocket.remote_address

        try:
            origin = websocket.request_headers.get("Origin")
            if not self._validate_origin(origin):
                print(f" [차단] 잘못된 Origin: {origin} (from {remote_addr})")
                await self._send_error(websocket, "접근이 거부되었습니다: 잘못된 Origin")
                await websocket.close()
                return

            auth_header = websocket.request_headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
            else:
                ws_path = websocket.path if hasattr(websocket, "path") else ""
                query_params = parse_qs(urlparse(ws_path).query)
                token = query_params.get("token", [None])[0]

            if not self._validate_token(token):
                print(f" [차단] 잘못된 토큰 (from {remote_addr})")
                await self._send_error(websocket, "접근이 거부되었습니다: 인증 실패")
                await websocket.close()
                return

            # 사용자 식별 (auth_enabled인 경우 토큰으로 resolve)
            user_id = "default"
            if self.auth_middleware is not None and token:
                try:
                    ctx = self.auth_middleware.authenticate(token, interface="web", source_ip=str(remote_addr))
                    if ctx is not None:
                        user_id = ctx.user_id
                except Exception:
                    pass  # resolve 실패 시 default 유지

            if len(self.active_connections) >= MAX_CONNECTIONS:
                print(f" [차단] 동시 연결 제한 초과 ({MAX_CONNECTIONS}): {remote_addr}")
                await self._send_error(websocket, "서버 동시 연결 제한에 도달했습니다. 잠시 후 다시 시도하세요.")
                await websocket.close()
                return

            print(f" [연결] 새 클라이언트: {remote_addr} (origin: {origin})")
            self.active_connections.add(connection_id)

            await self._send_json(websocket, {
                "type": "info",
                "content": "켈리 WebSocket 서버에 연결되었습니다."
            })

            messages = []

            # ConversationStore에 대화 생성
            conversation_id = None
            if self.conv_store:
                try:
                    conv = self.conv_store.create_conversation(interface="web", user_id=user_id)
                    conversation_id = conv.id
                except Exception:
                    pass

            async for raw_message in websocket:
                try:
                    if not self.rate_limiter.check_rate_limit(connection_id):
                        await self._send_error(websocket, "Rate limit exceeded. 잠시 후 다시 시도하세요.")
                        continue

                    message = json.loads(raw_message)
                    msg_type = message.get("type")
                    content = message.get("content", "").strip()

                    if msg_type == "message":
                        if not content:
                            await self._send_error(websocket, "빈 메시지는 처리할 수 없습니다.")
                            continue
                        if len(content) > 10000:
                            await self._send_error(websocket, "메시지가 너무 깁니다 (최대 10,000자).")
                            continue

                        print(f" [수신] {remote_addr}: {content[:50]}...")
                        await self._process_message(websocket, content, messages, conversation_id, user_id=user_id)

                    elif msg_type == "ping":
                        await self._send_json(websocket, {"type": "pong"})

                    else:
                        await self._send_error(websocket, f"알 수 없는 메시지 타입: {msg_type}")

                except json.JSONDecodeError:
                    await self._send_error(websocket, "잘못된 JSON 형식입니다.")
                except Exception as e:
                    error_msg = _mask_secrets(str(e))
                    print(f" [오류] 메시지 처리 실패: {error_msg}")
                    await self._send_error(websocket, f"메시지 처리 중 오류가 발생했습니다.")

        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            error_msg = _mask_secrets(str(e))
            print(f" [오류] 연결 처리 실패: {error_msg}")
        finally:
            self.active_connections.discard(connection_id)
            self.rate_limiter.cleanup_connection(connection_id)
            print(f" [종료] 클라이언트 연결 종료: {remote_addr}")

    async def start(self):
        """서버 시작"""
        print(f"\n켈리 WebSocket 서버 시작")
        print(f" - 주소: ws://{WS_HOST}:{WS_PORT}")
        print(f" - 허용 Origin: {', '.join(WS_ALLOWED_ORIGINS)}")
        print(f" - Rate Limit: {RATE_LIMIT_MAX_MESSAGES} 메시지/분")
        print(f" - 일일 API 제한: {MAX_DAILY_CALLS}회")
        print(f"\n종료하려면 Ctrl+C를 누르세요.\n")

        async def _periodic_cleanup():
            while True:
                await asyncio.sleep(300)
                self.rate_limiter.cleanup_stale()

        async with serve(self.handle_connection, WS_HOST, WS_PORT, max_size=1_048_576):
            asyncio.create_task(_periodic_cleanup())
            await asyncio.Future()


async def main():
    """메인 함수"""
    server = ChatbotServer()
    try:
        await server.start()
    except KeyboardInterrupt:
        print("\n\n서버를 종료합니다...")
        usage_data = load_usage()
        print(f" [오늘 사용량] API 호출: {usage_data['calls']}회, "
              f"입력: {usage_data['input_tokens']} 토큰, "
              f"출력: {usage_data['output_tokens']} 토큰")


if __name__ == "__main__":
    asyncio.run(main())
