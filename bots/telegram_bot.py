#!/usr/bin/env python3
"""
flux-openclaw 텔레그램 봇 인터페이스
보안: 허용된 사용자만 접근, 위험한 도구는 차단
"""

import os
import sys
import asyncio
import logging
from datetime import datetime
from typing import Dict, List

from dotenv import load_dotenv
import anthropic
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# core.py에서 공유 모듈 임포트
from core import (
    ToolManager, _mask_secrets,
    load_usage,
    load_system_prompt,
)
from conversation_engine import ConversationEngine

# LLM Provider 폴백 지원
try:
    from llm_provider import get_provider
    _use_provider = True
except ImportError:
    _use_provider = False

load_dotenv()

# 로깅 설정
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 환경변수 로드
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_ALLOWED_USERS = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# 허용된 사용자 목록 (chat_id)
ALLOWED_CHAT_IDS = set()
if TELEGRAM_ALLOWED_USERS:
    try:
        ALLOWED_CHAT_IDS = {int(x.strip()) for x in TELEGRAM_ALLOWED_USERS.split(",")}
        logger.info(f" [보안] 허용된 사용자: {len(ALLOWED_CHAT_IDS)}명")
    except ValueError:
        logger.error(" [오류] TELEGRAM_ALLOWED_USERS 형식 오류. 쉼표로 구분된 숫자여야 합니다.")
        sys.exit(1)

# 텔레그램에서 차단할 위험한 도구 목록
RESTRICTED_TOOLS = {
    "save_text_file",
    "screen_capture",
    "list_files",
}

# 일일 API 호출 제한
MAX_DAILY_CALLS = 100

# 사용자별 Rate Limiting
USER_RATE_LIMIT = 10
_user_msg_times: Dict[int, List[datetime]] = {}

# 사용자별 대화 히스토리
user_conversations: Dict[int, List[dict]] = {}

# 글로벌 싱글톤
_tool_mgr = None
_provider = None
_client = None
_system_prompt = ""
_engine = None


def load_telegram_system_prompt():
    """텔레그램 전용 시스템 프롬프트"""
    extra = (
        "\n\n## 텔레그램 봇 모드\n"
        "- 현재 텔레그램 봇으로 대화하고 있습니다.\n"
        f"- 보안상 다음 도구는 사용할 수 없습니다: {', '.join(RESTRICTED_TOOLS)}\n"
        "- 응답은 간결하게 유지하세요 (텔레그램 메시지 제한 고려).\n"
    )
    return load_system_prompt(extra_suffix=extra)


def check_telegram_daily_limit():
    """텔레그램용 일일 제한 확인. (허용 여부, 현재 호출 수, 최대 호출 수) 반환"""
    usage = load_usage()
    today = datetime.now().strftime("%Y-%m-%d")
    if usage.get("date") != today:
        return True, 0, MAX_DAILY_CALLS
    current_calls = usage.get("calls", 0)
    return current_calls < MAX_DAILY_CALLS, current_calls, MAX_DAILY_CALLS


def is_tool_allowed(tool_name: str) -> bool:
    """도구가 텔레그램에서 허용되는지 확인"""
    return tool_name not in RESTRICTED_TOOLS


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """시작 명령어"""
    if not update.message:
        return
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_CHAT_IDS:
        logger.warning(f" [보안] 미등록 사용자 접근 시도: {chat_id}")
        return
    welcome_msg = (
        "안녕하세요! 켈리 봇입니다.\n\n"
        "사용 가능한 명령어:\n"
        "/start - 시작 메시지\n"
        "/help - 도움말\n"
        "/reset - 대화 기록 초기화\n"
        "/usage - 오늘의 API 사용량\n\n"
        "메시지를 보내면 Claude AI가 답변합니다."
    )
    await update.message.reply_text(welcome_msg)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """도움말 명령어"""
    if not update.message:
        return
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_CHAT_IDS:
        logger.warning(f" [보안] 미등록 사용자 접근 시도: {chat_id}")
        return
    help_msg = (
        "켈리 봇 사용법:\n\n"
        "1. 일반 메시지를 보내면 Claude AI가 답변합니다.\n"
        "2. 파일 읽기, 날씨, 검색 등의 도구를 자동으로 사용합니다.\n"
        "3. 대화 기록은 세션별로 유지됩니다.\n\n"
        "명령어:\n"
        "/start - 시작 메시지\n"
        "/help - 이 도움말\n"
        "/reset - 대화 기록 초기화\n"
        "/usage - API 사용량 확인\n\n"
        f"⚠️ 보안상 제한된 도구: {', '.join(RESTRICTED_TOOLS)}"
    )
    await update.message.reply_text(help_msg)


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """대화 기록 초기화"""
    if not update.message:
        return
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_CHAT_IDS:
        logger.warning(f" [보안] 미등록 사용자 접근 시도: {chat_id}")
        return
    if chat_id in user_conversations:
        del user_conversations[chat_id]
    await update.message.reply_text("대화 기록이 초기화되었습니다.")


async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """API 사용량 확인"""
    if not update.message:
        return
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_CHAT_IDS:
        logger.warning(f" [보안] 미등록 사용자 접근 시도: {chat_id}")
        return
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
            f"📊 오늘의 API 사용량 ({today})\n\n"
            f"API 호출: {calls}/{MAX_DAILY_CALLS}회\n"
            f"남은 호출: {remaining}회\n"
            f"입력 토큰: {input_tokens:,}\n"
            f"출력 토큰: {output_tokens:,}\n"
            f"총 토큰: {input_tokens + output_tokens:,}"
        )
    await update.message.reply_text(msg)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """일반 메시지 처리"""
    if not update.message:
        return
    chat_id = update.effective_chat.id

    if chat_id not in ALLOWED_CHAT_IDS:
        logger.warning(f" [보안] 미등록 사용자 메시지 무시: {chat_id} - {_mask_secrets(update.message.text)}")
        return

    user_message = update.message.text

    # API 호출 제한 확인
    allowed, current_calls, max_calls = check_telegram_daily_limit()
    if not allowed:
        await update.message.reply_text(
            f"⚠️ 일일 API 호출 제한에 도달했습니다.\n"
            f"오늘 {current_calls}/{max_calls}회 사용\n"
            f"내일 다시 시도해주세요."
        )
        return

    # 사용자별 Rate Limiting
    now = datetime.now()
    if chat_id in _user_msg_times:
        _user_msg_times[chat_id] = [t for t in _user_msg_times[chat_id] if (now - t).total_seconds() < 60]
        if not _user_msg_times[chat_id]:
            del _user_msg_times[chat_id]
    times = _user_msg_times.get(chat_id, [])
    if len(times) >= USER_RATE_LIMIT:
        await update.message.reply_text("메시지를 너무 빠르게 보내고 있습니다. 잠시 후 다시 시도해주세요.")
        return
    times.append(now)
    _user_msg_times[chat_id] = times

    # 메시지 길이 제한
    if len(user_message) > 10000:
        await update.message.reply_text("메시지가 너무 깁니다 (최대 10,000자).")
        return

    if chat_id not in user_conversations:
        user_conversations[chat_id] = []

    messages = user_conversations[chat_id]
    messages.append({"role": "user", "content": user_message})

    if len(messages) > 50:
        messages[:] = messages[-50:]
        while messages and messages[0]["role"] != "user":
            messages.pop(0)

    await update.message.chat.send_action("typing")

    try:
        global _engine
        result = await _engine.run_turn_async(messages)

        if result.error:
            logger.warning(f" [AI] {result.error}")

        final_text = result.text
        if not final_text and result.error:
            final_text = result.error

        if final_text:
            if len(final_text) > 4000:
                chunks = [final_text[i:i+4000] for i in range(0, len(final_text), 4000)]
                for chunk in chunks:
                    await update.message.reply_text(chunk)
            else:
                await update.message.reply_text(final_text)
        else:
            await update.message.reply_text("(응답 없음)")

        user_conversations[chat_id] = messages

    except Exception as e:
        logger.error(f" [오류] 메시지 처리 실패: {_mask_secrets(str(e))}")
        await update.message.reply_text("오류가 발생했습니다. 잠시 후 다시 시도해주세요.")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """오류 핸들러"""
    logger.error(f" [오류] 업데이트 처리 중 예외 발생: {context.error}", exc_info=context.error)


def main():
    """메인 함수"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error(" [오류] TELEGRAM_BOT_TOKEN 환경변수가 설정되지 않았습니다.")
        sys.exit(1)
    if not ANTHROPIC_API_KEY:
        logger.error(" [오류] ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
        sys.exit(1)
    if not ALLOWED_CHAT_IDS:
        logger.error(" [오류] TELEGRAM_ALLOWED_USERS 환경변수가 설정되지 않았습니다.")
        logger.error(" [안내] .env 파일에 허용할 chat_id를 쉼표로 구분하여 추가하세요.")
        logger.error(" [예시] TELEGRAM_ALLOWED_USERS=123456789,987654321")
        sys.exit(1)

    logger.info(" [시작] 켈리 텔레그램 봇을 시작합니다...")
    logger.info(f" [보안] 허용된 사용자: {len(ALLOWED_CHAT_IDS)}명")
    logger.info(f" [보안] 제한된 도구: {', '.join(RESTRICTED_TOOLS)}")
    logger.info(f" [제한] 일일 API 호출 상한: {MAX_DAILY_CALLS}회")

    # LLM Provider 초기화 (폴백: Anthropic 직접 사용)
    global _tool_mgr, _provider, _client, _system_prompt, _engine
    _tool_mgr = ToolManager()

    if _use_provider:
        try:
            _provider = get_provider()
            _client = None
            logger.info(f" [LLM] {_provider.PROVIDER_NAME} ({_provider.model})")
        except Exception as e:
            logger.warning(f" [LLM] 프로바이더 초기화 실패, Anthropic 직접 사용: {e}")
            _provider = None
            _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    else:
        _provider = None
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    _system_prompt = load_telegram_system_prompt()

    # ConversationEngine 초기화
    _engine = ConversationEngine(
        provider=_provider,
        client=_client,
        tool_mgr=_tool_mgr,
        system_prompt=_system_prompt,
        restricted_tools=RESTRICTED_TOOLS,
    )

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("usage", usage_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info(" [실행] 봇이 실행 중입니다. Ctrl+C로 종료하세요.")
    app.run_polling()


if __name__ == "__main__":
    main()
