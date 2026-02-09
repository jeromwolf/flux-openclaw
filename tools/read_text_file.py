import os

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


def main(path):
    try:
        resolved = os.path.realpath(path)
        cwd = os.path.realpath(".")
        if not resolved.startswith(cwd + os.sep) and resolved != os.path.join(cwd, os.path.basename(path)):
            return "Error: 현재 디렉토리 범위 밖에는 접근할 수 없습니다."
        if not os.path.exists(resolved):
            return f"Error: 파일이 존재하지 않습니다: {path}"
        with open(path, "r") as f:
            return f.read()
    except Exception as e:
        return str(e)


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) > 1:
        print(main(sys.argv[1]))
    else:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
