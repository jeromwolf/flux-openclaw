#!/usr/bin/env python3
"""
flux-openclaw Discord 봇 인터페이스
보안: 허용된 서버/채널만 접근, 위험한 도구는 차단
"""

import os
import sys
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Set

from dotenv import load_dotenv

try:
    import discord
    from discord import app_commands
    from discord.ext import commands
except ImportError:
    print("오류: discord.py 라이브러리가 설치되지 않았습니다.")
    print("설치 명령: pip install discord.py")
    sys.exit(1)

# core.py에서 공유 모듈 임포트
from core import (
    ToolManager, _mask_secrets,
    load_usage,
    load_system_prompt,
)
from conversation_engine import ConversationEngine

# llm_provider 선택적 import
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
# 환경변수 로드
# ============================================================

DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

# 허용된 서버(길드) 목록
_allowed_guilds_raw = os.environ.get("DISCORD_ALLOWED_GUILDS", "")
DISCORD_ALLOWED_GUILDS: Set[int] = set()
if _allowed_guilds_raw.strip():
    try:
        DISCORD_ALLOWED_GUILDS = {int(x.strip()) for x in _allowed_guilds_raw.split(",") if x.strip()}
        logger.info(f" [보안] 허용된 서버: {len(DISCORD_ALLOWED_GUILDS)}개")
    except ValueError:
        logger.error(" [오류] DISCORD_ALLOWED_GUILDS 형식 오류. 쉼표로 구분된 숫자여야 합니다.")
        sys.exit(1)

# 허용된 채널 목록
_allowed_channels_raw = os.environ.get("DISCORD_ALLOWED_CHANNELS", "")
DISCORD_ALLOWED_CHANNELS: Set[int] = set()
if _allowed_channels_raw.strip():
    try:
        DISCORD_ALLOWED_CHANNELS = {int(x.strip()) for x in _allowed_channels_raw.split(",") if x.strip()}
        logger.info(f" [보안] 허용된 채널: {len(DISCORD_ALLOWED_CHANNELS)}개")
    except ValueError:
        logger.error(" [오류] DISCORD_ALLOWED_CHANNELS 형식 오류. 쉼표로 구분된 숫자여야 합니다.")
        sys.exit(1)

# LLM 설정
LLM_PROVIDER_NAME = os.environ.get("LLM_PROVIDER", "anthropic")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514")

# ============================================================
# 보안 설정
# ============================================================

# Discord에서 차단할 위험한 도구 목록
RESTRICTED_TOOLS = {"save_text_file", "screen_capture", "list_files"}

# 일일 API 호출 제한
MAX_DAILY_CALLS = 100

# 사용자별 Rate Limiting (분당 메시지 수)
USER_RATE_LIMIT = 10

# Discord 메시지 길이 제한
DISCORD_MSG_LIMIT = 2000

# ============================================================
# 상태 관리
# ============================================================

# 사용자별 Rate Limiting 타임스탬프
_user_msg_times: Dict[int, List[datetime]] = {}

# 대화 히스토리: key = "guild_channel_user" 또는 "dm_user"
user_conversations: Dict[str, List[dict]] = {}

# ============================================================
# 글로벌 싱글톤
# ============================================================

_tool_mgr: Optional[ToolManager] = None
_provider = None  # LLMProvider 인스턴스 또는 anthropic.Anthropic 클라이언트
_provider_type: str = "none"  # "llm_provider", "anthropic_direct"
_system_prompt: str = ""
_engine: Optional[ConversationEngine] = None


# ============================================================
# 헬퍼 함수
# ============================================================

def _conversation_key(message: discord.Message) -> str:
    """대화 히스토리 키 생성: guild_channel_user 또는 dm_user"""
    if isinstance(message.channel, discord.DMChannel):
        return f"dm_{message.author.id}"
    return f"{message.guild.id}_{message.channel.id}_{message.author.id}"


def load_discord_system_prompt() -> str:
    """Discord 전용 시스템 프롬프트"""
    extra = (
        "\n\n## Discord 봇 모드\n"
        "- 현재 Discord 봇으로 대화하고 있습니다.\n"
        f"- 보안상 다음 도구는 사용할 수 없습니다: {', '.join(RESTRICTED_TOOLS)}\n"
        "- 응답은 간결하게 유지하세요 (Discord 메시지 제한 2000자 고려).\n"
        "- 마크다운 서식을 사용할 수 있습니다.\n"
    )
    return load_system_prompt(extra_suffix=extra)


def check_discord_daily_limit():
    """Discord용 일일 제한 확인. (허용 여부, 현재 호출 수, 최대 호출 수) 반환"""
    usage = load_usage()
    today = datetime.now().strftime("%Y-%m-%d")
    if usage.get("date") != today:
        return True, 0, MAX_DAILY_CALLS
    current_calls = usage.get("calls", 0)
    return current_calls < MAX_DAILY_CALLS, current_calls, MAX_DAILY_CALLS


def is_tool_allowed(tool_name: str) -> bool:
    """도구가 Discord에서 허용되는지 확인"""
    return tool_name not in RESTRICTED_TOOLS


def split_message(text: str, limit: int = DISCORD_MSG_LIMIT) -> List[str]:
    """긴 메시지를 Discord 제한에 맞게 분할.

    코드 블록이 잘리지 않도록 줄 단위로 분할하되,
    제한 내에서 최대한 많은 내용을 포함합니다.
    """
    if len(text) <= limit:
        return [text]

    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break

        # 제한 내에서 마지막 줄바꿈 위치 찾기
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1 or split_at < limit // 2:
            # 줄바꿈이 없거나 너무 앞에 있으면 공백으로 분할
            split_at = text.rfind(" ", 0, limit)
        if split_at == -1 or split_at < limit // 2:
            # 그래도 없으면 강제 분할
            split_at = limit

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


def check_rate_limit(user_id: int) -> bool:
    """사용자별 Rate Limiting 확인. 허용이면 True 반환"""
    now = datetime.now()

    if user_id in _user_msg_times:
        _user_msg_times[user_id] = [
            t for t in _user_msg_times[user_id] if (now - t).total_seconds() < 60
        ]
        if not _user_msg_times[user_id]:
            del _user_msg_times[user_id]

    times = _user_msg_times.get(user_id, [])
    if len(times) >= USER_RATE_LIMIT:
        return False

    times.append(now)
    _user_msg_times[user_id] = times
    return True


# ============================================================
# Discord 봇
# ============================================================

class KellyBot(commands.Bot):
    """켈리 Discord 봇"""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        """슬래시 커맨드 동기화"""
        await self.tree.sync()
        logger.info(" [Discord] 슬래시 커맨드 동기화 완료")

    async def on_ready(self):
        logger.info(f" [Discord] {self.user} 로그인 완료")
        logger.info(f" [Discord] 서버 {len(self.guilds)}개 연결됨")
        if DISCORD_ALLOWED_GUILDS:
            logger.info(f" [보안] 허용 서버: {DISCORD_ALLOWED_GUILDS}")
        else:
            logger.info(" [보안] 모든 서버 허용 (DISCORD_ALLOWED_GUILDS 미설정)")
        if DISCORD_ALLOWED_CHANNELS:
            logger.info(f" [보안] 허용 채널: {DISCORD_ALLOWED_CHANNELS}")
        else:
            logger.info(" [보안] 모든 채널 허용 (DISCORD_ALLOWED_CHANNELS 미설정)")

    async def on_message(self, message: discord.Message):
        """메시지 수신 핸들러"""
        # 봇 자신의 메시지 무시
        if message.author.bot:
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mentioned = self.user in message.mentions if self.user else False

        # DM이 아니고 멘션도 아니면 슬래시 커맨드만 처리
        if not is_dm and not is_mentioned:
            await self.process_commands(message)
            return

        # 서버/채널 제한 확인 (DM은 제한 없음)
        if not is_dm:
            if DISCORD_ALLOWED_GUILDS and message.guild.id not in DISCORD_ALLOWED_GUILDS:
                logger.warning(
                    f" [보안] 허용되지 않은 서버에서 접근: guild={message.guild.id}"
                )
                return
            if DISCORD_ALLOWED_CHANNELS and message.channel.id not in DISCORD_ALLOWED_CHANNELS:
                logger.warning(
                    f" [보안] 허용되지 않은 채널에서 접근: channel={message.channel.id}"
                )
                return

        # 멘션 텍스트에서 봇 멘션 제거
        content = message.content
        if self.user:
            content = content.replace(f"<@{self.user.id}>", "").strip()
            content = content.replace(f"<@!{self.user.id}>", "").strip()
        if not content:
            return

        await self._handle_message(message, content)

    async def _handle_message(self, message: discord.Message, content: str):
        """메시지 처리 - Claude API 호출 및 응답"""
        user_id = message.author.id

        # 일일 API 호출 제한 확인
        allowed, current_calls, max_calls = check_discord_daily_limit()
        if not allowed:
            await message.channel.send(
                f"일일 API 호출 제한에 도달했습니다.\n"
                f"오늘 {current_calls}/{max_calls}회 사용\n"
                f"내일 다시 시도해주세요."
            )
            return

        # Rate Limiting
        if not check_rate_limit(user_id):
            await message.channel.send(
                "메시지를 너무 빠르게 보내고 있습니다. 잠시 후 다시 시도해주세요."
            )
            return

        # 메시지 길이 제한
        if len(content) > 10000:
            await message.channel.send("메시지가 너무 깁니다 (최대 10,000자).")
            return

        # 대화 히스토리 관리
        conv_key = _conversation_key(message)
        if conv_key not in user_conversations:
            user_conversations[conv_key] = []

        messages_history = user_conversations[conv_key]
        messages_history.append({"role": "user", "content": content})

        # 히스토리 50개 제한
        if len(messages_history) > 50:
            messages_history[:] = messages_history[-50:]
            while messages_history and messages_history[0]["role"] != "user":
                messages_history.pop(0)

        # 타이핑 표시
        try:
            async with message.channel.typing():
                final_text = await self._process_with_tools(messages_history, conv_key)
        except Exception as e:
            logger.error(f" [오류] 메시지 처리 실패: {_mask_secrets(str(e))}")
            await message.channel.send("오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
            return

        # 응답 전송
        if final_text:
            chunks = split_message(final_text)
            for chunk in chunks:
                if chunk.strip():
                    await message.channel.send(chunk)
        else:
            await message.channel.send("(응답 없음)")

        # 히스토리 저장
        user_conversations[conv_key] = messages_history

    async def _process_with_tools(self, messages_history: List[dict], conv_key: str) -> str:
        """ConversationEngine을 사용한 LLM 응답 생성"""
        global _engine

        result = await _engine.run_turn_async(messages_history)

        if result.error:
            logger.warning(f" [AI] {conv_key}: {result.error}")

        return result.text or result.error or ""


# ============================================================
# 봇 인스턴스 및 슬래시 커맨드
# ============================================================

bot = KellyBot()


@bot.tree.command(name="help", description="켈리 봇 도움말")
async def help_command(interaction: discord.Interaction):
    """도움말 슬래시 커맨드"""
    help_msg = (
        "**켈리 봇 사용법**\n\n"
        "1. 봇을 @멘션하면 Claude AI가 답변합니다.\n"
        "2. DM으로도 대화할 수 있습니다.\n"
        "3. 파일 읽기, 날씨, 검색 등의 도구를 자동으로 사용합니다.\n"
        "4. 대화 기록은 채널+사용자별로 유지됩니다.\n\n"
        "**슬래시 커맨드:**\n"
        "`/help` - 이 도움말\n"
        "`/reset` - 대화 기록 초기화\n"
        "`/usage` - API 사용량 확인\n\n"
        f"**보안상 제한된 도구:** {', '.join(RESTRICTED_TOOLS)}"
    )
    await interaction.response.send_message(help_msg, ephemeral=True)


@bot.tree.command(name="reset", description="대화 기록 초기화")
async def reset_command(interaction: discord.Interaction):
    """대화 기록 초기화 슬래시 커맨드"""
    user_id = interaction.user.id

    # 해당 사용자의 모든 대화 키를 찾아 삭제
    keys_to_delete = [
        k for k in user_conversations if k.endswith(f"_{user_id}") or k == f"dm_{user_id}"
    ]

    if keys_to_delete:
        for key in keys_to_delete:
            del user_conversations[key]
        await interaction.response.send_message(
            f"대화 기록이 초기화되었습니다. ({len(keys_to_delete)}개 세션)",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            "초기화할 대화 기록이 없습니다.", ephemeral=True
        )


@bot.tree.command(name="usage", description="API 사용량 확인")
async def usage_command(interaction: discord.Interaction):
    """API 사용량 확인 슬래시 커맨드"""
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
            f"**오늘의 API 사용량** ({today})\n\n"
            f"API 호출: {calls}/{MAX_DAILY_CALLS}회\n"
            f"남은 호출: {remaining}회\n"
            f"입력 토큰: {input_tokens:,}\n"
            f"출력 토큰: {output_tokens:,}\n"
            f"총 토큰: {input_tokens + output_tokens:,}"
        )

    await interaction.response.send_message(msg, ephemeral=True)


# ============================================================
# 메인 진입점
# ============================================================

def main():
    """메인 함수"""
    global _tool_mgr, _provider, _provider_type, _system_prompt, _engine

    if not DISCORD_BOT_TOKEN:
        logger.error(" [오류] DISCORD_BOT_TOKEN 환경변수를 설정하세요.")
        sys.exit(1)

    # 도구 매니저 초기화
    _tool_mgr = ToolManager()

    # LLM 프로바이더 초기화
    _llm_provider = None
    _llm_client = None

    if get_provider is not None:
        try:
            _llm_provider = get_provider()
            _provider = _llm_provider
            _provider_type = "llm_provider"
            logger.info(f" [LLM] llm_provider 사용 (provider={LLM_PROVIDER_NAME}, model={LLM_MODEL})")
        except Exception as e:
            logger.warning(f" [LLM] llm_provider 초기화 실패: {e}. anthropic 직접 사용으로 폴백합니다.")
            _llm_provider = None

    if _llm_provider is None:
        # 폴백: anthropic 직접 사용
        try:
            import anthropic
        except ImportError:
            logger.error(" [오류] anthropic 라이브러리가 설치되지 않았습니다.")
            logger.error(" 설치 명령: pip install anthropic")
            sys.exit(1)

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.error(" [오류] ANTHROPIC_API_KEY 환경변수를 설정하세요.")
            sys.exit(1)

        _llm_client = anthropic.Anthropic(api_key=api_key)
        _provider = _llm_client
        _provider_type = "anthropic_direct"
        logger.info(f" [LLM] anthropic 직접 사용 (model={LLM_MODEL})")

    # 시스템 프롬프트 로드
    _system_prompt = load_discord_system_prompt()

    # ConversationEngine 초기화
    _engine = ConversationEngine(
        provider=_llm_provider,
        client=_llm_client,
        tool_mgr=_tool_mgr,
        system_prompt=_system_prompt,
        restricted_tools=RESTRICTED_TOOLS,
    )

    logger.info(" [시작] 켈리 Discord 봇을 시작합니다...")
    logger.info(f" [보안] 제한된 도구: {', '.join(RESTRICTED_TOOLS)}")
    logger.info(f" [제한] 일일 API 호출 상한: {MAX_DAILY_CALLS}회")
    logger.info(f" [제한] 사용자 Rate Limit: {USER_RATE_LIMIT}회/분")

    bot.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()
