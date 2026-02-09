import os

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


PROTECTED_FILES = {".env", "main.py"}


def main(path, content):
    try:
        resolved = os.path.realpath(path)
        cwd = os.path.realpath(".")
        if not resolved.startswith(cwd + os.sep) and resolved != os.path.join(cwd, os.path.basename(path)):
            return "Error: 현재 디렉토리 범위 밖에는 저장할 수 없습니다."
        if os.path.basename(resolved) in PROTECTED_FILES:
            return f"Error: 보호된 파일입니다: {os.path.basename(resolved)}"
        if os.path.exists(resolved):
            confirm = input(f"'{path}' 파일이 이미 존재합니다. 덮어쓰시겠습니까? (Y/N): ").strip().upper()
            if confirm != "Y":
                return "저장 취소됨"
        os.makedirs(os.path.dirname(resolved), exist_ok=True) if os.path.dirname(resolved) else None
        with open(path, "w") as f:
            f.write(content)
        return f"저장 완료: {path}"
    except Exception as e:
        return str(e)


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) > 2:
        print(main(sys.argv[1], sys.argv[2]))
    else:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
