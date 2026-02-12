"""랜덤 값 생성 도구 (숫자, 문자열, 비밀번호, 랜덤 ID)"""

import random
import string
import math
import time

SCHEMA = {
    "name": "random_generate",
    "description": "랜덤 정수, 실수, 문자열, 비밀번호, 랜덤 ID를 생성합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["integer", "float", "string", "password", "random_id",
                         "choice", "shuffle", "dice"],
                "description": "생성 유형"
            },
            "min_val": {
                "type": "number",
                "description": "최솟값 (정수/실수 생성 시)"
            },
            "max_val": {
                "type": "number",
                "description": "최댓값 (정수/실수 생성 시)"
            },
            "length": {
                "type": "integer",
                "description": "길이 (문자열/비밀번호/ID 생성 시, 기본값: 16)"
            },
            "count": {
                "type": "integer",
                "description": "생성 개수 (기본값: 1)"
            },
            "items": {
                "type": "array",
                "items": {"type": "string"},
                "description": "선택/셔플 대상 목록"
            },
            "include_special": {
                "type": "boolean",
                "description": "특수 문자 포함 여부 (비밀번호, 기본값: true)"
            }
        },
        "required": ["action"]
    }
}


def _random_string(length, charset):
    return "".join(random.choice(charset) for _ in range(length))


def _random_id(length):
    chars = string.ascii_lowercase + string.digits
    timestamp_part = hex(int(time.time() * 1000))[2:][:8]
    rand_len = max(1, length - len(timestamp_part))
    rand_part = _random_string(rand_len, chars)
    return (timestamp_part + rand_part)[:length]


def main(**kwargs):
    action = kwargs.get("action", "integer")
    count = max(1, min(kwargs.get("count", 1), 1000))

    if action == "integer":
        min_val = int(kwargs.get("min_val", 0))
        max_val = int(kwargs.get("max_val", 100))
        if min_val > max_val:
            return {"error": "min_val이 max_val보다 클 수 없습니다."}
        results = [random.randint(min_val, max_val) for _ in range(count)]
        return {"results": results if count > 1 else results[0], "range": [min_val, max_val]}

    if action == "float":
        min_val = float(kwargs.get("min_val", 0.0))
        max_val = float(kwargs.get("max_val", 1.0))
        if min_val > max_val:
            return {"error": "min_val이 max_val보다 클 수 없습니다."}
        results = [round(random.uniform(min_val, max_val), 6) for _ in range(count)]
        return {"results": results if count > 1 else results[0], "range": [min_val, max_val]}

    if action == "string":
        length = max(1, min(kwargs.get("length", 16), 1024))
        charset = string.ascii_letters + string.digits
        results = [_random_string(length, charset) for _ in range(count)]
        return {"results": results if count > 1 else results[0], "length": length}

    if action == "password":
        length = max(8, min(kwargs.get("length", 16), 128))
        include_special = kwargs.get("include_special", True)
        charset = string.ascii_letters + string.digits
        if include_special:
            charset += "!@#$%^&*()-_=+"
        results = []
        for _ in range(count):
            pwd = _random_string(length, charset)
            # 최소 요구사항 보장: 대문자, 소문자, 숫자
            pwd_list = list(pwd)
            pwd_list[0] = random.choice(string.ascii_uppercase)
            pwd_list[1] = random.choice(string.ascii_lowercase)
            pwd_list[2] = random.choice(string.digits)
            if include_special:
                pwd_list[3] = random.choice("!@#$%^&*()-_=+")
            random.shuffle(pwd_list)
            results.append("".join(pwd_list))
        return {"results": results if count > 1 else results[0], "length": length}

    if action == "random_id":
        length = max(8, min(kwargs.get("length", 16), 64))
        results = [_random_id(length) for _ in range(count)]
        return {"results": results if count > 1 else results[0], "length": length}

    if action == "choice":
        items = kwargs.get("items", [])
        if not items:
            return {"error": "items 목록이 필요합니다."}
        results = [random.choice(items) for _ in range(count)]
        return {"results": results if count > 1 else results[0]}

    if action == "shuffle":
        items = kwargs.get("items", [])
        if not items:
            return {"error": "items 목록이 필요합니다."}
        shuffled = list(items)
        random.shuffle(shuffled)
        return {"results": shuffled}

    if action == "dice":
        results = [random.randint(1, 6) for _ in range(count)]
        total = sum(results)
        return {"results": results, "total": total, "count": count}

    return {"error": f"알 수 없는 작업: {action}"}


if __name__ == "__main__":
    print(main(action="integer", min_val=1, max_val=100, count=5))
    print(main(action="password", length=20))
    print(main(action="random_id"))
    print(main(action="dice", count=3))
