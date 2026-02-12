"""시간 계산 도구 (날짜 차이, 시간 변환, 포맷 변환)"""

import datetime
import calendar
import math

SCHEMA = {
    "name": "time_calc",
    "description": "날짜 차이 계산, 시간 단위 변환, 날짜 포맷 변환 등 시간 관련 계산을 수행합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["date_diff", "time_convert", "format_date", "add_days", "weekday", "now"],
                "description": "수행할 작업"
            },
            "date1": {
                "type": "string",
                "description": "첫 번째 날짜 (YYYY-MM-DD 형식)"
            },
            "date2": {
                "type": "string",
                "description": "두 번째 날짜 (YYYY-MM-DD 형식)"
            },
            "value": {
                "type": "number",
                "description": "변환할 시간 값"
            },
            "from_unit": {
                "type": "string",
                "description": "원본 시간 단위 (seconds, minutes, hours, days, weeks)"
            },
            "to_unit": {
                "type": "string",
                "description": "대상 시간 단위"
            },
            "format": {
                "type": "string",
                "description": "날짜 출력 포맷 (예: '%Y년 %m월 %d일')"
            },
            "days": {
                "type": "integer",
                "description": "더할 일수 (음수 가능)"
            }
        },
        "required": ["action"]
    }
}

TIME_TO_SECONDS = {
    "seconds": 1,
    "minutes": 60,
    "hours": 3600,
    "days": 86400,
    "weeks": 604800,
}

WEEKDAY_NAMES_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]


def _parse_date(date_str):
    try:
        return datetime.datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def main(**kwargs):
    action = kwargs.get("action", "now")

    if action == "now":
        now = datetime.datetime.now()
        fmt = kwargs.get("format", "%Y-%m-%d %H:%M:%S")
        return {"now": now.strftime(fmt), "timestamp": int(now.timestamp())}

    if action == "date_diff":
        d1 = _parse_date(kwargs.get("date1"))
        d2 = _parse_date(kwargs.get("date2"))
        if not d1 or not d2:
            return {"error": "유효한 날짜 2개가 필요합니다 (YYYY-MM-DD)."}
        delta = d2 - d1
        total_seconds = int(delta.total_seconds())
        return {
            "days": delta.days,
            "total_seconds": total_seconds,
            "total_hours": round(total_seconds / 3600, 2),
            "weeks": delta.days // 7,
            "remaining_days": delta.days % 7,
        }

    if action == "time_convert":
        value = kwargs.get("value")
        from_unit = kwargs.get("from_unit", "seconds")
        to_unit = kwargs.get("to_unit", "minutes")
        if value is None:
            return {"error": "value는 필수입니다."}
        if from_unit not in TIME_TO_SECONDS:
            return {"error": f"알 수 없는 단위: {from_unit}"}
        if to_unit not in TIME_TO_SECONDS:
            return {"error": f"알 수 없는 단위: {to_unit}"}
        seconds = value * TIME_TO_SECONDS[from_unit]
        result = seconds / TIME_TO_SECONDS[to_unit]
        return {"result": round(result, 6), "from": from_unit, "to": to_unit}

    if action == "format_date":
        d = _parse_date(kwargs.get("date1"))
        if not d:
            return {"error": "유효한 날짜가 필요합니다 (YYYY-MM-DD)."}
        fmt = kwargs.get("format", "%Y년 %m월 %d일")
        return {"formatted": d.strftime(fmt), "original": kwargs.get("date1")}

    if action == "add_days":
        d = _parse_date(kwargs.get("date1"))
        days = kwargs.get("days", 0)
        if not d:
            return {"error": "유효한 날짜가 필요합니다 (YYYY-MM-DD)."}
        result = d + datetime.timedelta(days=days)
        return {"result": result.strftime("%Y-%m-%d"), "original": kwargs.get("date1"), "days_added": days}

    if action == "weekday":
        d = _parse_date(kwargs.get("date1"))
        if not d:
            return {"error": "유효한 날짜가 필요합니다 (YYYY-MM-DD)."}
        wd = d.weekday()
        return {"weekday": WEEKDAY_NAMES_KR[wd], "weekday_number": wd, "date": kwargs.get("date1")}

    return {"error": f"알 수 없는 작업: {action}"}


if __name__ == "__main__":
    print(main(action="now"))
    print(main(action="date_diff", date1="2025-01-01", date2="2026-02-11"))
    print(main(action="time_convert", value=3600, from_unit="seconds", to_unit="hours"))
    print(main(action="weekday", date1="2026-02-11"))
