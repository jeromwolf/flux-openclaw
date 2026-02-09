import requests

SCHEMA = {
    "name": "weather",
    "description": "특정 도시의 현재 날씨와 예보를 가져옵니다. 날씨, 기온, 습도, 바람 등 날씨 관련 질문에 사용합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "날씨를 조회할 도시 이름 (예: Seoul, Busan, Tokyo, New York)",
            },
        },
        "required": ["city"],
    },
}


def main(city):
    try:
        resp = requests.get(
            f"https://wttr.in/{city}?format=j1&lang=ko",
            headers={"User-Agent": "curl/7.68.0"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        cur = data["current_condition"][0]
        weather_desc = cur.get("lang_ko", [{}])[0].get("value", cur.get("weatherDesc", [{}])[0].get("value", ""))

        lines = [
            f"📍 {city} 현재 날씨",
            f"  상태: {weather_desc}",
            f"  온도: {cur['temp_C']}°C (체감 {cur['FeelsLikeC']}°C)",
            f"  습도: {cur['humidity']}%",
            f"  바람: {cur['windspeedKmph']}km/h ({cur.get('winddir16Point', '')})",
            f"  강수량: {cur['precipMM']}mm",
            f"  자외선: {cur.get('uvIndex', 'N/A')}",
            "",
        ]

        forecasts = data.get("weather", [])[:3]
        if forecasts:
            lines.append("📅 예보:")
            for day in forecasts:
                date = day["date"]
                desc = day.get("hourly", [{}])[4].get("lang_ko", [{}])[0].get(
                    "value",
                    day.get("hourly", [{}])[4].get("weatherDesc", [{}])[0].get("value", ""),
                )
                lines.append(
                    f"  {date}: {desc}, "
                    f"{day['mintempC']}°C ~ {day['maxtempC']}°C, "
                    f"강수확률 {day.get('hourly', [{}])[4].get('chanceofrain', '?')}%"
                )

        return "\n".join(lines)

    except requests.exceptions.Timeout:
        return f"Error: 날씨 서버 응답 시간 초과"
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    import sys, json

    if len(sys.argv) > 1:
        print(main(sys.argv[1]))
    else:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
