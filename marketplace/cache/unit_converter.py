"""단위 변환 도구 (길이, 무게, 온도, 부피, 속도)"""

SCHEMA = {
    "name": "unit_convert",
    "description": "단위 변환 도구입니다. 길이, 무게, 온도, 부피, 속도 단위를 변환합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "value": {
                "type": "number",
                "description": "변환할 값"
            },
            "from_unit": {
                "type": "string",
                "description": "원본 단위 (예: m, kg, C, L, km/h)"
            },
            "to_unit": {
                "type": "string",
                "description": "대상 단위 (예: ft, lb, F, gal, mph)"
            }
        },
        "required": ["value", "from_unit", "to_unit"]
    }
}

# 길이: 미터 기준
LENGTH_TO_M = {
    "m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 0.001,
    "mi": 1609.344, "ft": 0.3048, "in": 0.0254, "yd": 0.9144,
}

# 무게: 킬로그램 기준
WEIGHT_TO_KG = {
    "kg": 1.0, "g": 0.001, "mg": 0.000001,
    "lb": 0.45359237, "oz": 0.028349523125,
}

# 부피: 리터 기준
VOLUME_TO_L = {
    "L": 1.0, "mL": 0.001, "gal": 3.785411784,
    "qt": 0.946352946, "pt": 0.473176473, "cup": 0.236588,
}

# 속도: m/s 기준
SPEED_TO_MS = {
    "m/s": 1.0, "km/h": 1.0 / 3.6, "mph": 0.44704,
    "kn": 0.514444, "ft/s": 0.3048,
}

UNIT_GROUPS = [
    ("길이", LENGTH_TO_M),
    ("무게", WEIGHT_TO_KG),
    ("부피", VOLUME_TO_L),
    ("속도", SPEED_TO_MS),
]


def _find_group(unit):
    for name, table in UNIT_GROUPS:
        if unit in table:
            return name, table
    return None, None


def _convert_temperature(value, from_unit, to_unit):
    temps = {"C", "F", "K"}
    if from_unit not in temps or to_unit not in temps:
        return None
    # 먼저 섭씨로 변환
    if from_unit == "C":
        c = value
    elif from_unit == "F":
        c = (value - 32) * 5.0 / 9.0
    else:
        c = value - 273.15
    # 섭씨에서 대상으로 변환
    if to_unit == "C":
        return round(c, 6)
    elif to_unit == "F":
        return round(c * 9.0 / 5.0 + 32, 6)
    else:
        return round(c + 273.15, 6)


def main(**kwargs):
    value = kwargs.get("value")
    from_unit = kwargs.get("from_unit", "").strip()
    to_unit = kwargs.get("to_unit", "").strip()

    if value is None:
        return {"error": "value는 필수입니다."}
    if not from_unit or not to_unit:
        return {"error": "from_unit과 to_unit은 필수입니다."}

    # 온도 체크
    if from_unit in {"C", "F", "K"} or to_unit in {"C", "F", "K"}:
        result = _convert_temperature(value, from_unit, to_unit)
        if result is not None:
            return {"result": result, "from": from_unit, "to": to_unit, "category": "온도"}
        return {"error": "지원하지 않는 온도 단위입니다."}

    from_name, from_table = _find_group(from_unit)
    to_name, to_table = _find_group(to_unit)

    if from_table is None:
        return {"error": f"알 수 없는 단위: {from_unit}"}
    if to_table is None:
        return {"error": f"알 수 없는 단위: {to_unit}"}
    if from_table is not to_table:
        return {"error": f"다른 종류의 단위는 변환할 수 없습니다: {from_unit}({from_name}) -> {to_unit}({to_name})"}

    base_value = value * from_table[from_unit]
    result = base_value / to_table[to_unit]

    return {"result": round(result, 6), "from": from_unit, "to": to_unit, "category": from_name}


if __name__ == "__main__":
    print(main(value=100, from_unit="cm", to_unit="in"))
    print(main(value=0, from_unit="C", to_unit="F"))
    print(main(value=60, from_unit="mph", to_unit="km/h"))
