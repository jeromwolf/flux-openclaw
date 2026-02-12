"""JSON 정리/포맷팅 도구"""

import json

SCHEMA = {
    "name": "json_format",
    "description": "JSON 문자열을 포맷팅, 압축, 키 정렬, 경로 추출합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "json_string": {
                "type": "string",
                "description": "처리할 JSON 문자열"
            },
            "action": {
                "type": "string",
                "enum": ["prettify", "minify", "sort_keys", "extract_path", "validate"],
                "description": "수행할 작업 (prettify, minify, sort_keys, extract_path, validate)"
            },
            "indent": {
                "type": "integer",
                "description": "들여쓰기 칸 수 (기본값: 2)"
            },
            "path": {
                "type": "string",
                "description": "추출할 경로 (점 표기법, 예: 'a.b.c')"
            }
        },
        "required": ["json_string", "action"]
    }
}


def _extract_path(data, path):
    keys = path.split(".")
    current = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list):
            try:
                idx = int(key)
                current = current[idx]
            except (ValueError, IndexError):
                return None, f"경로를 찾을 수 없습니다: {key}"
        else:
            return None, f"경로를 찾을 수 없습니다: {key}"
    return current, None


def main(**kwargs):
    json_string = kwargs.get("json_string", "")
    action = kwargs.get("action", "prettify")
    indent = kwargs.get("indent", 2)
    path = kwargs.get("path", "")

    # 파싱
    try:
        data = json.loads(json_string)
    except json.JSONDecodeError as e:
        if action == "validate":
            return {"valid": False, "error": str(e)}
        return {"error": f"잘못된 JSON입니다: {e}"}

    if action == "validate":
        kind = "dict" if isinstance(data, dict) else "list" if isinstance(data, list) else "string" if isinstance(data, str) else "number" if isinstance(data, (int, float)) else "boolean" if isinstance(data, bool) else "null" if data is None else "unknown"
        return {"valid": True, "type": kind}

    if action == "prettify":
        result = json.dumps(data, indent=indent, ensure_ascii=False)
        return {"result": result}

    if action == "minify":
        result = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        return {"result": result}

    if action == "sort_keys":
        result = json.dumps(data, indent=indent, sort_keys=True, ensure_ascii=False)
        return {"result": result}

    if action == "extract_path":
        if not path:
            return {"error": "extract_path 작업에는 path가 필요합니다."}
        value, err = _extract_path(data, path)
        if err:
            return {"error": err}
        return {"result": value}

    return {"error": f"알 수 없는 작업: {action}"}


if __name__ == "__main__":
    sample = '{"name":"홍길동","age":30,"address":{"city":"서울","zip":"12345"}}'
    print(main(json_string=sample, action="prettify"))
    print(main(json_string=sample, action="minify"))
    print(main(json_string=sample, action="sort_keys"))
    print(main(json_string=sample, action="extract_path", path="address.city"))
    print(main(json_string=sample, action="validate"))
