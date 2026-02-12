#!/usr/bin/env python3
"""
flux-openclaw Slack 봇 인터페이스
Socket Mode를 사용하여 웹서버 없이 Slack과 통신합니다.

보안: 허용된 채널만 접근, 위험한 도구는 차단
"""

import os
import re
import sys
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

from dotenv import load_dotenv

try:
    from slack_bolt.async_app import AsyncApp
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
except ImportError:
    print("오류: slack_bolt 라이브러리가 설치되지 않았습니다.")
    print("설치 명령: pip install slack-bolt aiohttp")
    sys.exit(1)

# core.py에서 공유 모듈 임포트
from core import (
    ToolManager, _mask_secrets,
    load_usage,
    load_system_prompt,
)
from conversation_engine import ConversationEngine

# llm_provider 지원 (없으면 직접 anthropic 사용)
try:
    from llm_provider import get_provider
except ImportError:
    get_provider = None

load_dotenv()

# 로깅 설정
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============================================================
# 환경변수 및 설정
# ============================================================

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")

# 허용된 채널 목록 (비어있으면 모든 채널 허용)
_allowed_channels_raw = os.environ.get("SLACK_ALLOWED_CHANNELS", "").strip()
SLACK_ALLOWED_CHANNELS: set = set()
if _allowed_channels_raw:
    SLACK_ALLOWED_CHANNELS = {ch.strip() for ch in _allowed_channels_raw.split(",") if ch.strip()}

# LLM 설정
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514")

# Slack에서 차단할 위험한 도구 목록
RESTRICTED_TOOLS = {"save_text_file", "screen_capture", "list_files"}

# 일일 API 호출 제한
MAX_DAILY_CALLS = 100

# 사용자별 Rate Limiting (분당 메시지 수)
USER_RATE_LIMIT = 10
_user_msg_times: Dict[str, List[datetime]] = {}

# 스레드별 대화 히스토리 (key: "channel:thread_ts" 또는 "channel:user:dm")
thread_conversations: Dict[str, List[dict]] = {}

# 대화 히스토리 최대 길이
MAX_HISTORY = 50

# Slack 메시지 최대 길이
SLACK_MAX_MESSAGE_LEN = 4000

# ============================================================
# 글로벌 싱글톤
# ============================================================

_tool_mgr: Optional[ToolManager] = None
_provider = None
_system_prompt = ""
_bot_user_id: Optional[str] = None
_engine: Optional[ConversationEngine] = None

# ============================================================
# Slack 앱 초기화
# ============================================================

app = AsyncApp(token=SLACK_BOT_TOKEN)


# ============================================================
# 유틸리티 함수
# ============================================================

def _get_conversation_key(channel: str, thread_ts: Optional[str], user: str) -> str:
    """대화 키 생성 (스레드 기반)"""
    if thread_ts:
        return f"{channel}:{thread_ts}"
    return f"{channel}:{user}:dm"


def _is_channel_allowed(channel: str) -> bool:
    """채널 접근 허용 여부 확인"""
    if not SLACK_ALLOWED_CHANNELS:
        return True
    return channel in SLACK_ALLOWED_CHANNELS


def _is_tool_allowed(tool_name: str) -> bool:
    """도구가 Slack 봇에서 허용되는지 확인"""
    return tool_name not in RESTRICTED_TOOLS


def _check_rate_limit(user: str) -> bool:
    """사용자별 Rate Limiting (분당 메시지 수 제한). 허용 시 True 반환"""
    now = datetime.now()
    if user in _user_msg_times:
        _user_msg_times[user] = [
            t for t in _user_msg_times[user]
            if (now - t).total_seconds() < 60
        ]
        if not _user_msg_times[user]:
            del _user_msg_times[user]

    times = _user_msg_times.get(user, [])
    if len(times) >= USER_RATE_LIMIT:
        return False

    times.append(now)
    _user_msg_times[user] = times
    return True


def _check_daily_limit():
    """일일 API 호출 제한 확인. (허용 여부, 현재 호출 수, 최대 호출 수) 반환"""
    usage = load_usage()
    today = datetime.now().strftime("%Y-%m-%d")
    if usage.get("date") != today:
        return True, 0, MAX_DAILY_CALLS
    current_calls = usage.get("calls", 0)
    return current_calls < MAX_DAILY_CALLS, current_calls, MAX_DAILY_CALLS


def _split_message(text: str, max_len: int = SLACK_MAX_MESSAGE_LEN) -> List[str]:
    """긴 메시지를 max_len 단위로 분할"""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # 줄바꿈 기준으로 자연스럽게 분할 시도
        split_pos = text.rfind("\n", 0, max_len)
        if split_pos <= 0:
            split_pos = max_len
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")
    return chunks


def _strip_bot_mention(text: str) -> str:
    """메시지에서 봇 멘션(<@BOT_ID>) 패턴 제거"""
    return re.sub(r"<@\w+>", "", text).strip()


def load_slack_system_prompt() -> str:
    """Slack 전용 시스템 프롬프트"""
    extra = (
        "\n\n## Slack 봇 모드\n"
        "- 현재 Slack 봇으로 대화하고 있습니다.\n"
        f"- 보안상 다음 도구는 사용할 수 없습니다: {', '.join(RESTRICTED_TOOLS)}\n"
        "- 응답은 간결하게 유지하세요 (Slack 메시지 제한 고려).\n"
        "- 스레드 내에서 대화 맥락을 유지합니다.\n"
    )
    return load_system_prompt(extra_suffix=extra)


# ============================================================
# 메시지 처리 핵심 로직
# ============================================================

async def _process_message(channel: str, user: str, text: str,
                           thread_ts: str, say) -> None:
    """메시지 처리 핵심 로직

    Args:
        channel: Slack 채널 ID
        user: 사용자 ID
        text: 사용자 메시지 (멘션 제거 후)
        thread_ts: 스레드 타임스탬프 (스레드 기반 대화 키)
        say: Slack say() 함수
    """
    # Rate limiting
    if not _check_rate_limit(user):
        await say(
            text="메시지를 너무 빠르게 보내고 있습니다. 잠시 후 다시 시도해주세요.",
            thread_ts=thread_ts,
        )
        return

    # 일일 API 호출 제한 확인
    allowed, current_calls, max_calls = _check_daily_limit()
    if not allowed:
        await say(
            text=(
                f"일일 API 호출 제한에 도달했습니다.\n"
                f"오늘 {current_calls}/{max_calls}회 사용\n"
                f"내일 다시 시도해주세요."
            ),
            thread_ts=thread_ts,
        )
        return

    # 메시지 길이 제한
    if len(text) > 10000:
        await say(
            text="메시지가 너무 깁니다 (최대 10,000자).",
            thread_ts=thread_ts,
        )
        return

    # 대화 히스토리 관리
    conv_key = _get_conversation_key(channel, thread_ts, user)
    if conv_key not in thread_conversations:
        thread_conversations[conv_key] = []

    messages = thread_conversations[conv_key]
    messages.append({"role": "user", "content": text})

    try:
        global _engine
        result = await _engine.run_turn_async(messages)

        if result.error:
            logger.warning(f" [AI] {conv_key}: {result.error}")

        final_text = result.text or result.error or ""

        # 응답 전송 (4000자 분할)
        if final_text:
            chunks = _split_message(final_text)
            for chunk in chunks:
                await say(text=chunk, thread_ts=thread_ts)
        else:
            await say(text="(응답 없음)", thread_ts=thread_ts)

        # 히스토리 업데이트
        thread_conversations[conv_key] = messages

    except Exception as e:
        logger.error(f" [오류] 메시지 처리 실패: {_mask_secrets(str(e))}")
        await say(
            text="오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
            thread_ts=thread_ts,
        )


# ============================================================
# 이벤트 핸들러
# ============================================================

@app.event("app_mention")
async def handle_mention(event, say):
    """@멘션 처리"""
    channel = event.get("channel")
    user = event.get("user")
    text = event.get("text", "")
    thread_ts = event.get("thread_ts") or event.get("ts")

    if not _is_channel_allowed(channel):
        return

    # 봇 멘션 제거
    text = _strip_bot_mention(text)
    if not text:
        return

    await _process_message(channel, user, text, thread_ts, say)


@app.event("message")
async def handle_dm(event, say):
    """DM (Direct Message) 처리"""
    # DM인 경우에만 처리
    if event.get("channel_type") != "im":
        return
    # 봇 메시지, 변경 이벤트 등 서브타입이 있는 메시지는 무시
    if event.get("subtype"):
        return
    # 봇 자신의 메시지 무시
    if event.get("bot_id"):
        return

    channel = event.get("channel")
    user = event.get("user")
    text = event.get("text", "")
    thread_ts = event.get("thread_ts") or event.get("ts")

    if not text.strip():
        return

    await _process_message(channel, user, text, thread_ts, say)


# ============================================================
# 슬래시 커맨드
# ============================================================

@app.command("/kelly-help")
async def help_command(ack, respond):
    """도움말 슬래시 커맨드"""
    await ack()
    help_text = (
        "*켈리 봇 사용법*\n\n"
        "1. 채널에서 `@켈리`를 멘션하면 AI가 답변합니다.\n"
        "2. DM으로 직접 메시지를 보낼 수도 있습니다.\n"
        "3. 스레드 내에서 대화 맥락이 유지됩니다.\n"
        "4. 파일 읽기, 날씨, 검색 등의 도구를 자동으로 사용합니다.\n\n"
        "*슬래시 커맨드:*\n"
        "`/kelly-help` - 이 도움말\n"
        "`/kelly-reset` - 현재 스레드의 대화 기록 초기화\n"
        "`/kelly-usage` - API 사용량 확인\n\n"
        f"*보안상 제한된 도구:* {', '.join(RESTRICTED_TOOLS)}"
    )
    await respond(help_text)


@app.command("/kelly-reset")
async def reset_command(ack, respond, command):
    """대화 기록 초기화 슬래시 커맨드"""
    await ack()
    channel = command.get("channel_id", "")
    user = command.get("user_id", "")

    # 해당 사용자/채널 관련 대화 키 찾아서 삭제
    keys_to_remove = [
        key for key in thread_conversations
        if key.startswith(f"{channel}:") or key.endswith(f":{user}:dm")
    ]
    for key in keys_to_remove:
        del thread_conversations[key]

    count = len(keys_to_remove)
    if count > 0:
        await respond(f"대화 기록이 초기화되었습니다. ({count}개 세션 삭제)")
    else:
        await respond("초기화할 대화 기록이 없습니다.")


@app.command("/kelly-usage")
async def usage_command(ack, respond):
    """API 사용량 확인 슬래시 커맨드"""
    await ack()
    usage = load_usage()
    today = datetime.now().strftime("%Y-%m-%d")

    if usage.get("date") != today:
        msg = f"오늘({today})은 아직 API 호출이 없습니다.\n제한: {MAX_DAILY_CALLS}회/일"
    else:
        calls = usage.get("calls", 0)
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        remaining = MAX_DAILY_CALLS - calls
        msg = (
            f"*오늘의 API 사용량* ({today})\n\n"
            f"API 호출: {calls}/{MAX_DAILY_CALLS}회\n"
            f"남은 호출: {remaining}회\n"
            f"입력 토큰: {input_tokens:,}\n"
            f"출력 토큰: {output_tokens:,}\n"
            f"총 토큰: {input_tokens + output_tokens:,}"
        )

    await respond(msg)


# ============================================================
# 메인 진입점
# ============================================================

async def main():
    """메인 함수"""
    global _tool_mgr, _provider, _system_prompt, _bot_user_id, _engine

    if not SLACK_BOT_TOKEN:
        print("[오류] SLACK_BOT_TOKEN 환경변수가 설정되지 않았습니다.")
        print("[안내] .env 파일에 SLACK_BOT_TOKEN=xoxb-... 을 추가하세요.")
        sys.exit(1)

    if not SLACK_APP_TOKEN:
        print("[오류] SLACK_APP_TOKEN 환경변수가 설정되지 않았습니다.")
        print("[안내] .env 파일에 SLACK_APP_TOKEN=xapp-... 을 추가하세요.")
        sys.exit(1)

    # 도구 관리자 초기화
    _tool_mgr = ToolManager()

    # LLM Provider 초기화
    _llm_provider = None
    _llm_client = None

    if get_provider is not None:
        try:
            _llm_provider = get_provider()
            _provider = _llm_provider
            logger.info(f" [LLM] llm_provider 사용 (provider={LLM_PROVIDER})")
        except Exception as e:
            logger.warning(f" [LLM] llm_provider 초기화 실패: {e}, anthropic 직접 사용")
            _llm_provider = None
    else:
        logger.info(" [LLM] llm_provider 모듈 없음, anthropic 직접 사용")

    # anthropic 직접 사용 시 클라이언트 생성
    if _llm_provider is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("[오류] ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
            sys.exit(1)
        import anthropic
        _llm_client = anthropic.Anthropic(api_key=api_key)
        _provider = _llm_client
        logger.info(f" [LLM] anthropic 직접 클라이언트 생성 (model={LLM_MODEL})")

    # 시스템 프롬프트 로드
    _system_prompt = load_slack_system_prompt()

    # ConversationEngine 초기화
    _engine = ConversationEngine(
        provider=_llm_provider,
        client=_llm_client,
        tool_mgr=_tool_mgr,
        system_prompt=_system_prompt,
        restricted_tools=RESTRICTED_TOOLS,
    )

    # 시작 정보 출력
    logger.info(" [시작] 켈리 Slack 봇을 시작합니다...")
    if SLACK_ALLOWED_CHANNELS:
        logger.info(f" [보안] 허용된 채널: {len(SLACK_ALLOWED_CHANNELS)}개")
    else:
        logger.info(" [보안] 모든 채널 허용")
    logger.info(f" [보안] 제한된 도구: {', '.join(RESTRICTED_TOOLS)}")
    logger.info(f" [제한] 일일 API 호출 상한: {MAX_DAILY_CALLS}회")
    logger.info(f" [제한] 사용자 Rate Limit: {USER_RATE_LIMIT}회/분")
    logger.info(f" [LLM] 모델: {LLM_MODEL}")

    # Socket Mode 핸들러 시작
    handler = AsyncSocketModeHandler(app, SLACK_APP_TOKEN)
    logger.info(" [실행] 봇이 실행 중입니다. Ctrl+C로 종료하세요.")
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
