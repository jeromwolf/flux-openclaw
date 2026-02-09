import os
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


PROTECTED_FILES = {".env", "main.py", "instruction.md", ".gitignore", "requirements.txt", "security.md", "style.md", "ws_server.py", "telegram_bot.py"}
PROTECTED_DIRS = {"tools"}
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
        if resolved.name in PROTECTED_FILES:
            return f"Error: 보호된 파일입니다: {resolved.name}"

        # 보호 디렉토리 체크 (tools/ 내 기존 파일 덮어쓰기 방지)
        try:
            rel = resolved.relative_to(cwd)
            if rel.parts and rel.parts[0] in PROTECTED_DIRS and resolved.exists():
                return f"Error: 보호된 디렉토리의 기존 파일은 수정할 수 없습니다: {path}"
        except ValueError:
            pass

        if resolved.exists():
            confirm = input(f"'{path}' 파일이 이미 존재합니다. 덮어쓰시겠습니까? (Y/N): ").strip().upper()
            if confirm != "Y":
                return "저장 취소됨"

        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content)
        return f"저장 완료: {path}"
    except Exception as e:
        return f"Error: 파일 저장 실패"


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) > 2:
        print(main(sys.argv[1], sys.argv[2]))
    else:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
