import os
import re
from pathlib import Path

SCHEMA = {
    "name": "read_text_file",
    "description": "텍스트 파일의 내용을 읽어서 반환합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "읽을 파일 경로"},
        },
        "required": ["path"],
    },
}

SECRET_PATTERNS = re.compile(
    r"(sk-ant-[a-zA-Z0-9_-]+|AIza[a-zA-Z0-9_-]+|sk-[a-zA-Z0-9_-]{20,}"
    r"|ghp_[a-zA-Z0-9]{36,}|glpat-[a-zA-Z0-9_-]{20,}"
    r"|xox[bpsa]-[a-zA-Z0-9-]{10,})"
)
BLOCKED_FILES = {".env", ".env.local", ".env.production", ".env.development", "log.md", ".tool_approved.json", "usage_data.json"}
BLOCKED_DIRS = {"history"}


def main(path):
    try:
        cwd = Path(".").resolve()
        resolved = Path(path).resolve()

        # 심볼릭 링크 차단
        if Path(path).is_symlink():
            return "Error: 심볼릭 링크는 허용되지 않습니다."

        # 워크스페이스 외부 접근 차단
        if not resolved == cwd and not str(resolved).startswith(str(cwd) + os.sep):
            return "Error: 현재 디렉토리 범위 밖에는 접근할 수 없습니다."

        # 차단 파일
        if resolved.name.lower() in BLOCKED_FILES:
            return f"Error: 보안상 읽을 수 없는 파일입니다: {resolved.name}"

        # 차단 디렉토리 체크
        try:
            rel = resolved.relative_to(cwd)
            if rel.parts and rel.parts[0] in BLOCKED_DIRS:
                return f"Error: 보안상 읽을 수 없는 디렉토리입니다: {rel.parts[0]}/"
        except ValueError:
            pass

        if not resolved.exists():
            return f"Error: 파일이 존재하지 않습니다: {path}"

        content = resolved.read_text()

        # API 키 패턴 마스킹
        content = SECRET_PATTERNS.sub("[REDACTED]", content)

        return content
    except Exception as e:
        return "Error: 파일 읽기 실패"


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) > 1:
        print(main(sys.argv[1]))
    else:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
