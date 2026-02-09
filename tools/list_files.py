import os

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
        resolved = os.path.realpath(path)
        cwd = os.path.realpath(".")
        if not resolved.startswith(cwd + os.sep) and resolved != cwd:
            return "Error: 현재 디렉토리의 하위 경로만 접근할 수 있습니다."
        if not os.path.isdir(resolved):
            return f"Error: 디렉토리가 존재하지 않습니다: {path}"
        files = os.listdir(resolved)
        return str(files)
    except Exception as e:
        return str(e)


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) > 1:
        print(main(sys.argv[1]))
    else:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
