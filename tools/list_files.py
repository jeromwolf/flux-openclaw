import os
from pathlib import Path

SCHEMA = {
    "name": "list_files",
    "description": "지정한 디렉토리의 파일 목록을 반환합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "조회할 디렉토리 경로"},
        },
        "required": ["path"],
    },
}


def main(path):
    try:
        cwd = Path(".").resolve()
        resolved = Path(path).resolve()

        # 심볼릭 링크 차단
        if Path(path).is_symlink():
            return "Error: 심볼릭 링크는 허용되지 않습니다."

        # 워크스페이스 외부 접근 차단
        if not resolved == cwd and not str(resolved).startswith(str(cwd) + os.sep):
            return "Error: 현재 디렉토리의 하위 경로만 접근할 수 있습니다."

        if not resolved.is_dir():
            return f"Error: 디렉토리가 존재하지 않습니다: {path}"

        files = os.listdir(resolved)
        return str(files)
    except Exception:
        return "Error: 디렉토리를 조회할 수 없습니다."


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) > 1:
        print(main(sys.argv[1]))
    else:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
