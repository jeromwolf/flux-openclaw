"""진법 변환 도구 (2진, 8진, 16진, 임의 진법)"""

import string

SCHEMA = {
    "name": "base_convert",
    "description": "숫자의 진법을 변환합니다. 2진, 8진, 10진, 16진 및 임의 진법(2-36)을 지원합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "value": {
                "type": "string",
                "description": "변환할 값 (문자열, 예: '255', '0xFF', '11111111')"
            },
            "from_base": {
                "type": "integer",
                "description": "원본 진법 (2-36, 기본값: 10)"
            },
            "to_base": {
                "type": "integer",
                "description": "대상 진법 (2-36, 기본값: 2)"
            },
            "action": {
                "type": "string",
                "enum": ["convert", "to_all", "explain"],
                "description": "작업 유형 (convert: 단일 변환, to_all: 모든 주요 진법으로 변환, explain: 변환 과정 설명)"
            }
        },
        "required": ["value"]
    }
}

DIGITS = string.digits + string.ascii_lowercase


def _to_decimal(value_str, base):
    """임의 진법 문자열을 10진수로 변환"""
    value_str = value_str.strip().lower()
    negative = False
    if value_str.startswith("-"):
        negative = True
        value_str = value_str[1:]

    # 접두사 제거
    if base == 16 and value_str.startswith("0x"):
        value_str = value_str[2:]
    elif base == 8 and value_str.startswith("0o"):
        value_str = value_str[2:]
    elif base == 2 and value_str.startswith("0b"):
        value_str = value_str[2:]

    result = 0
    for ch in value_str:
        digit = DIGITS.index(ch)
        if digit >= base:
            return None, f"'{ch}'는 {base}진법에서 유효하지 않습니다."
        result = result * base + digit

    if negative:
        result = -result
    return result, None


def _from_decimal(decimal_val, base):
    """10진수를 임의 진법 문자열로 변환"""
    if decimal_val == 0:
        return "0"

    negative = decimal_val < 0
    decimal_val = abs(decimal_val)

    digits = []
    while decimal_val > 0:
        digits.append(DIGITS[decimal_val % base])
        decimal_val //= base

    result = "".join(reversed(digits))
    if negative:
        result = "-" + result
    return result


def _format_with_prefix(value_str, base):
    """진법에 따라 접두사 추가"""
    prefixes = {2: "0b", 8: "0o", 16: "0x"}
    prefix = prefixes.get(base, "")
    return prefix + value_str


def main(**kwargs):
    value = kwargs.get("value", "")
    from_base = kwargs.get("from_base", 10)
    to_base = kwargs.get("to_base", 2)
    action = kwargs.get("action", "convert")

    if not value:
        return {"error": "value는 필수입니다."}
    if not (2 <= from_base <= 36):
        return {"error": f"from_base는 2-36 범위여야 합니다: {from_base}"}
    if not (2 <= to_base <= 36):
        return {"error": f"to_base는 2-36 범위여야 합니다: {to_base}"}

    decimal_val, err = _to_decimal(str(value), from_base)
    if err:
        return {"error": err}

    if action == "convert":
        result = _from_decimal(decimal_val, to_base)
        return {
            "result": result,
            "formatted": _format_with_prefix(result, to_base),
            "decimal": decimal_val,
            "from_base": from_base,
            "to_base": to_base,
        }

    if action == "to_all":
        return {
            "decimal": decimal_val,
            "binary": _format_with_prefix(_from_decimal(decimal_val, 2), 2),
            "octal": _format_with_prefix(_from_decimal(decimal_val, 8), 8),
            "hexadecimal": _format_with_prefix(_from_decimal(decimal_val, 16), 16),
            "base36": _from_decimal(decimal_val, 36) if decimal_val >= 0 else None,
            "from_base": from_base,
            "original": value,
        }

    if action == "explain":
        steps = []
        steps.append(f"1. 입력: '{value}' ({from_base}진법)")
        steps.append(f"2. 10진수 변환: {decimal_val}")
        result = _from_decimal(decimal_val, to_base)
        steps.append(f"3. {to_base}진법 변환: {result}")
        steps.append(f"4. 포맷: {_format_with_prefix(result, to_base)}")
        return {"steps": steps, "result": _format_with_prefix(result, to_base)}

    return {"error": f"알 수 없는 작업: {action}"}


if __name__ == "__main__":
    print(main(value="255", from_base=10, to_base=16))
    print(main(value="255", action="to_all"))
    print(main(value="FF", from_base=16, to_base=2, action="explain"))
