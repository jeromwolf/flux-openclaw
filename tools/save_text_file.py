import os
import sys
from pathlib import Path

SCHEMA = {
    "name": "save_text_file",
    "description": "텍스트 문자열을 파일에 저장합니다. 파이썬 코드 등 긴 문자열도 저장할 수 있습니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "저장할 파일 경로"},
            "content": {"type": "string", "description": "파일에 저장할 문자열 내용"},
        },
        "required": ["path", "content"],
    },
}


PROTECTED_FILES = {".env", "main.py", "core.py", "instruction.md", ".gitignore", "requirements.txt", "security.md", "style.md", "ws_server.py", "telegram_bot.py", ".tool_approved.json", "daemon.py", "scheduler.py", "memory_store.py", "llm_provider.py", "discord_bot.py", "slack_bot.py", "tool_marketplace.py", "onboarding.py", "dashboard_server.py", "knowledge_base.py", "plugin_sdk.py", "conversation_engine.py"}
PROTECTED_DIRS = {"tools", "marketplace", "dashboard", "knowledge", "openclaw", "bots", "trading"}
MAX_CONTENT_SIZE = 1024 * 1024  # 1MB


def main(path, content):
    try:
        cwd = Path(".").resolve()
        resolved = Path(path).resolve()

        # 콘텐츠 크기 제한
        if len(content) > MAX_CONTENT_SIZE:
            return f"Error: 파일 크기가 1MB를 초과합니다."

        # 심볼릭 링크 차단
        if Path(path).is_symlink():
            return "Error: 심볼릭 링크는 허용되지 않습니다."

        # 워크스페이스 외부 접근 차단
        if not resolved == cwd and not str(resolved).startswith(str(cwd) + os.sep):
            return "Error: 현재 디렉토리 범위 밖에는 저장할 수 없습니다."

        # 보호 파일 체크
        if resolved.name.lower() in PROTECTED_FILES:
            return f"Error: 보호된 파일입니다: {resolved.name}"

        # 보호 디렉토리 체크 (tools/ 내 파일 생성·수정 전면 차단)
        try:
            rel = resolved.relative_to(cwd)
            if rel.parts and rel.parts[0] in PROTECTED_DIRS:
                return f"Error: 보호된 디렉토리에는 파일을 생성하거나 수정할 수 없습니다: {path}"
        except ValueError:
            pass

        if resolved.exists():
            if not sys.stdin.isatty():
                return "Error: 비대화형 환경에서는 기존 파일을 덮어쓸 수 없습니다."
            confirm = input(f"'{path}' 파일이 이미 존재합니다. 덮어쓰시겠습니까? (Y/N): ").strip().upper()
            if confirm != "Y":
                return "저장 취소됨"

        resolved.parent.mkdir(parents=True, exist_ok=True)
        # O_NOFOLLOW: 심볼릭 링크 추종 방지 (TOCTOU 방지)
        try:
            fd = os.open(str(resolved), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, 'w') as f:
                f.write(content)
        except OSError as e:
            if e.errno == 40:  # ELOOP - symlink detected
                return "Error: 심볼릭 링크는 허용되지 않습니다."
            raise
        return f"저장 완료: {path}"
    except Exception as e:
        return f"Error: 파일 저장 실패"


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) > 2:
        print(main(sys.argv[1], sys.argv[2]))
    else:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
