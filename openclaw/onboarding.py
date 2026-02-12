"""
flux-openclaw 온보딩 마법사

새 사용자가 처음 실행할 때 API 키와 기본 설정을 대화형으로 안내합니다.

보안: getpass 에코 차단, .env 퍼미션 0o600, O_NOFOLLOW 심볼릭 링크 차단,
기존 .env 존재 시 자동 백업, 비대화형 환경 자동 건너뜀
"""

import os
import sys
import re
import getpass
from datetime import datetime
from typing import Optional

_API_KEY_RE = re.compile(r"^(sk-ant-|sk-)[a-zA-Z0-9_-]{17,}$")

_INTERFACES = [
    ("1", "CLI (main.py)", []),
    ("2", "WebSocket (ws_server.py)", ["WS_SECRET_TOKEN"]),
    ("3", "Telegram (telegram_bot.py)", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS"]),
    ("4", "Discord (discord_bot.py)", ["DISCORD_TOKEN"]),
    ("5", "Slack (slack_bot.py)", ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"]),
]

_PROVIDERS = [
    ("1", "anthropic", None),
    ("2", "openai", "OPENAI_API_KEY"),
    ("3", "google", "GOOGLE_API_KEY"),
]

_IFACE_KEYS = [
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS",
    "DISCORD_TOKEN", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "WS_SECRET_TOKEN",
]


class OnboardingWizard:
    """대화형 CLI 설정 마법사"""

    def __init__(self):
        self.env_path = ".env"

    def should_run(self) -> bool:
        """True if .env 없거나 ANTHROPIC_API_KEY 미설정"""
        if not os.path.exists(self.env_path):
            return True
        try:
            with open(self.env_path, "r") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("ANTHROPIC_API_KEY="):
                        val = stripped.split("=", 1)[1].strip()
                        if val and val != "your-api-key-here":
                            return False
        except OSError:
            return True
        return True

    def run(self) -> bool:
        """마법사 실행. True=완료, False=취소"""
        config = {}
        self._step_welcome()

        api_result = self._step_api_key()
        if api_result is None:
            return False
        config.update(api_result)
        config.update(self._step_interface())
        config.update(self._step_optional_features())

        self._write_env(config)
        self._step_summary(config)
        return True

    def _step_welcome(self):
        """환영 메시지"""
        print()
        print("\u2554" + "\u2550" * 46 + "\u2557")
        print("\u2551     flux-openclaw 설정 마법사             \u2551")
        print("\u2551     자기 확장형 AI 에이전트              \u2551")
        print("\u2560" + "\u2550" * 46 + "\u2563")
        print("\u2551  처음 실행을 환영합니다!                 \u2551")
        print("\u2551  이 마법사가 기본 설정을 도와드립니다.   \u2551")
        print("\u255a" + "\u2550" * 46 + "\u255d")
        print()

    def _step_api_key(self) -> Optional[dict]:
        """API 키 수집 (getpass로 마스킹). None이면 취소"""
        print("[1/3] Anthropic API 키 설정")
        print("  https://console.anthropic.com/ 에서 발급받을 수 있습니다.")
        print("  (입력 시 화면에 표시되지 않습니다)\n")

        for attempt in range(3):
            try:
                key = getpass.getpass("  API 키 입력: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  취소되었습니다.")
                return None
            if not key:
                print("  [건너뜀] API 키를 나중에 .env 파일에 직접 입력하세요.")
                return {"ANTHROPIC_API_KEY": ""}
            if _API_KEY_RE.match(key):
                print(f"  [확인] 키 등록됨: {key[:7]}...{key[-4:]}")
                return {"ANTHROPIC_API_KEY": key}
            remaining = 2 - attempt
            if remaining > 0:
                print(f"  [오류] 올바른 형식이 아닙니다 (sk-ant- 또는 sk- 로 시작, 20자 이상)")
                print(f"         남은 시도: {remaining}회")
            else:
                print("  [오류] 3회 실패. API 키를 나중에 .env 파일에 직접 입력하세요.")
        return {"ANTHROPIC_API_KEY": ""}

    def _step_interface(self) -> dict:
        """인터페이스 선택 안내"""
        print("\n[2/3] 인터페이스 선택")
        print("  사용할 인터페이스를 선택하세요 (쉼표로 복수 선택 가능):\n")
        for num, name, tokens in _INTERFACES:
            extra = f" - 필요: {', '.join(tokens)}" if tokens else ""
            print(f"  {num}. {name}{extra}")
        print()
        try:
            raw = input("  선택 [1]: ").strip() or "1"
        except (EOFError, KeyboardInterrupt):
            raw = "1"

        result = {}
        for choice in (c.strip() for c in raw.split(",")):
            for num, name, tokens in _INTERFACES:
                if choice == num and tokens:
                    print(f"\n  -- {name} 토큰 설정 --")
                    for token_name in tokens:
                        try:
                            val = input(f"  {token_name}: ").strip()
                        except (EOFError, KeyboardInterrupt):
                            val = ""
                        if val:
                            result[token_name] = val
        return result

    def _step_optional_features(self) -> dict:
        """선택적 기능 (LLM 프로바이더 등)"""
        print("\n[3/3] LLM 프로바이더 선택 (선택 사항)")
        print("  기본값: anthropic (Claude)\n")
        for num, name, _env in _PROVIDERS:
            default = " (기본)" if num == "1" else ""
            print(f"  {num}. {name}{default}")
        print()
        try:
            raw = input("  선택 [1]: ").strip()
        except (EOFError, KeyboardInterrupt):
            raw = ""
        if not raw or raw == "1":
            return {}

        result = {}
        for num, name, env_key in _PROVIDERS:
            if raw == num:
                result["LLM_PROVIDER"] = name
                if env_key:
                    print(f"\n  {name} API 키가 필요합니다.")
                    try:
                        val = getpass.getpass(f"  {env_key}: ").strip()
                    except (EOFError, KeyboardInterrupt):
                        val = ""
                    if val:
                        result[env_key] = val
                break
        return result

    def _write_env(self, config: dict):
        """안전한 .env 파일 생성 (O_NOFOLLOW, 0o600)"""
        if os.path.exists(self.env_path):
            backup = f".env.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            try:
                os.rename(self.env_path, backup)
                print(f"\n  [백업] 기존 .env -> {backup}")
            except OSError as e:
                print(f"\n  [경고] .env 백업 실패: {e}")

        lines = ["# flux-openclaw 설정 (자동 생성)", ""]
        api_key = config.get("ANTHROPIC_API_KEY", "")
        lines.append(f"ANTHROPIC_API_KEY={api_key}" if api_key else "ANTHROPIC_API_KEY=your-api-key-here")
        lines.append("")

        lines.append("# LLM 프로바이더 (선택)")
        provider = config.get("LLM_PROVIDER")
        lines.append(f"LLM_PROVIDER={provider}" if provider and provider != "anthropic" else "# LLM_PROVIDER=anthropic")
        lines.append("# LLM_MODEL=")
        for _num, _name, env_key in _PROVIDERS:
            if env_key and env_key in config:
                lines.append(f"{env_key}={config[env_key]}")
        lines.append("")

        lines.append("# 인터페이스 토큰 (선택)")
        for key in _IFACE_KEYS:
            lines.append(f"{key}={config[key]}" if key in config else f"# {key}=")
        lines.append("")

        content = "\n".join(lines)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.env_path, flags, 0o600)
            try:
                os.write(fd, content.encode("utf-8"))
            finally:
                os.close(fd)
        except OSError as e:
            print(f"\n  [오류] .env 파일 생성 실패: {e}")

    def _step_summary(self, config: dict):
        """설정 요약 + 다음 단계 안내"""
        print("\n" + "=" * 46)
        print("  설정 완료!")
        print("=" * 46 + "\n")
        api_key = config.get("ANTHROPIC_API_KEY", "")
        if api_key:
            print(f"  API 키: {api_key[:7]}...{api_key[-4:]}")
        else:
            print("  API 키: 미설정 (.env 파일에 직접 입력하세요)")
        print(f"  프로바이더: {config.get('LLM_PROVIDER', 'anthropic')}")

        iface_tokens = [k for k in config if k not in (
            "ANTHROPIC_API_KEY", "LLM_PROVIDER", "LLM_MODEL", "OPENAI_API_KEY", "GOOGLE_API_KEY")]
        if iface_tokens:
            print(f"  인터페이스 토큰: {', '.join(iface_tokens)}")
        print("\n  다음 단계:")
        print("    python main.py          # CLI 실행")
        print("    python telegram_bot.py   # 텔레그램 봇 실행")
        print("    python ws_server.py      # WebSocket 서버 실행\n")


def check_and_run_onboarding() -> bool:
    """온보딩 실행 필요 시 실행. True=완료/불필요, False=사용자취소"""
    if not sys.stdin.isatty():
        return True
    wizard = OnboardingWizard()
    if not wizard.should_run():
        return True
    return wizard.run()


if __name__ == "__main__":
    check_and_run_onboarding()
